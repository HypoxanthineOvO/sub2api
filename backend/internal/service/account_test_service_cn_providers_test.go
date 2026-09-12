//go:build unit

package service

import (
	"io"
	"net/http"
	"testing"

	"github.com/Wei-Shaw/sub2api/internal/config"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
	"github.com/tidwall/gjson"
)

// 复现 #GLM 代理测试 404：zhipu 账号此前落入 testClaudeAccountConnection，
// 把 OpenAI 兼容 base_url（paas/v4）拼上 /v1/messages，上游返回
// 404 {"path":"/v4/v1/messages"}。修复后必须按 api_protocol 分流。

func TestAccountTestService_ZhipuChatCompletionsHitsChatCompletionsEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)
	ctx, recorder := newTestContext()

	resp := newJSONResponse(http.StatusOK, "data: {\"choices\":[{\"delta\":{\"content\":\"hi\"},\"finish_reason\":null}]}\n\ndata: [DONE]\n\n")

	upstream := &queuedHTTPUpstream{responses: []*http.Response{resp}}
	svc := &AccountTestService{httpUpstream: upstream, cfg: &config.Config{Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}}}}
	account := &Account{
		ID:          201,
		Platform:    PlatformZhipu,
		Type:        AccountTypeAPIKey,
		Concurrency: 1,
		Credentials: map[string]any{
			"api_key":  "sk-test",
			"base_url": "https://open.bigmodel.cn/api/paas/v4",
		},
	}

	const prompt = "custom knowledge cutoff question"
	err := svc.testCNProviderAccountConnection(ctx, account, "glm-5.2", prompt)
	require.NoError(t, err)
	require.Len(t, upstream.requests, 1)

	req := upstream.requests[0]
	require.Equal(t, "https://open.bigmodel.cn/api/paas/v4/chat/completions", req.URL.String())
	require.Equal(t, "Bearer sk-test", req.Header.Get("Authorization"))

	body, err := io.ReadAll(req.Body)
	require.NoError(t, err)
	require.Equal(t, "glm-5.2", gjson.GetBytes(body, "model").String())
	require.Equal(t, prompt, gjson.GetBytes(body, "messages.0.content").String())
	require.Contains(t, recorder.Body.String(), "test_complete")
}

func TestAccountTestService_ZhipuAnthropicProtocolHitsNativeAnthropicEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)
	ctx, recorder := newTestContext()

	resp := newJSONResponse(http.StatusOK, "data: {\"type\":\"content_block_delta\",\"delta\":{\"text\":\"hi\"}}\n\ndata: {\"type\":\"message_stop\"}\n\n")

	upstream := &queuedHTTPUpstream{responses: []*http.Response{resp}}
	svc := &AccountTestService{httpUpstream: upstream, cfg: &config.Config{Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}}}}
	account := &Account{
		ID:          202,
		Platform:    PlatformZhipu,
		Type:        AccountTypeAPIKey,
		Concurrency: 1,
		Credentials: map[string]any{
			"api_key":      "sk-test",
			"api_protocol": "anthropic",
			"base_url":     "https://open.bigmodel.cn/api/anthropic",
		},
	}

	const prompt = "custom knowledge cutoff question"
	err := svc.testCNProviderAccountConnection(ctx, account, "glm-5.2", prompt)
	require.NoError(t, err)
	require.Len(t, upstream.requests, 1)

	req := upstream.requests[0]
	// 朴素 /v1/messages，不带 ?beta=true（对齐 nativeAnthropicTargetURL）
	require.Equal(t, "https://open.bigmodel.cn/api/anthropic/v1/messages", req.URL.String())
	// 默认 x-api-key 鉴权（zhipu 原生 Anthropic 端点）
	require.Equal(t, "sk-test", req.Header.Get("x-api-key"))
	require.Empty(t, req.Header.Get("Authorization"))
	require.Equal(t, "2023-06-01", req.Header.Get("anthropic-version"))

	body, err := io.ReadAll(req.Body)
	require.NoError(t, err)
	require.Equal(t, "glm-5.2", gjson.GetBytes(body, "model").String())
	require.Equal(t, prompt, gjson.GetBytes(body, "messages.0.content.0.text").String())
	require.Contains(t, recorder.Body.String(), "test_complete")
}

func TestAccountTestService_ZhipuAnthropicDefaultBaseURLFallback(t *testing.T) {
	gin.SetMode(gin.TestMode)
	ctx, _ := newTestContext()

	resp := newJSONResponse(http.StatusOK, "data: {\"type\":\"message_stop\"}\n\n")

	upstream := &queuedHTTPUpstream{responses: []*http.Response{resp}}
	svc := &AccountTestService{httpUpstream: upstream, cfg: &config.Config{Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}}}}
	account := &Account{
		ID:          203,
		Platform:    PlatformZhipu,
		Type:        AccountTypeAPIKey,
		Concurrency: 1,
		Credentials: map[string]any{
			"api_key":      "sk-test",
			"api_protocol": "anthropic",
		},
	}

	err := svc.testCNProviderAccountConnection(ctx, account, "glm-5.2", "")
	require.NoError(t, err)
	require.Len(t, upstream.requests, 1)
	require.Equal(t, "https://open.bigmodel.cn/api/anthropic/v1/messages", upstream.requests[0].URL.String())
}

