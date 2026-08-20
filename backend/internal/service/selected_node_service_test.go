package service

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/config"
	"github.com/stretchr/testify/require"
)

func selectedNodeTestConfig(endpoint string) *config.Config {
	return &config.Config{SelectedNode: config.SelectedNodeConfig{
		Enabled: true, Endpoint: endpoint, Token: "test-token", TimeoutMS: 800,
		FreshTTLSeconds: 10, StaleTTLSeconds: 60, FailureBackoffSeconds: 5, MaxResponseBytes: 1024,
		ProxySlots: map[string]string{"22": "slot-a", "36": "slot-b"},
	}}
}

func TestSelectedNodeServiceDoesNotUseEnvironmentProxy(t *testing.T) {
	var proxyCalls atomic.Int32
	var leakedAuthorization atomic.Value
	proxyServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxyCalls.Add(1)
		leakedAuthorization.Store(r.Header.Get("Authorization"))
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"slots":{"slot-a":{"selected_node_name":"proxy-injected","observed_at":"2026-08-17T06:00:00Z","status":"fresh"}}}`))
	}))
	t.Cleanup(proxyServer.Close)
	t.Setenv("HTTP_PROXY", proxyServer.URL)
	t.Setenv("HTTPS_PROXY", proxyServer.URL)
	t.Setenv("NO_PROXY", "")

	cfg := selectedNodeTestConfig("http://127.0.0.1:1/v1/selected-nodes")
	svc := NewSelectedNodeService(cfg)
	transport, ok := svc.httpClient.Transport.(*http.Transport)
	require.True(t, ok)
	require.Nil(t, transport.Proxy)
	svc.now = func() time.Time { return time.Date(2026, 8, 17, 6, 0, 1, 0, time.UTC) }
	proxy := &Proxy{ID: 22}
	svc.EnrichProxies(context.Background(), []*Proxy{proxy})

	require.Zero(t, proxyCalls.Load(), "selected-node credentials must never traverse HTTP_PROXY")
	if leaked := leakedAuthorization.Load(); leaked != nil {
		require.Empty(t, leaked)
	}
	require.Equal(t, SelectedNodeStatusUnavailable, proxy.SelectedNodeStatus)
}

func TestSelectedNodeServiceRejectsRedirect(t *testing.T) {
	var targetCalls atomic.Int32
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		targetCalls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"slots":{}}`))
	}))
	t.Cleanup(target.Close)
	redirect := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Redirect(w, nil, target.URL, http.StatusFound)
	}))
	t.Cleanup(redirect.Close)

	svc := NewSelectedNodeService(selectedNodeTestConfig(redirect.URL))
	proxy := &Proxy{ID: 22}
	svc.EnrichProxies(context.Background(), []*Proxy{proxy})

	require.Zero(t, targetCalls.Load())
	require.Equal(t, SelectedNodeStatusUnavailable, proxy.SelectedNodeStatus)
}

func TestSelectedNodeServiceBacksOffAfterFetchFailure(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		http.Error(w, "unavailable", http.StatusServiceUnavailable)
	}))
	t.Cleanup(server.Close)
	svc := NewSelectedNodeService(selectedNodeTestConfig(server.URL))
	now := time.Date(2026, 8, 17, 6, 0, 0, 0, time.UTC)
	svc.now = func() time.Time { return now }
	proxy := &Proxy{ID: 22}

	svc.EnrichProxies(context.Background(), []*Proxy{proxy})
	svc.EnrichProxies(context.Background(), []*Proxy{proxy})
	require.Equal(t, int32(1), calls.Load(), "failure backoff must suppress repeated list-triggered fetches")
	require.Equal(t, SelectedNodeStatusUnavailable, proxy.SelectedNodeStatus)
	now = now.Add(6 * time.Second)
	svc.EnrichProxies(context.Background(), []*Proxy{proxy})
	require.Equal(t, int32(2), calls.Load())
}

