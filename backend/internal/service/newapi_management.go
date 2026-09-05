package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/pkg/tlsfingerprint"
)

const (
	NewAPIManagementEnabledCredentialKey = "newapi_management_enabled"
	NewAPIManagementBaseURLCredentialKey = "newapi_management_base_url"
	NewAPIManagementTokenCredentialKey   = "newapi_management_token"
	NewAPIManagementSnapshotExtraKey     = "newapi_management_snapshot"

	// NewAPI /api/status responses can arrive promptly but finish slowly behind
	// some relay/CDN stacks. This budget covers all three sequential read-only
	// requests without affecting inference request timeouts.
	newAPIManagementRequestTimeout = 30 * time.Second
	newAPIManagementMaxBodyBytes   = 64 * 1024
)

// NewAPIManagementSnapshot is a safe, persisted view of a NewAPI account's
// management-plane balance and token usage. On a failed refresh, previously
// fetched values remain present while Status/Error describe the latest attempt.
type NewAPIManagementSnapshot struct {
	Status              string     `json:"status"`
	Error               string     `json:"error,omitempty"`
	BalanceUSD          float64    `json:"balance_usd"`
	UsedUSD             float64    `json:"used_usd"`
	RequestCount        int64      `json:"request_count"`
	PromptTokens        int64      `json:"prompt_tokens"`
	CompletionTokens    int64      `json:"completion_tokens"`
	CacheTokens         int64      `json:"cache_tokens"`
	CacheCreationTokens int64      `json:"cache_creation_tokens"`
	TotalTokens         int64      `json:"total_tokens"`
	Quota               float64    `json:"quota,omitempty"`
	UsedQuota           float64    `json:"used_quota,omitempty"`
	QuotaPerUnit        float64    `json:"quota_per_unit,omitempty"`
	Currency            string     `json:"currency,omitempty"`
	HTTPStatus          int        `json:"http_status,omitempty"`
	FetchedAt           *time.Time `json:"fetched_at,omitempty"`
	LastAttemptAt       time.Time  `json:"last_attempt_at"`
}

type NewAPIManagementService struct {
	accountRepo        AccountRepository
	accountTestService *AccountTestService
	now                func() time.Time
}

func NewNewAPIManagementService(accountRepo AccountRepository, accountTestService *AccountTestService) *NewAPIManagementService {
	return &NewAPIManagementService{accountRepo: accountRepo, accountTestService: accountTestService, now: time.Now}
}

