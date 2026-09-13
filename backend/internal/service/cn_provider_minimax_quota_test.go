package service

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/pkg/tlsfingerprint"
	"github.com/stretchr/testify/require"
)

type minimaxQuotaProbeRepo struct {
	AccountRepository
	account     *Account
	extraWrites []map[string]any
}

func (r *minimaxQuotaProbeRepo) GetByID(_ context.Context, _ int64) (*Account, error) {
	return r.account, nil
}

func (r *minimaxQuotaProbeRepo) UpdateExtra(_ context.Context, _ int64, updates map[string]any) error {
	r.extraWrites = append(r.extraWrites, updates)
	return nil
}

type minimaxQuotaUpstream struct {
	statusCode int
	body       string
	request    *http.Request
	proxyURL   string
}

func (u *minimaxQuotaUpstream) Do(req *http.Request, proxyURL string, _ int64, _ int) (*http.Response, error) {
	u.request = req.Clone(req.Context())
	u.proxyURL = proxyURL
	return &http.Response{
		StatusCode: u.statusCode,
		Body:       io.NopCloser(strings.NewReader(u.body)),
		Header:     make(http.Header),
	}, nil
}

func (u *minimaxQuotaUpstream) DoWithTLS(
	req *http.Request,
	proxyURL string,
	accountID int64,
	accountConcurrency int,
	_ *tlsfingerprint.Profile,
) (*http.Response, error) {
	return u.Do(req, proxyURL, accountID, accountConcurrency)
}

func newMinimaxQuotaAccount() *Account {
	return &Account{
		ID:       71,
		Platform: PlatformMiniMax,
		Type:     AccountTypeAPIKey,
		Status:   StatusActive,
		Credentials: map[string]any{
			"account_mode": AccountModeCoding,
			"api_key":      "sk-minimax-test",
			// Quota probe must ignore this inference endpoint and use the distinct
			// official subscription endpoint, while still going through URL validation.
			"base_url": "https://api.minimaxi.com/v1",
		},
	}
}

const minimaxQuotaSuccessFixture = `{
  "base_resp": {"status_code": 0, "status_msg": "success"},
  "model_remains": [
    {
      "model_name": "general",
      "start_time": 1788055200000,
      "end_time": 1788073200000,
      "remains_time": 10533775,
      "current_interval_total_count": 0,
      "current_interval_usage_count": 0,
      "current_interval_status": 1,
      "current_interval_remaining_percent": 100,
      "weekly_start_time": 1787500800000,
      "weekly_end_time": 1788105600000,
      "weekly_remains_time": 42933775,
      "current_weekly_total_count": 0,
      "current_weekly_usage_count": 0,
      "current_weekly_status": 1,
      "current_weekly_remaining_percent": 90
    },
    {
      "model_name": "video",
      "end_time": 1788105600000,
      "weekly_end_time": 1788105600000,
      "current_interval_remaining_percent": 5,
      "current_weekly_remaining_percent": 4
    }
  ]
}`

func TestParseMinimaxUsageTiers_UsesGeneralModelWindows(t *testing.T) {
	tiers, err := parseMiniMaxUsageTiers([]byte(minimaxQuotaSuccessFixture))
	require.NoError(t, err)
	require.Equal(t, []CNQuotaTier{
		{
			Window:      "5h",
			UsedPercent: 0,
			ResetAt:     time.UnixMilli(1788073200000).UTC().Format(time.RFC3339),
		},
		{
			Window:      "weekly",
			UsedPercent: 10,
			ResetAt:     time.UnixMilli(1788105600000).UTC().Format(time.RFC3339),
		},
	}, tiers)
}

func TestParseMinimaxUsageTiers_FailsClosedOnInvalidSchema(t *testing.T) {
	tests := []struct {
		name string
		body string
	}{
		{name: "invalid json", body: `{`},
		{name: "missing array", body: `{"base_resp":{"status_code":0}}`},
		{name: "missing general", body: `{"model_remains":[{"model_name":"video"}]}`},
		{name: "non numeric percentage", body: `{"model_remains":[{"model_name":"general","current_interval_remaining_percent":"oops","end_time":1788073200000,"current_weekly_remaining_percent":90,"weekly_end_time":1788105600000}]}`},
		{name: "percentage below zero", body: `{"model_remains":[{"model_name":"general","current_interval_remaining_percent":-1,"end_time":1788073200000,"current_weekly_remaining_percent":90,"weekly_end_time":1788105600000}]}`},
		{name: "percentage above one hundred", body: `{"model_remains":[{"model_name":"general","current_interval_remaining_percent":100,"end_time":1788073200000,"current_weekly_remaining_percent":101,"weekly_end_time":1788105600000}]}`},
		{name: "invalid five hour end", body: `{"model_remains":[{"model_name":"general","current_interval_remaining_percent":100,"end_time":0,"current_weekly_remaining_percent":90,"weekly_end_time":1788105600000}]}`},
		{name: "invalid weekly end", body: `{"model_remains":[{"model_name":"general","current_interval_remaining_percent":100,"end_time":1788073200000,"current_weekly_remaining_percent":90,"weekly_end_time":"invalid"}]}`},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tiers, err := parseMiniMaxUsageTiers([]byte(tt.body))
			require.Error(t, err)
			require.Empty(t, tiers)
		})
	}
}