func TestSelectedNodeServiceFreshCacheAndStaleFallback(t *testing.T) {
	observed := "2026-08-17T06:00:00Z"
	var calls atomic.Int32
	fail := atomic.Bool{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		require.Equal(t, "Bearer test-token", r.Header.Get("Authorization"))
		if fail.Load() {
			http.Error(w, "secret upstream body", http.StatusBadGateway)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"slots":{"slot-a":{"selected_node_name":"香港-HKT-01","observed_at":%q,"status":"fresh"}}}`, observed)
	}))
	t.Cleanup(server.Close)

	now := time.Date(2026, 8, 17, 6, 0, 1, 0, time.UTC)
	svc := NewSelectedNodeService(selectedNodeTestConfig(server.URL))
	svc.now = func() time.Time { return now }
	proxies := []*Proxy{{ID: 22}, {ID: 36}, {ID: 99}}

	svc.EnrichProxies(context.Background(), proxies)
	require.Equal(t, int32(1), calls.Load())
	require.Equal(t, "香港-HKT-01", proxies[0].SelectedNodeName)
	require.Equal(t, SelectedNodeStatusFresh, proxies[0].SelectedNodeStatus)
	require.Equal(t, observed, proxies[0].SelectedNodeObservedAt)
	require.Equal(t, SelectedNodeStatusUnavailable, proxies[1].SelectedNodeStatus)
	require.Equal(t, SelectedNodeStatusNotConfigured, proxies[2].SelectedNodeStatus)

	svc.EnrichProxies(context.Background(), proxies)
	require.Equal(t, int32(1), calls.Load(), "fresh cache must avoid a second aggregator request")

	fail.Store(true)
	now = now.Add(11 * time.Second)
	svc.EnrichProxies(context.Background(), proxies)
	require.Equal(t, int32(2), calls.Load())
	require.Equal(t, "香港-HKT-01", proxies[0].SelectedNodeName)
	require.Equal(t, SelectedNodeStatusStale, proxies[0].SelectedNodeStatus)

	now = now.Add(61 * time.Second)
	svc.EnrichProxies(context.Background(), proxies)
	require.Equal(t, SelectedNodeStatusUnavailable, proxies[0].SelectedNodeStatus)
	require.Empty(t, proxies[0].SelectedNodeName)
}

func TestSelectedNodeServiceRejectsBadResponsesWithoutLeakingBody(t *testing.T) {
	tests := []struct {
		name        string
		contentType string
		status      int
		body        string
	}{
		{name: "oversize", contentType: "application/json", status: 200, body: strings.Repeat("x", 2048)},
		{name: "wrong content type", contentType: "text/plain", status: 200, body: `{"slots":{}}`},
		{name: "bad json", contentType: "application/json", status: 200, body: `{`},
		{name: "bad status", contentType: "application/json", status: 503, body: "secret error detail"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", tt.contentType)
				w.WriteHeader(tt.status)
				_, _ = w.Write([]byte(tt.body))
			}))
			t.Cleanup(server.Close)
			cfg := selectedNodeTestConfig(server.URL)
			cfg.SelectedNode.MaxResponseBytes = 128
			svc := NewSelectedNodeService(cfg)
			proxy := &Proxy{ID: 22}
			svc.EnrichProxies(context.Background(), []*Proxy{proxy})
			require.Equal(t, SelectedNodeStatusUnavailable, proxy.SelectedNodeStatus)
			require.Empty(t, proxy.SelectedNodeName)
		})
	}
}

func TestSelectedNodeServiceDisabledIsNotConfigured(t *testing.T) {
	svc := NewSelectedNodeService(&config.Config{})
	proxy := &Proxy{ID: 22}
	svc.EnrichProxies(context.Background(), []*Proxy{proxy})
	require.Equal(t, SelectedNodeStatusNotConfigured, proxy.SelectedNodeStatus)
}

func TestSelectedNodeServiceCoalescesConcurrentRefresh(t *testing.T) {
	var calls atomic.Int32
	now := time.Date(2026, 8, 17, 6, 0, 1, 0, time.UTC)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		time.Sleep(25 * time.Millisecond)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"slots":{"slot-a":{"selected_node_name":"香港-HKT-01","observed_at":"2026-08-17T06:00:00Z","status":"fresh"}}}`))
	}))
	t.Cleanup(server.Close)
	svc := NewSelectedNodeService(selectedNodeTestConfig(server.URL))
	svc.now = func() time.Time { return now }

	var wg sync.WaitGroup
	for range 20 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			proxy := &Proxy{ID: 22}
			svc.EnrichProxies(context.Background(), []*Proxy{proxy})
			require.Equal(t, SelectedNodeStatusFresh, proxy.SelectedNodeStatus)
		}()
	}
	wg.Wait()
	require.Equal(t, int32(1), calls.Load())
}

