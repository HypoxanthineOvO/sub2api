package chatroles

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestNormalizePreservesConversationAndUnknownFields(t *testing.T) {
	body := []byte(`{"model":"alias","messages":[{"role":"system","content":"first"},{"role":"developer","content":[{"type":"text","text":"developer is just text","cache_control":{"type":"ephemeral"}}],"name":"rules"},{"role":"user","content":"ping"},{"role":"assistant","content":null,"tool_calls":[{"id":"call_1","type":"function","function":{"name":"echo","arguments":"{\"role\":\"developer\"}"}}]},{"role":"tool","tool_call_id":"call_1","content":"ok"},{"role":"developer","content":"last"}],"metadata":{"large":9007199254740993,"role":"developer"},"stream":true,"reasoning_effort":"high"}`)
	want := strings.Replace(string(body), `"role":"developer","content"`, `"role":"system","content"`, -1)
	for _, platform := range []string{"deepseek", "kimi", "zhipu"} {
		t.Run(platform, func(t *testing.T) {
			got, err := Normalize(platform, "apikey", "https://upstream.example.test/v1/chat/completions", body)
			require.NoError(t, err)
			require.JSONEq(t, want, string(got))
			require.Contains(t, string(got), "9007199254740993")
			require.Contains(t, string(body), `"role":"developer","content"`)
		})
	}
}

func TestNormalizeUsesSelectedOfficialHostForOpenAICompatibleAccounts(t *testing.T) {
	body := []byte(`{"messages":[{"role":"developer","content":"rules"}]}`)
	for _, host := range []string{"api.deepseek.com", "api.kimi.com", "api.moonshot.cn", "api.moonshot.ai", "open.bigmodel.cn", "api.z.ai"} {
		t.Run(host, func(t *testing.T) {
			got, err := Normalize("openai", "apikey", "https://"+host+"/coding/v1/chat/completions", body)
			require.NoError(t, err)
			require.JSONEq(t, `{"messages":[{"role":"system","content":"rules"}]}`, string(got))
		})
	}
}

func TestNormalizeLeavesOtherTargetsByteIdentical(t *testing.T) {
	body := []byte("{ \"messages\": [{\"role\":\"developer\",\"content\":\"rules\"}] }")
	for _, target := range []string{"https://api.openai.com/v1/chat/completions", "https://relay.example.test/v1/chat/completions", "https://api.deepseek.com.example.test/v1/chat/completions", "https://example.test/api.kimi.com/chat/completions"} {
		got, err := Normalize("openai", "apikey", target, body)
		require.NoError(t, err)
		require.Equal(t, body, got)
	}
	got, err := Normalize("kimi", "oauth", "https://api.kimi.com/coding/v1/chat/completions", body)
	require.NoError(t, err)
	require.Equal(t, body, got)
}

func TestNormalizeDoesNotRewriteAlreadyCompatibleRequests(t *testing.T) {
	body := []byte("{ \"messages\": [{\"role\":\"system\",\"content\":\"rules\"}] }")
	got, err := Normalize("deepseek", "apikey", "https://api.deepseek.com/v1/chat/completions", body)
	require.NoError(t, err)
	require.Equal(t, body, got)
}

func TestNormalizeRejectsMalformedMessagesWithoutEchoingContent(t *testing.T) {
	for _, body := range []string{`{"secret":`, `{"messages":"secret"}`, `{"messages":["secret"]}`, `{"messages":[{"role":12,"content":"secret"}]}`} {
		_, err := Normalize("deepseek", "apikey", "https://api.deepseek.com/v1/chat/completions", []byte(body))
		require.Error(t, err)
		require.NotContains(t, err.Error(), "secret")
	}
}
