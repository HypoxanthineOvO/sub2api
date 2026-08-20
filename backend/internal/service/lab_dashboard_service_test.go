package service

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestLabDashboardDisplayNameNeverFallsBackToEmail(t *testing.T) {
	require.Equal(t, "Alice", labDashboardDisplayName("Alice", "alice", "alice@example.com", 7))
	require.Equal(t, "alice", labDashboardDisplayName("", "alice", "alice@example.com", 7))
	require.Equal(t, "User 7", labDashboardDisplayName("", "", "alice@example.com", 7))
	require.Equal(t, "User 7", labDashboardDisplayName("alice@example.com", "alice@example.com", "alice@example.com", 7))
}

func TestLabDashboardProbabilityUnavailableWithoutConfiguredGroup(t *testing.T) {
	probability, status := labDashboardProbability(nil, nil)
	require.Nil(t, probability)
	require.Equal(t, "unavailable", status)
}

func TestLabDashboardSwitchesUsesFullRequestChain(t *testing.T) {
	oldAccount := &Account{Name: "Card A"}
	got := labDashboardSwitches([]UsageLog{
		{ID: 1, UserID: 9, RequestID: "req", AccountID: 10, Account: oldAccount, CreatedAt: time.Unix(1, 0)},
		{ID: 2, UserID: 9, RequestID: "req", AccountID: 11, Account: &Account{Name: "Card B"}, CreatedAt: time.Unix(2, 0)},
	})
	require.Equal(t, "Card A", got[2])
}

func TestLabDashboardAccountBillingNormalizesSubscriptionQuotaWindows(t *testing.T) {
	account := &Account{
		Platform:    PlatformZhipu,
		Type:        AccountTypeAPIKey,
		Credentials: map[string]any{"account_mode": AccountModeCoding, "api_key": "must-not-be-projected"},
		Extra: map[string]any{
			"zhipu_5h_used_percent":     13.0,
			"zhipu_5h_reset_at":         "2026-08-20T19:02:11Z",
			"zhipu_weekly_used_percent": 92.0,
			"zhipu_weekly_reset_at":     "2026-08-21T06:38:44Z",
		},
	}

	mode, windows, balances, low := labDashboardAccountBilling(account)

	require.Equal(t, AccountModeCoding, mode)
	require.Equal(t, []LabDashboardQuotaWindow{
		{Window: "5h", UsedPercent: 13, ResetAt: "2026-08-20T19:02:11Z"},
		{Window: "weekly", UsedPercent: 92, ResetAt: "2026-08-21T06:38:44Z"},
	}, windows)
	require.Nil(t, balances)
	require.False(t, low)
}

func TestLabDashboardAccountBillingProjectsPayGBalances(t *testing.T) {
	account := &Account{
		Platform:    PlatformDeepseek,
		Type:        AccountTypeAPIKey,
		Credentials: map[string]any{"account_mode": AccountModePayG, "api_key": "must-not-be-projected"},
		Extra: map[string]any{
			"deepseek_balance":          12.65,
			"deepseek_balance_currency": "CNY",
			"deepseek_balance_low":      true,
			"deepseek_balances": []any{
				map[string]any{"currency": "CNY", "balance": 12.65},
				map[string]any{"currency": "USD", "balance": 1.75},
			},
		},
	}

	mode, windows, balances, low := labDashboardAccountBilling(account)

	require.Equal(t, AccountModePayG, mode)
	require.Empty(t, windows)
	require.Equal(t, []LabDashboardBalance{
		{Currency: "CNY", Balance: 12.65},
		{Currency: "USD", Balance: 1.75},
	}, balances)
	require.True(t, low)
}
