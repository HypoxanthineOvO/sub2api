package service

import (
	"context"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/config"
	"github.com/Wei-Shaw/sub2api/internal/pkg/pagination"
	"github.com/Wei-Shaw/sub2api/internal/pkg/timezone"
	"github.com/Wei-Shaw/sub2api/internal/pkg/usagestats"
)

type LabDashboardResponse struct {
	GeneratedAt  string                    `json:"generated_at"`
	Timezone     string                    `json:"timezone"`
	Summary      LabDashboardSummary       `json:"summary"`
	Accounts     []LabDashboardAccount     `json:"accounts"`
	Leaderboard  LabDashboardLeaderboard   `json:"leaderboard"`
	UserUsage24h []LabDashboardUserUsage   `json:"user_usage_24h"`
	RecentUsage  []LabDashboardRecentUsage `json:"recent_usage"`
}

type LabDashboardSummary struct {
	TodayActualCost     float64 `json:"today_actual_cost"`
	TodayRequests       int64   `json:"today_requests"`
	ActiveUsers         int64   `json:"active_users"`
	SchedulableAccounts int     `json:"schedulable_accounts"`
	TotalAccounts       int     `json:"total_accounts"`
	WeekActualCost      float64 `json:"week_actual_cost"`
}

type LabDashboardAccount struct {
	Name                       string   `json:"name"`
	Platform                   string   `json:"platform"`
	Type                       string   `json:"type"`
	PlanType                   string   `json:"plan_type,omitempty"`
	Status                     string   `json:"status"`
	Schedulable                bool     `json:"schedulable"`
	Quota5hUsedPercent         *float64 `json:"quota_5h_used_percent,omitempty"`
	Quota7dUsedPercent         *float64 `json:"quota_7d_used_percent,omitempty"`
	QuotaFactor                float64  `json:"quota_factor"`
	SelectionProbability       *float64 `json:"selection_probability,omitempty"`
	SelectionProbabilityStatus string   `json:"selection_probability_status"`
	TodayRequests              int64    `json:"today_requests"`
	TodayActualCost            float64  `json:"today_actual_cost"`
	SlotLabel                  string   `json:"slot_label,omitempty"`
	SelectedNodeName           string   `json:"selected_node_name,omitempty"`
	SelectedNodeStatus         string   `json:"selected_node_status,omitempty"`
	SelectedNodeObservedAt     string   `json:"selected_node_observed_at,omitempty"`
}

type LabDashboardLeaderboard struct {
	HistoryStartDate string                       `json:"history_start_date,omitempty"`
	HistoryEndDate   string                       `json:"history_end_date,omitempty"`
	Rows             []LabDashboardLeaderboardRow `json:"rows"`
}
type LabDashboardLeaderboardRow struct {
	DisplayName     string     `json:"display_name"`
	TodayActualCost float64    `json:"today_actual_cost"`
	LastActiveAt    *time.Time `json:"last_active_at,omitempty"`
	TotalActualCost float64    `json:"total_actual_cost"`
}
type LabDashboardUserUsage struct {
	Bucket      string  `json:"bucket"`
	DisplayName string  `json:"display_name"`
	Requests    int64   `json:"requests"`
	ActualCost  float64 `json:"actual_cost"`
}
type LabDashboardRecentUsage struct {
	CreatedAt             time.Time `json:"created_at"`
	UserDisplayName       string    `json:"user_display_name"`
	Model                 string    `json:"model"`
	AccountName           string    `json:"account_name,omitempty"`
	SwitchFromAccountName string    `json:"switch_from_account_name,omitempty"`
	SwitchReason          string    `json:"switch_reason,omitempty"`
	ActualCost            float64   `json:"actual_cost"`
}

type LabDashboardService struct {
	usage         *UsageService
	dashboard     *DashboardService
	admin         AdminService
	accounts      *AccountUsageService
	concurrency   *ConcurrencyService
	rateLimit     *RateLimitService
	selectedNodes SelectedNodeEnricher
	cfg           *config.Config
}

func NewLabDashboardService(usage *UsageService, dashboard *DashboardService, admin AdminService, accounts *AccountUsageService, concurrency *ConcurrencyService, rateLimit *RateLimitService, selectedNodes SelectedNodeEnricher, cfg *config.Config) *LabDashboardService {
	return &LabDashboardService{usage: usage, dashboard: dashboard, admin: admin, accounts: accounts, concurrency: concurrency, rateLimit: rateLimit, selectedNodes: selectedNodes, cfg: cfg}
}

func labDashboardDisplayName(displayName, username, email string, id int64) string {
	if value := strings.TrimSpace(displayName); value != "" && !strings.Contains(value, "@") {
		return value
	}
	if value := strings.TrimSpace(username); value != "" && !strings.Contains(value, "@") {
		return value
	}
	return "User " + formatInt64(id)
}

func formatInt64(id int64) string { return strconv.FormatInt(id, 10) }