func TestCNProviderQuotaService_MiniMaxSuccess(t *testing.T) {
	repo := &minimaxQuotaProbeRepo{account: newMinimaxQuotaAccount()}
	upstream := &minimaxQuotaUpstream{statusCode: http.StatusOK, body: minimaxQuotaSuccessFixture}
	svc := NewCNProviderQuotaService(repo, nil, upstream, nil)

	result, err := svc.QueryUsage(context.Background(), repo.account.ID)

	require.NoError(t, err)
	require.True(t, result.Success)
	require.True(t, result.CredentialValid)
	require.True(t, result.Persisted)
	require.Equal(t, PlatformMiniMax, result.Provider)
	require.Equal(t, http.StatusOK, result.StatusCode)
	require.Len(t, result.Tiers, 2)
	require.NotNil(t, upstream.request)
	require.Equal(t, http.MethodGet, upstream.request.Method)
	require.Equal(t, minimaxQuotaURL(DefaultMiniMaxBaseURL), upstream.request.URL.String())
	require.Equal(t, "Bearer sk-minimax-test", upstream.request.Header.Get("Authorization"))
	require.Equal(t, "application/json", upstream.request.Header.Get("Accept"))
	require.Equal(t, "application/json", upstream.request.Header.Get("Content-Type"))
	require.Len(t, repo.extraWrites, 1)
	write := repo.extraWrites[0]
	require.Equal(t, float64(0), write["minimax_5h_used_percent"])
	require.Equal(t, time.UnixMilli(1788073200000).UTC().Format(time.RFC3339), write["minimax_5h_reset_at"])
	require.Equal(t, float64(10), write["minimax_weekly_used_percent"])
	require.Equal(t, time.UnixMilli(1788105600000).UTC().Format(time.RFC3339), write["minimax_weekly_reset_at"])
	require.NotEmpty(t, write["minimax_usage_updated_at"])
}

func TestCNProviderQuotaService_MiniMaxBusinessErrorsDoNotPersist(t *testing.T) {
	tests := []struct {
		name            string
		statusCode      int
		body            string
		credentialValid bool
	}{
		{name: "invalid key envelope", statusCode: http.StatusOK, body: `{"base_resp":{"status_code":1004,"status_msg":"invalid api key"}}`},
		{name: "http unauthorized", statusCode: http.StatusUnauthorized, body: `{}`},
		{name: "http forbidden", statusCode: http.StatusForbidden, body: `{}`},
		{name: "unknown success schema", statusCode: http.StatusOK, body: `{"base_resp":{"status_code":0,"status_msg":"success"}}`, credentialValid: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			repo := &minimaxQuotaProbeRepo{account: newMinimaxQuotaAccount()}
			upstream := &minimaxQuotaUpstream{statusCode: tt.statusCode, body: tt.body}
			svc := NewCNProviderQuotaService(repo, nil, upstream, nil)

			result, err := svc.QueryUsage(context.Background(), repo.account.ID)

			require.NoError(t, err)
			require.False(t, result.Success)
			require.Equal(t, tt.credentialValid, result.CredentialValid)
			require.NotEmpty(t, result.Error)
			require.False(t, result.Persisted)
			require.Empty(t, repo.extraWrites)
		})
	}
}

func TestCNProviderQuotaService_MiniMaxOfficialHostMustBeAllowlisted(t *testing.T) {
	repo := &minimaxQuotaProbeRepo{account: newMinimaxQuotaAccount()}
	upstream := &minimaxQuotaUpstream{statusCode: http.StatusOK, body: minimaxQuotaSuccessFixture}
	svc := NewCNProviderQuotaService(repo, nil, upstream, cnProbeAllowlistConfig("inference.example.com"))

	_, err := svc.QueryUsage(context.Background(), repo.account.ID)

	require.Error(t, err)
	require.Contains(t, err.Error(), "CN_QUOTA_URL_REJECTED")
	require.Nil(t, upstream.request)
}