func TestAccountTestService_CNProviderAppliesWildcardModelMapping(t *testing.T) {
	gin.SetMode(gin.TestMode)
	ctx, _ := newTestContext()

	resp := newJSONResponse(http.StatusOK, "data: {\"choices\":[{\"delta\":{\"content\":\"hi\"},\"finish_reason\":null}]}\n\ndata: [DONE]\n\n")

	upstream := &queuedHTTPUpstream{responses: []*http.Response{resp}}
	svc := &AccountTestService{httpUpstream: upstream, cfg: &config.Config{Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}}}}
	account := &Account{
		ID:          204,
		Platform:    PlatformZhipu,
		Type:        AccountTypeAPIKey,
		Concurrency: 1,
		Credentials: map[string]any{
			"api_key":       "sk-test",
			"base_url":      "https://open.bigmodel.cn/api/paas/v4",
			"model_mapping": map[string]any{"*": "glm-5.2"},
		},
	}

	err := svc.testCNProviderAccountConnection(ctx, account, "claude-sonnet-4-5", "")
	require.NoError(t, err)
	require.Len(t, upstream.requests, 1)

	body, err := io.ReadAll(upstream.requests[0].Body)
	require.NoError(t, err)
	require.Equal(t, "glm-5.2", gjson.GetBytes(body, "model").String())
}

func TestAccountTestService_ZhipuAnthropicMisconfiguredBaseURLGivesHint(t *testing.T) {
	gin.SetMode(gin.TestMode)
	ctx, recorder := newTestContext()

	upstream := &queuedHTTPUpstream{}
	cfg := &config.Config{Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}}}
	svc := &AccountTestService{httpUpstream: upstream, cfg: cfg}
	account := &Account{
		ID:          206,
		Platform:    PlatformZhipu,
		Type:        AccountTypeAPIKey,
		Concurrency: 1,
		Credentials: map[string]any{
			"api_key":      "sk-test",
			"api_protocol": "anthropic",
			"base_url":     "https://open.bigmodel.cn/api/paas/v4",
		},
	}

	err := svc.testCNProviderAccountConnection(ctx, account, "glm-5.2", "")
	require.Error(t, err)
	// 不应发出任何上游请求：配置错误在本地拦截
	require.Empty(t, upstream.requests)
	require.Contains(t, recorder.Body.String(), "looks like an OpenAI-compatible endpoint")
	require.Contains(t, recorder.Body.String(), "https://open.bigmodel.cn/api/anthropic")
}

func TestCnAnthropicBaseURLMisconfigHint(t *testing.T) {
	t.Parallel()

	// OpenAI 兼容形状：命中提示
	for _, hit := range []string{
		"https://open.bigmodel.cn/api/paas/v4",
		"https://open.bigmodel.cn/api/coding/paas/v4",
		"https://api.example.com/v1",
		"https://api.example.com/chat/completions",
		"https://api.example.com/responses",
	} {
		require.NotEmpty(t, cnAnthropicBaseURLMisconfigHint(hit), hit)
	}
	// Anthropic 兼容形状：不命中
	for _, miss := range []string{
		"https://open.bigmodel.cn/api/anthropic",
		"https://api.deepseek.com/anthropic",
		"https://api.moonshot.cn/anthropic",
		"https://relay.example.com/claude",
		"https://api.example.com/",
	} {
		require.Empty(t, cnAnthropicBaseURLMisconfigHint(miss), miss)
	}
}

func TestAccountTestService_CNProviderAnthropic401MarksAccountError(t *testing.T) {
	gin.SetMode(gin.TestMode)
	ctx, _ := newTestContext()

	resp := newJSONResponse(http.StatusUnauthorized, `{"error":{"message":"invalid api key"}}`)

	repo := &openAIAccountTestRepo{}
	upstream := &queuedHTTPUpstream{responses: []*http.Response{resp}}
	svc := &AccountTestService{accountRepo: repo, httpUpstream: upstream, cfg: &config.Config{Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}}}}
	account := &Account{
		ID:          205,
		Platform:    PlatformZhipu,
		Type:        AccountTypeAPIKey,
		Concurrency: 1,
		Credentials: map[string]any{
			"api_key":      "sk-test",
			"api_protocol": "anthropic",
		},
	}

	err := svc.testCNProviderAccountConnection(ctx, account, "glm-5.2", "")
	require.Error(t, err)
	require.Equal(t, int64(205), repo.setErrorID)
	require.Contains(t, repo.setErrorMsg, "401")
}
