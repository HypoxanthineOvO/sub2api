package config

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestLoadSelectedNodeFromEnv(t *testing.T) {
	resetViperWithJWTSecret(t)
	t.Setenv("SELECTED_NODE_ENABLED", "true")
	t.Setenv("SELECTED_NODE_ENDPOINT", "http://127.0.0.1:19090/v1/selected-nodes")
	t.Setenv("SELECTED_NODE_TOKEN", "selected-secret")
	t.Setenv("SELECTED_NODE_TIMEOUT_MS", "750")
	t.Setenv("SELECTED_NODE_FRESH_TTL_SECONDS", "9")
	t.Setenv("SELECTED_NODE_STALE_TTL_SECONDS", "55")
	t.Setenv("SELECTED_NODE_FAILURE_BACKOFF_SECONDS", "7")
	t.Setenv("SELECTED_NODE_MAX_RESPONSE_BYTES", "8192")
	t.Setenv("SELECTED_NODE_PROXY_SLOTS", `{"4":"Slot A","8":"Slot E"}`)

	cfg, err := Load()
	require.NoError(t, err)
	require.Equal(t, SelectedNodeConfig{
		Enabled: true, Endpoint: "http://127.0.0.1:19090/v1/selected-nodes", Token: "selected-secret",
		TimeoutMS: 750, FreshTTLSeconds: 9, StaleTTLSeconds: 55, FailureBackoffSeconds: 7,
		MaxResponseBytes: 8192, ProxySlots: map[string]string{"4": "Slot A", "8": "Slot E"},
	}, cfg.SelectedNode)
}

func TestSelectedNodeEndpointIsLiteralLoopbackOnly(t *testing.T) {
	invalid := []string{
		"http://host.docker.internal:19090/v1/selected-nodes",
		"http://172.17.0.1:19090/v1/selected-nodes",
		"http://example.com:19090/v1/selected-nodes",
		"https://127.0.0.1:19090/v1/selected-nodes",
		"http://127.0.0.1:19090/other",
		"http://127.0.0.1:19090/v1/selected-nodes?redirect=x",
	}
	for _, endpoint := range invalid {
		t.Run(endpoint, func(t *testing.T) {
			cfg := &Config{SelectedNode: SelectedNodeConfig{
				Enabled: true, Endpoint: endpoint, Token: "secret", TimeoutMS: 800,
				FreshTTLSeconds: 10, StaleTTLSeconds: 60, FailureBackoffSeconds: 5, MaxResponseBytes: 65536,
			}}
			require.ErrorContains(t, cfg.validateSelectedNode(), "selected_node.endpoint")
		})
	}
}

func TestSelectedNodeRequiresBoundedConfiguration(t *testing.T) {
	cfg := &Config{SelectedNode: SelectedNodeConfig{
		Enabled: true, Endpoint: "http://[::1]:19090/v1/selected-nodes", Token: "secret",
		TimeoutMS: 800, FreshTTLSeconds: 10, StaleTTLSeconds: 60, FailureBackoffSeconds: 5, MaxResponseBytes: 65536,
	}}
	require.NoError(t, cfg.validateSelectedNode())

	cfg.SelectedNode.Token = ""
	require.ErrorContains(t, cfg.validateSelectedNode(), "selected_node.token")
	cfg.SelectedNode.Token = "secret"
	cfg.SelectedNode.TimeoutMS = 2001
	require.ErrorContains(t, cfg.validateSelectedNode(), "selected_node.timeout_ms")
}