func (s *NewAPIManagementService) ProbeAccount(ctx context.Context, accountID int64) (*NewAPIManagementSnapshot, error) {
	if s == nil || s.accountRepo == nil {
		return nil, errors.New("NewAPI management service is unavailable")
	}
	account, err := s.accountRepo.GetByID(ctx, accountID)
	if err != nil {
		return nil, err
	}
	snapshot := decodeNewAPIManagementSnapshot(account.Extra)
	if snapshot == nil {
		snapshot = &NewAPIManagementSnapshot{}
	}
	snapshot.Status = "failed"
	snapshot.Error = ""
	snapshot.HTTPStatus = 0
	snapshot.LastAttemptAt = s.currentTime().UTC()

	if !accountCredentialBool(account, NewAPIManagementEnabledCredentialKey) {
		return s.persistFailure(ctx, account, snapshot, 0, "not_enabled")
	}
	token := strings.TrimSpace(account.GetCredential(NewAPIManagementTokenCredentialKey))
	baseURL := strings.TrimSpace(account.GetCredential(NewAPIManagementBaseURLCredentialKey))
	if token == "" || baseURL == "" {
		return s.persistFailure(ctx, account, snapshot, 0, "incomplete_configuration")
	}
	if s.accountTestService == nil || s.accountTestService.httpUpstream == nil {
		return s.persistFailure(ctx, account, snapshot, 0, "transport_unavailable")
	}

	normalizedBaseURL, err := normalizeNewAPIManagementBaseURL(s.accountTestService, baseURL)
	if err != nil {
		return s.persistFailure(ctx, account, snapshot, 0, "invalid_base_url")
	}
	proxyURL := ""
	if account.ProxyID != nil {
		if account.Proxy == nil || account.Proxy.ID != *account.ProxyID {
			return s.persistFailure(ctx, account, snapshot, 0, "proxy_unavailable")
		}
		proxyURL = account.Proxy.URL()
	}

	probeCtx, cancel := context.WithTimeout(ctx, newAPIManagementRequestTimeout)
	defer cancel()
	statusData, statusCode, probeErr := s.fetchJSON(probeCtx, account, proxyURL, normalizedBaseURL, "/api/status", "")
	if probeErr != nil {
		return s.persistFailure(ctx, account, snapshot, statusCode, mapNewAPIManagementError(statusCode, probeErr))
	}
	selfData, statusCode, probeErr := s.fetchJSON(probeCtx, account, proxyURL, normalizedBaseURL, "/api/user/self", token)
	if probeErr != nil {
		return s.persistFailure(ctx, account, snapshot, statusCode, mapNewAPIManagementError(statusCode, probeErr))
	}
	statData, statusCode, probeErr := s.fetchJSON(probeCtx, account, proxyURL, normalizedBaseURL, "/api/log/self/stat", token)
	if probeErr != nil {
		return s.persistFailure(ctx, account, snapshot, statusCode, mapNewAPIManagementError(statusCode, probeErr))
	}

	quotaPerUnit, ok := numberAt(statusData, "quota_per_unit")
	if !ok || quotaPerUnit <= 0 {
		return s.persistFailure(ctx, account, snapshot, statusCode, "invalid_response")
	}
	quota, quotaOK := numberAt(selfData, "quota")
	usedQuota, usedOK := numberAt(selfData, "used_quota")
	if !quotaOK || !usedOK {
		return s.persistFailure(ctx, account, snapshot, statusCode, "invalid_response")
	}
	requestCount, _ := int64At(selfData, "request_count")
	promptTokens, _ := findInt64(statData, "prompt_tokens")
	completionTokens, _ := findInt64(statData, "completion_tokens")
	cacheTokens, _ := findInt64(statData, "cache_tokens")
	cacheCreationTokens, _ := findInt64(statData, "cache_creation_tokens")
	totalTokens, totalOK := findInt64(statData, "total_tokens")
	if !totalOK {
		totalTokens = promptTokens + completionTokens + cacheTokens + cacheCreationTokens
	}

	now := s.currentTime().UTC()
	snapshot = &NewAPIManagementSnapshot{
		Status:              "ok",
		BalanceUSD:          quota / quotaPerUnit,
		UsedUSD:             usedQuota / quotaPerUnit,
		RequestCount:        requestCount,
		PromptTokens:        promptTokens,
		CompletionTokens:    completionTokens,
		CacheTokens:         cacheTokens,
		CacheCreationTokens: cacheCreationTokens,
		TotalTokens:         totalTokens,
		Quota:               quota,
		UsedQuota:           usedQuota,
		QuotaPerUnit:        quotaPerUnit,
		Currency:            managementCurrency(statusData),
		HTTPStatus:          statusCode,
		FetchedAt:           &now,
		LastAttemptAt:       now,
	}
	if err := s.accountRepo.UpdateExtra(ctx, account.ID, map[string]any{NewAPIManagementSnapshotExtraKey: snapshot}); err != nil {
		return nil, err
	}
	return snapshot, nil
}

func (s *NewAPIManagementService) fetchJSON(ctx context.Context, account *Account, proxyURL, baseURL, path, token string) (map[string]any, int, error) {
	requestURL := strings.TrimRight(baseURL, "/") + path
	req, err := http.NewRequestWithContext(WithHTTPUpstreamRedirectsDisabled(ctx), http.MethodGet, requestURL, nil)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Accept", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	var profile *tlsfingerprint.Profile
	if s.accountTestService.tlsFPProfileService != nil {
		profile = s.accountTestService.tlsFPProfileService.ResolveTLSProfile(account)
	}
	resp, err := s.accountTestService.httpUpstream.DoWithTLS(req, proxyURL, account.ID, account.Concurrency, profile)
	if err != nil {
		return nil, 0, err
	}
	if resp == nil || resp.Body == nil {
		return nil, 0, errors.New("empty response")
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(resp.Body, newAPIManagementMaxBodyBytes+1))
	if err != nil {
		return nil, resp.StatusCode, err
	}
	if len(body) > newAPIManagementMaxBodyBytes {
		return nil, resp.StatusCode, errors.New("response too large")
	}
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return nil, resp.StatusCode, fmt.Errorf("upstream returned HTTP %d", resp.StatusCode)
	}
	decoder := json.NewDecoder(strings.NewReader(string(body)))
	decoder.UseNumber()
	var envelope map[string]any
	if err := decoder.Decode(&envelope); err != nil {
		return nil, resp.StatusCode, err
	}
	if success, exists := envelope["success"].(bool); exists && !success {
		return nil, resp.StatusCode, errors.New("upstream reported failure")
	}
	data, ok := envelope["data"].(map[string]any)
	if !ok {
		return nil, resp.StatusCode, errors.New("response data is missing")
	}
	return data, resp.StatusCode, nil
}

