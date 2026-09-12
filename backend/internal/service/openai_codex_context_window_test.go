package service

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestCodexLongContextDefaults(t *testing.T) {
	t.Parallel()

	for _, modelID := range []string{
		"gpt-5.5", "gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
		"gpt-6", "gpt-6-astra", "openai/gpt-6-astra-2026-09-01",
	} {
		t.Run(modelID, func(t *testing.T) {
			descriptor := newConfiguredCodexModelDescriptor(modelID)
			require.EqualValues(t, 1_000_000, descriptor.ContextWindow)
			require.EqualValues(t, 1_050_000, descriptor.MaxContextWindow)
		})
	}
}

func TestAdjustCodexModelsManifestContextWindow(t *testing.T) {
	t.Parallel()

	for _, tc := range []struct {
		name    string
		fields  string
		wantMax int64
	}{
		{name: "missing", fields: ``, wantMax: 1_050_000},
		{name: "legacy", fields: `,"context_window":272000,"max_context_window":872000`, wantMax: 1_050_000},
		{name: "262k", fields: `,"context_window":262144,"max_context_window":1050000`, wantMax: 1_050_000},
		{name: "larger ceiling", fields: `,"context_window":1050000,"max_context_window":2000000`, wantMax: 2_000_000},
		{name: "already current", fields: `,"context_window":1000000,"max_context_window":1050000`, wantMax: 1_050_000},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := []byte(`{"models":[{"slug":"gpt-5.6-sol","effective_context_window_percent":95,"auto_compact_token_limit":null` + tc.fields + `}],"metadata":{"version":1}}`)
			adjusted, err := adjustCodexModelsManifestContextWindow(body)
			require.NoError(t, err)
			model := decodeCodexManifestModels(t, adjusted)[0]
			require.EqualValues(t, 1_000_000, model["context_window"])
			require.EqualValues(t, tc.wantMax, model["max_context_window"])
			require.EqualValues(t, 95, model["effective_context_window_percent"])
			require.Nil(t, model["auto_compact_token_limit"])
			var envelope map[string]json.RawMessage
			require.NoError(t, json.Unmarshal(adjusted, &envelope))
			require.JSONEq(t, `{"version":1}`, string(envelope["metadata"]))
			again, err := adjustCodexModelsManifestContextWindow(adjusted)
			require.NoError(t, err)
			require.Equal(t, adjusted, again)
		})
	}
}

func TestCodexContextWindowPreservesOtherModels(t *testing.T) {
	t.Parallel()

	for _, modelID := range []string{"custom-model", "claude-sonnet-4-5", "gpt-5.3-codex-spark", "gpt-5.6-codex", "gpt-6-other"} {
		t.Run(modelID, func(t *testing.T) {
			body := []byte(`{"models":[{"slug":"` + modelID + `","context_window":128000,"max_context_window":128000}]}`)
			adjusted, err := adjustCodexModelsManifestContextWindow(body)
			require.NoError(t, err)
			require.Equal(t, body, adjusted)
		})
	}
}

func TestCodexConfiguredContextWindowOverridesStaleGPTMetadata(t *testing.T) {
	t.Parallel()

	body, err := buildCodexModelsManifest(
		[]string{"gpt-5.6-sol"}, nil, nil, nil,
		map[string]codexModelMetadataOverride{
			"gpt-5.6-sol": {UpstreamModelMetadata: UpstreamModelMetadata{ContextWindow: 262_144}},
		},
	)
	require.NoError(t, err)
	model := decodeCodexManifestModels(t, body)[0]
	require.EqualValues(t, 1_000_000, model["context_window"])
	require.EqualValues(t, 1_050_000, model["max_context_window"])
}

func TestCodexAPIKeyCompletionKeepsLongContextDefault(t *testing.T) {
	t.Parallel()

	account := newCodexModelsAPIKeyTestAccount("https://upstream.example/v1")
	account.SetUpstreamModelMetadataSnapshot(UpstreamModelMetadataSnapshot{Models: map[string]UpstreamModelMetadata{
		"gpt-5.6-sol": {ID: "gpt-5.6-sol", ContextWindow: 262_144},
	}})
	for _, source := range []string{
		`{"object":"list","data":[{"id":"gpt-5.6-sol"}]}`,
		`{"models":[{"slug":"gpt-5.6-sol","context_window":272000,"max_context_window":1050000}]}`,
	} {
		converted := convertOpenAIModelListToCodexManifestForAccount([]byte(source), account)
		manifest := &CodexModelsManifest{
			Body: converted, upstreamSourceBody: []byte(source),
			convertedFromOpenAIModelList: string(converted) != source,
		}
		svc := &OpenAIGatewayService{}
		require.NoError(t, svc.CompleteAPIKeyCodexModelsManifestForClient(manifest, account))
		model := decodeCodexManifestModels(t, manifest.Body)[0]
		require.EqualValues(t, 1_000_000, model["context_window"])
		require.EqualValues(t, 1_050_000, model["max_context_window"])
		require.Equal(t, codexModelsManifestBodyETag(manifest.Body), manifest.ETag)
		previous := append([]byte(nil), manifest.Body...)
		require.NoError(t, svc.CompleteAPIKeyCodexModelsManifestForClient(manifest, account))
		require.Equal(t, previous, manifest.Body)
	}
}

func TestCodexConfiguredLongContextETag(t *testing.T) {
	t.Parallel()

	const groupID int64 = 9876
	account := Account{
		ID: 1, Platform: PlatformOpenAI, Type: AccountTypeAPIKey,
		Credentials: map[string]any{"model_mapping": map[string]any{"gpt-5.6-sol": "gpt-5.6-sol"}},
	}
	svc := &OpenAIGatewayService{accountRepo: codexModelsVisibilityAccountRepo{byGroup: map[int64][]Account{groupID: {account}}}}
	group := &Group{ID: groupID, Platform: PlatformOpenAI}
	manifest, configured, err := svc.BuildGroupConfiguredCodexModelsManifest(context.Background(), group, "")
	require.NoError(t, err)
	require.True(t, configured)
	require.EqualValues(t, 1_000_000, decodeCodexManifestModels(t, manifest.Body)[0]["context_window"])
	require.Equal(t, codexModelsManifestBodyETag(manifest.Body), manifest.ETag)
	cached, configured, err := svc.BuildGroupConfiguredCodexModelsManifest(context.Background(), group, manifest.ETag)
	require.NoError(t, err)
	require.True(t, configured)
	require.True(t, cached.NotModified)
}
