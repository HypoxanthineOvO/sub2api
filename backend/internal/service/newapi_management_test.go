package service

import (
	"context"
	"io"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/config"
	"github.com/Wei-Shaw/sub2api/internal/pkg/tlsfingerprint"
	"github.com/stretchr/testify/require"
)

type newAPIManagementHTTPStub struct {
	mu       sync.Mutex
	requests []*http.Request
	status   map[string]int
	bodies   map[string]string
	err      error
}

func (u *newAPIManagementHTTPStub) Do(req *http.Request, _ string, _ int64, _ int) (*http.Response, error) {
	return u.DoWithTLS(req, "", 0, 0, nil)
}

func (u *newAPIManagementHTTPStub) DoWithTLS(req *http.Request, _ string, _ int64, _ int, _ *tlsfingerprint.Profile) (*http.Response, error) {
	u.mu.Lock()
	defer u.mu.Unlock()
	u.requests = append(u.requests, req)
	if u.err != nil {
		return nil, u.err
	}
	code := u.status[req.URL.Path]
	if code == 0 {
		code = http.StatusOK
	}
	return &http.Response{
		StatusCode: code,
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader(u.bodies[req.URL.Path])),
	}, nil
}

func newAPIManagementTestService(account *Account, upstream HTTPUpstream) (*NewAPIManagementService, *upstreamBillingProbeAccountRepo) {
	repo := &upstreamBillingProbeAccountRepo{accounts: map[int64]*Account{account.ID: account}}
	cfg := &config.Config{Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{
		Enabled:           false,
		AllowInsecureHTTP: true,
	}}}
	testService := &AccountTestService{accountRepo: repo, httpUpstream: upstream, cfg: cfg}
	return NewNewAPIManagementService(repo, testService), repo
}

func newAPIManagementAccount() *Account {
	return &Account{
		ID:          42,
		Concurrency: 3,
		Credentials: map[string]any{
			NewAPIManagementEnabledCredentialKey: true,
			NewAPIManagementBaseURLCredentialKey: "http://newapi.example/anthropic/v1",
			NewAPIManagementTokenCredentialKey:   "management-token",
		},
		Extra: map[string]any{},
	}
}

func TestNewAPIManagementProbeNormalizesAndPersistsSnapshot(t *testing.T) {
	upstream := &newAPIManagementHTTPStub{bodies: map[string]string{
		"/api/status":        `{"success":true,"data":{"quota_per_unit":500000,"quota_display_type":"USD"}}`,
		"/api/user/self":     `{"success":true,"data":{"quota":1001472,"used_quota":998998528,"request_count":321}}`,
		"/api/log/self/stat": `{"success":true,"data":{"prompt_tokens":11,"completion_tokens":13,"cache_tokens":17,"cache_creation_tokens":19}}`,
	}}
	service, repo := newAPIManagementTestService(newAPIManagementAccount(), upstream)
	now := time.Date(2026, 9, 2, 7, 0, 0, 0, time.UTC)
	service.now = func() time.Time { return now }

	snapshot, err := service.ProbeAccount(context.Background(), 42)
	require.NoError(t, err)
	require.Equal(t, "ok", snapshot.Status)
	require.InDelta(t, 2.002944, snapshot.BalanceUSD, 0.0000001)
	require.InDelta(t, 1997.997056, snapshot.UsedUSD, 0.0000001)
	require.Equal(t, int64(321), snapshot.RequestCount)
	require.Equal(t, int64(11), snapshot.PromptTokens)
	require.Equal(t, int64(13), snapshot.CompletionTokens)
	require.Equal(t, int64(17), snapshot.CacheTokens)
	require.Equal(t, int64(19), snapshot.CacheCreationTokens)
	require.Equal(t, int64(60), snapshot.TotalTokens)
	require.NotNil(t, snapshot.FetchedAt)
	require.Equal(t, now, *snapshot.FetchedAt)

	require.Len(t, upstream.requests, 3)
	require.Equal(t, "/api/status", upstream.requests[0].URL.Path)
	require.Empty(t, upstream.requests[0].Header.Get("Authorization"))
	for _, req := range upstream.requests[1:] {
		require.Equal(t, "Bearer management-token", req.Header.Get("Authorization"))
		require.True(t, HTTPUpstreamRedirectsDisabled(req.Context()))
		require.NotContains(t, req.URL.Path, "anthropic")
	}
	persisted := decodeNewAPIManagementSnapshot(repo.accounts[42].Extra)
	require.NotNil(t, persisted)
	require.Equal(t, snapshot.TotalTokens, persisted.TotalTokens)
}

func TestNewAPIManagementProbeFailurePreservesLastSuccessfulValues(t *testing.T) {
	oldFetchedAt := time.Date(2026, 9, 1, 1, 0, 0, 0, time.UTC)
	account := newAPIManagementAccount()
	account.Extra[NewAPIManagementSnapshotExtraKey] = &NewAPIManagementSnapshot{
		Status: "ok", BalanceUSD: 12.5, UsedUSD: 7.5, TotalTokens: 99, FetchedAt: &oldFetchedAt,
	}
	upstream := &newAPIManagementHTTPStub{
		status: map[string]int{"/api/user/self": http.StatusUnauthorized},
		bodies: map[string]string{
			"/api/status":    `{"success":true,"data":{"quota_per_unit":500000}}`,
			"/api/user/self": `{"success":false,"message":"invalid token"}`,
		},
	}
	service, _ := newAPIManagementTestService(account, upstream)

	snapshot, err := service.ProbeAccount(context.Background(), 42)
	require.NoError(t, err)
	require.Equal(t, "failed", snapshot.Status)
	require.Equal(t, "authentication_failed", snapshot.Error)
	require.Equal(t, http.StatusUnauthorized, snapshot.HTTPStatus)
	require.Equal(t, 12.5, snapshot.BalanceUSD)
	require.Equal(t, int64(99), snapshot.TotalTokens)
	require.NotNil(t, snapshot.FetchedAt)
	require.Equal(t, oldFetchedAt, *snapshot.FetchedAt)
}

func TestNewAPIManagementProbeDisabledDoesNotCallUpstream(t *testing.T) {
	account := newAPIManagementAccount()
	account.Credentials[NewAPIManagementEnabledCredentialKey] = false
	upstream := &newAPIManagementHTTPStub{}
	service, _ := newAPIManagementTestService(account, upstream)

	snapshot, err := service.ProbeAccount(context.Background(), 42)
	require.NoError(t, err)
	require.Equal(t, "failed", snapshot.Status)
	require.Equal(t, "not_enabled", snapshot.Error)
	require.Empty(t, upstream.requests)
}

func TestNewAPIManagementProbeMapsTimeoutWithoutLeakingError(t *testing.T) {
	upstream := &newAPIManagementHTTPStub{err: context.DeadlineExceeded}
	service, _ := newAPIManagementTestService(newAPIManagementAccount(), upstream)

	snapshot, err := service.ProbeAccount(context.Background(), 42)
	require.NoError(t, err)
	require.Equal(t, "failed", snapshot.Status)
	require.Equal(t, "timeout", snapshot.Error)
}