func (s *NewAPIManagementService) persistFailure(ctx context.Context, account *Account, snapshot *NewAPIManagementSnapshot, httpStatus int, reason string) (*NewAPIManagementSnapshot, error) {
	snapshot.Status = "failed"
	snapshot.Error = reason
	snapshot.HTTPStatus = httpStatus
	if err := s.accountRepo.UpdateExtra(ctx, account.ID, map[string]any{NewAPIManagementSnapshotExtraKey: snapshot}); err != nil {
		return nil, err
	}
	return snapshot, nil
}

func (s *NewAPIManagementService) currentTime() time.Time {
	if s != nil && s.now != nil {
		return s.now()
	}
	return time.Now()
}

func normalizeNewAPIManagementBaseURL(testService *AccountTestService, raw string) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return "", errors.New("invalid management base URL")
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/")
	for {
		trimmed := false
		for _, suffix := range []string{"/keys", "/v1", "/anthropic"} {
			if strings.HasSuffix(parsed.Path, suffix) {
				parsed.Path = strings.TrimSuffix(parsed.Path, suffix)
				trimmed = true
				break
			}
		}
		if !trimmed {
			break
		}
	}
	parsed.RawPath = ""
	return testService.validateUpstreamBaseURL(parsed.String())
}

func accountCredentialBool(account *Account, key string) bool {
	if account == nil || account.Credentials == nil {
		return false
	}
	value, _ := account.Credentials[key].(bool)
	return value
}

func decodeNewAPIManagementSnapshot(extra map[string]any) *NewAPIManagementSnapshot {
	if extra == nil || extra[NewAPIManagementSnapshotExtraKey] == nil {
		return nil
	}
	raw, err := json.Marshal(extra[NewAPIManagementSnapshotExtraKey])
	if err != nil {
		return nil
	}
	var snapshot NewAPIManagementSnapshot
	if err := json.Unmarshal(raw, &snapshot); err != nil {
		return nil
	}
	return &snapshot
}

func numberAt(data map[string]any, key string) (float64, bool) {
	value, ok := data[key]
	if !ok {
		return 0, false
	}
	switch number := value.(type) {
	case json.Number:
		parsed, err := number.Float64()
		return parsed, err == nil
	case float64:
		return number, true
	case int64:
		return float64(number), true
	default:
		return 0, false
	}
}

func int64At(data map[string]any, key string) (int64, bool) {
	value, ok := numberAt(data, key)
	return int64(value), ok
}

func findInt64(data map[string]any, key string) (int64, bool) {
	if value, ok := int64At(data, key); ok {
		return value, true
	}
	for _, value := range data {
		if nested, ok := value.(map[string]any); ok {
			if found, ok := findInt64(nested, key); ok {
				return found, true
			}
		}
	}
	return 0, false
}

func managementCurrency(status map[string]any) string {
	if value, ok := status["quota_display_type"].(string); ok && strings.TrimSpace(value) != "" {
		return strings.ToUpper(strings.TrimSpace(value))
	}
	return "USD"
}

func mapNewAPIManagementError(status int, err error) string {
	switch status {
	case http.StatusUnauthorized:
		return "authentication_failed"
	case http.StatusForbidden:
		return "forbidden"
	case http.StatusNotFound, http.StatusMethodNotAllowed:
		return "unsupported_or_wrong_base_url"
	case http.StatusTooManyRequests:
		return "rate_limited"
	}
	if status >= 500 {
		return "upstream_unavailable"
	}
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		return "timeout"
	}
	if status >= 200 && status < 300 {
		return "invalid_response"
	}
	return "network_error"
}

func newAPIManagementIdentity(account *Account) [3]string {
	if account == nil {
		return [3]string{}
	}
	return [3]string{
		fmt.Sprint(account.Credentials[NewAPIManagementEnabledCredentialKey]),
		account.GetCredential(NewAPIManagementBaseURLCredentialKey),
		account.GetCredential(NewAPIManagementTokenCredentialKey),
	}
}