func labDashboardProbability(scores map[int64]float64, accountID *int64) (*float64, string) {
	if accountID == nil || scores == nil {
		return nil, "unavailable"
	}
	value, ok := scores[*accountID]
	if !ok {
		return nil, "unavailable"
	}
	return &value, "computed"
}

func (s *LabDashboardService) Get(ctx context.Context) (*LabDashboardResponse, error) {
	now := time.Now()
	stats, err := s.dashboard.GetDashboardStats(ctx)
	if err != nil {
		return nil, err
	}
	accounts, _, err := s.admin.ListAccounts(ctx, 1, 100, "", "", "", "", 0, "", "name", "asc")
	if err != nil {
		return nil, err
	}
	accounts = filterLabDashboardAccounts(accounts, s.cfg)
	ids := make([]int64, 0, len(accounts))
	for i := range accounts {
		ids = append(ids, accounts[i].ID)
	}
	today, _ := s.accounts.GetTodayStatsBatch(ctx, ids)
	if s.selectedNodes != nil {
		proxies := make([]*Proxy, 0, len(accounts))
		for i := range accounts {
			if accounts[i].Proxy != nil {
				proxies = append(proxies, accounts[i].Proxy)
			}
		}
		s.selectedNodes.EnrichProxies(ctx, proxies)
	}
	probabilities := map[int64]float64(nil)
	probabilityPool := map[int64]struct{}{}
	if s.cfg != nil && s.cfg.LabDashboard.SchedulerGroupID > 0 {
		gid := s.cfg.LabDashboard.SchedulerGroupID
		pool, poolErr := s.admin.ListOpenAISchedulableAccountsForSchedulerScore(ctx, &gid)
		if poolErr == nil && len(pool) > 0 {
			openAI := make([]*Account, 0, len(pool))
			loads := make([]AccountWithConcurrency, 0, len(pool))
			for i := range pool {
				openAI = append(openAI, &pool[i])
				probabilityPool[pool[i].ID] = struct{}{}
				loads = append(loads, AccountWithConcurrency{ID: pool[i].ID, MaxConcurrency: pool[i].EffectiveLoadFactor()})
			}
			loadMap := map[int64]*AccountLoadInfo{}
			if s.concurrency != nil {
				loadMap, _ = s.concurrency.GetAccountsLoadBatch(ctx, loads)
			}
			var snapshots map[int64]OpenAIAccountSchedulerScoreSnapshot
			if s.rateLimit != nil {
				snapshots = s.rateLimit.BuildOpenAIAccountSchedulerScoreSnapshot(ctx, openAI, loadMap)
			} else {
				snapshots = BuildOpenAIAccountSchedulerScoreSnapshot(openAI, loadMap)
			}
			topK := len(openAI)
			if s.cfg.Gateway.OpenAIWS.LBTopK > 0 && s.cfg.Gateway.OpenAIWS.LBTopK < topK {
				topK = s.cfg.Gateway.OpenAIWS.LBTopK
			}
			probabilities = OpenAIWeightedSelectionProbability(openAI, snapshots, topK, now)
		}
	}
	result := &LabDashboardResponse{GeneratedAt: now.UTC().Format(time.RFC3339), Timezone: configTimezone(s.cfg), Summary: LabDashboardSummary{TodayActualCost: stats.TodayActualCost, TodayRequests: stats.TodayRequests, ActiveUsers: stats.ActiveUsers, TotalAccounts: len(accounts)}, Accounts: make([]LabDashboardAccount, 0, len(accounts))}
	for i := range accounts {
		account := &accounts[i]
		item := LabDashboardAccount{Name: account.Name, Platform: account.Platform, Type: account.Type, Status: account.Status, Schedulable: account.IsSchedulable(), QuotaFactor: OpenAIAccountQuotaTaperFactor(account, now), SelectionProbabilityStatus: "unavailable"}
		if plan, ok := account.Extra["plan_type"].(string); ok {
			item.PlanType = plan
		}
		if value, ok := quotaPercent(account.Extra, "codex_5h_used_percent"); ok {
			item.Quota5hUsedPercent = &value
		}
		if value, ok := quotaPercent(account.Extra, "codex_7d_used_percent"); ok {
			item.Quota7dUsedPercent = &value
		}
		if value, ok := probabilities[account.ID]; ok {
			item.SelectionProbability = &value
			item.SelectionProbabilityStatus = "computed"
		} else if _, ok := probabilityPool[account.ID]; ok {
			item.SelectionProbabilityStatus = "outside_first_choice_pool"
		}
		if itemValue := today[account.ID]; itemValue != nil {
			item.TodayRequests = itemValue.Requests
			item.TodayActualCost = itemValue.UserCost
		}
		if account.Proxy != nil {
			item.SlotLabel = account.Proxy.Name
			item.SelectedNodeName = account.Proxy.SelectedNodeName
			item.SelectedNodeStatus = account.Proxy.SelectedNodeStatus
			item.SelectedNodeObservedAt = account.Proxy.SelectedNodeObservedAt
		}
		result.Accounts = append(result.Accounts, item)
		if item.Schedulable {
			result.Summary.SchedulableAccounts++
		}
	}
	weekTrend, _ := s.dashboard.GetUsageTrendWithFilters(ctx, timezone.StartOfWeek(now), now, "day", 0, 0, 0, 0, "", nil, nil, nil)
	for _, point := range weekTrend {
		result.Summary.WeekActualCost += point.ActualCost
	}
	start := now.Add(-24 * time.Hour)
	trend, _ := s.dashboard.GetUserUsageTrend(ctx, start, now, "hour", 12)
	for _, point := range trend {
		result.UserUsage24h = append(result.UserUsage24h, LabDashboardUserUsage{Bucket: point.Date, DisplayName: labDashboardDisplayName("", point.Username, point.Email, point.UserID), Requests: point.Requests, ActualCost: point.ActualCost})
	}
	todayRanking, _ := s.dashboard.GetUserSpendingRanking(ctx, timezone.Today(), now, 10)
	historyRanking, _ := s.dashboard.GetUserSpendingRanking(ctx, time.Unix(0, 0), now, 100)
	historyByUser := map[int64]float64{}
	if historyRanking != nil {
		for _, row := range historyRanking.Ranking {
			historyByUser[row.UserID] = row.ActualCost
		}
	}
	result.Leaderboard.HistoryStartDate = "retained"
	result.Leaderboard.HistoryEndDate = now.Format("2006-01-02")
	if todayRanking != nil {
		result.Leaderboard.Rows = make([]LabDashboardLeaderboardRow, 0, len(todayRanking.Ranking))
		for _, row := range todayRanking.Ranking {
			result.Leaderboard.Rows = append(result.Leaderboard.Rows, LabDashboardLeaderboardRow{DisplayName: labDashboardDisplayName("", row.Username, row.Email, row.UserID), TodayActualCost: row.ActualCost, TotalActualCost: historyByUser[row.UserID]})
		}
	}
	params := pagination.PaginationParams{Page: 1, PageSize: 8, SortBy: "created_at", SortOrder: "desc"}
	logs, _, _ := s.usage.ListWithFilters(ctx, params, usagestats.UsageLogFilters{})
	chains, _ := s.usage.ListRequestChains(ctx, logs)
	switches := labDashboardSwitches(chains)
	for _, log := range logs {
		name := ""
		if log.Account != nil {
			name = log.Account.Name
		}
		display := "User " + formatInt64(log.UserID)
		if log.User != nil {
			display = labDashboardDisplayName("", log.User.Username, log.User.Email, log.User.ID)
		}
		recent := LabDashboardRecentUsage{CreatedAt: log.CreatedAt, UserDisplayName: display, Model: log.Model, AccountName: name, ActualCost: log.ActualCost}
		if from, ok := switches[log.ID]; ok {
			recent.SwitchFromAccountName = from
			recent.SwitchReason = "account_changed"
		}
		result.RecentUsage = append(result.RecentUsage, recent)
	}
	return result, nil
}

