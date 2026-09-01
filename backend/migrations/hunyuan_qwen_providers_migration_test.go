package migrations

import (
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestHunyuanQwenProvidersMigration(t *testing.T) {
	sqlBytes, err := os.ReadFile("232_add_hunyuan_qwen_providers.sql")
	require.NoError(t, err)
	sql := string(sqlBytes)

	for _, constraint := range []string{
		"user_platform_quotas_platform_check",
		"composite_model_routes_target_platform_check",
	} {
		require.Contains(t, sql, constraint)
	}
	for _, platform := range []string{"'hunyuan'", "'qwen'"} {
		require.GreaterOrEqual(t, strings.Count(sql, platform), 2)
	}
}
