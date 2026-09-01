package migrations

import (
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestMinimaxMiMoProvidersMigration(t *testing.T) {
	sqlBytes, err := os.ReadFile("231_add_minimax_mimo_providers.sql")
	require.NoError(t, err)
	sql := string(sqlBytes)

	for _, constraint := range []string{
		"user_platform_quotas_platform_check",
		"channel_monitors_provider_check",
		"channel_monitor_request_templates_provider_check",
		"composite_model_routes_target_platform_check",
	} {
		require.Contains(t, sql, constraint)
	}
	for _, platform := range []string{"'minimax'", "'mimo'"} {
		require.GreaterOrEqual(t, strings.Count(sql, platform), 4)
	}
}
