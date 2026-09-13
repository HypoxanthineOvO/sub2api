package service

import (
	"testing"

	"github.com/stretchr/testify/require"
	"github.com/tidwall/gjson"
)

func TestProviderAdapterForNativeResponsesProviders(t *testing.T) {
	for _, tc := range []struct {
		provider string
		model    string
		path     string
	}{
		{provider: MonitorProviderDeepseek, model: "deepseek-v4", path: providerDeepseekResponsesPath},
		{provider: MonitorProviderMiniMax, model: "MiniMax-M3", path: providerOpenAIResponsesPath},
		{provider: MonitorProviderMiMo, model: "mimo-v2.5", path: providerOpenAIResponsesPath},
	} {
		t.Run(tc.provider, func(t *testing.T) {
			require.NoError(t, validateAPIMode(tc.provider, MonitorAPIModeResponses))
			adapter, mode, ok := providerAdapterFor(tc.provider, MonitorAPIModeResponses)
			require.True(t, ok)
			require.Equal(t, MonitorAPIModeResponses, mode)
			require.Equal(t, tc.path, adapter.buildPath(tc.model))

			body, err := adapter.buildBody(tc.model, "Q: 1 + 1 = ?\nA:")
			require.NoError(t, err)
			require.Equal(t, tc.model, gjson.GetBytes(body, "model").String())
			require.Equal(t, "Q: 1 + 1 = ?\nA:", gjson.GetBytes(body, "input").String())
			require.Equal(t, "Bearer provider-key", adapter.buildHeaders("provider-key")["Authorization"])
		})
	}
}