func configTimezone(cfg *config.Config) string {
	if cfg != nil && cfg.Timezone != "" {
		return cfg.Timezone
	}
	return "UTC"
}
func quotaPercent(extra map[string]any, key string) (float64, bool) {
	value, ok := resolveAccountExtraNumber(extra, key)
	if !ok || value < 0 {
		return 0, false
	}
	return value, true
}

func filterLabDashboardAccounts(accounts []Account, cfg *config.Config) []Account {
	if cfg == nil || len(cfg.LabDashboard.AccountGroupIDs) == 0 {
		return accounts
	}
	allowed := map[int64]struct{}{}
	for _, id := range cfg.LabDashboard.AccountGroupIDs {
		if id > 0 {
			allowed[id] = struct{}{}
		}
	}
	result := make([]Account, 0, len(accounts))
	for _, account := range accounts {
		keep := false
		for _, id := range account.GroupIDs {
			if _, ok := allowed[id]; ok {
				keep = true
				break
			}
		}
		if !keep {
			for _, membership := range account.AccountGroups {
				if _, ok := allowed[membership.GroupID]; ok {
					keep = true
					break
				}
			}
		}
		if keep {
			result = append(result, account)
		}
	}
	return result
}

func labDashboardSwitches(chains []UsageLog) map[int64]string {
	grouped := map[string][]UsageLog{}
	for _, log := range chains {
		if strings.TrimSpace(log.RequestID) != "" {
			key := formatInt64(log.UserID) + "\x00" + log.RequestID
			grouped[key] = append(grouped[key], log)
		}
	}
	result := map[int64]string{}
	for _, logs := range grouped {
		sort.SliceStable(logs, func(i, j int) bool {
			if logs[i].CreatedAt.Equal(logs[j].CreatedAt) {
				return logs[i].ID < logs[j].ID
			}
			return logs[i].CreatedAt.Before(logs[j].CreatedAt)
		})
		for i := 1; i < len(logs); i++ {
			if logs[i-1].AccountID != logs[i].AccountID && logs[i-1].Account != nil {
				result[logs[i].ID] = logs[i-1].Account.Name
			}
		}
	}
	return result
}