func TestSelectedNodeAggregatorContractFixtureIsPartialAndUTF8Safe(t *testing.T) {
	now := time.Date(2026, 8, 17, 6, 0, 20, 0, time.UTC)
	fixture := `{
  "slots": {
    "Slot A": {"selected_node_name":"香港-HKT-01","observed_at":"2026-08-17T06:00:18Z","status":"fresh"},
    "slot-b": {"selected_node_name":"新加坡-SG-02","observed_at":"2026-08-17T06:00:05Z","status":"stale"},
    "slot-invalid": {"selected_node_name":"bad\u0000node","observed_at":"2026-08-17T06:00:19Z","status":"fresh"},
    "slot-unavailable": {"selected_node_name":"","observed_at":"","status":"unavailable"}
  }
}`
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(fixture))
	}))
	t.Cleanup(server.Close)
	cfg := selectedNodeTestConfig(server.URL)
	cfg.SelectedNode.ProxySlots = map[string]string{
		"22": "Slot A", "36": "slot-b", "37": "slot-invalid", "38": "slot-unavailable",
	}
	svc := NewSelectedNodeService(cfg)
	svc.now = func() time.Time { return now }
	proxies := []*Proxy{{ID: 22}, {ID: 36}, {ID: 37}, {ID: 38}}

	svc.EnrichProxies(context.Background(), proxies)
	require.Equal(t, "香港-HKT-01", proxies[0].SelectedNodeName)
	require.Equal(t, SelectedNodeStatusFresh, proxies[0].SelectedNodeStatus)
	require.Equal(t, "新加坡-SG-02", proxies[1].SelectedNodeName)
	require.Equal(t, SelectedNodeStatusStale, proxies[1].SelectedNodeStatus, "age, not remote status alone, controls freshness")
	require.Equal(t, SelectedNodeStatusUnavailable, proxies[2].SelectedNodeStatus)
	require.Equal(t, SelectedNodeStatusUnavailable, proxies[3].SelectedNodeStatus)
}

func TestSelectedNodeServiceObservedAtControlsAgeAndFetchDoesNotRenewIt(t *testing.T) {
	observed := time.Date(2026, 8, 17, 6, 0, 0, 0, time.UTC)
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"slots":{"slot-a":{"selected_node_name":"香港-HKT-01","observed_at":%q,"status":"fresh"}}}`, observed.Format(time.RFC3339))
	}))
	t.Cleanup(server.Close)
	svc := NewSelectedNodeService(selectedNodeTestConfig(server.URL))
	now := observed.Add(2 * time.Second)
	svc.now = func() time.Time { return now }
	proxy := &Proxy{ID: 22}

	svc.EnrichProxies(context.Background(), []*Proxy{proxy})
	require.Equal(t, SelectedNodeStatusFresh, proxy.SelectedNodeStatus)
	now = observed.Add(13 * time.Second)
	svc.EnrichProxies(context.Background(), []*Proxy{proxy})
	require.Equal(t, SelectedNodeStatusStale, proxy.SelectedNodeStatus)
	require.Equal(t, int32(2), calls.Load(), "refresh may fetch again but must not reset observation age")
}

func TestSelectedNodeServiceRejectsObservationBeyondClockSkewPerSlot(t *testing.T) {
	now := time.Date(2026, 8, 17, 6, 0, 0, 0, time.UTC)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"slots":{`+
			`"slot-a":{"selected_node_name":"future","observed_at":%q,"status":"fresh"},`+
			`"slot-b":{"selected_node_name":"healthy","observed_at":%q,"status":"fresh"}}}`,
			now.Add(6*time.Second).Format(time.RFC3339), now.Add(5*time.Second).Format(time.RFC3339))
	}))
	t.Cleanup(server.Close)
	svc := NewSelectedNodeService(selectedNodeTestConfig(server.URL))
	svc.now = func() time.Time { return now }
	proxies := []*Proxy{{ID: 22}, {ID: 36}}

	svc.EnrichProxies(context.Background(), proxies)
	require.Equal(t, SelectedNodeStatusUnavailable, proxies[0].SelectedNodeStatus)
	require.Equal(t, "healthy", proxies[1].SelectedNodeName)
	require.Equal(t, SelectedNodeStatusFresh, proxies[1].SelectedNodeStatus)
}

func TestSelectedNodeServiceNeverUpgradesRemoteStaleToFresh(t *testing.T) {
	now := time.Date(2026, 8, 17, 6, 0, 10, 0, time.UTC)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"slots":{"slot-a":{"selected_node_name":"香港-HKT-01","observed_at":"2026-08-17T06:00:04Z","status":"stale"}}}`))
	}))
	t.Cleanup(server.Close)
	svc := NewSelectedNodeService(selectedNodeTestConfig(server.URL))
	svc.now = func() time.Time { return now }
	proxy := &Proxy{ID: 22}

	svc.EnrichProxies(context.Background(), []*Proxy{proxy})
	require.Equal(t, "香港-HKT-01", proxy.SelectedNodeName)
	require.Equal(t, SelectedNodeStatusStale, proxy.SelectedNodeStatus, "remote stale must not be upgraded inside the consumer fresh TTL")
}
