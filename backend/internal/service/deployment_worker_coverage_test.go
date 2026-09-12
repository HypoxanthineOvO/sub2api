package service

import (
	"go/ast"
	"go/parser"
	"go/token"
	"testing"
)

// New autonomous providers must receive an explicit deployment-safety review.
func TestDeploymentAutonomousProviderCoverage(t *testing.T) {
	known := map[string]string{
		"ProvideBatchImageCleanupService":      "batch_image_cleanup.go",
		"ProvideTokenRefreshService":           "token_refresh_service.go",
		"ProvideCNProviderBalanceCheckService": "cn_provider_balance_check_service.go",
		"ProvideDashboardAggregationService":   "dashboard_aggregation_service.go",
		"ProvideUsageCleanupService":           "usage_cleanup_service.go",
		"ProvideAccountExpiryService":          "account_expiry_service.go",
		"ProvideOpenAICodexVersionSyncService": "openai_codex_version_sync_service.go",
		"ProvideProxyExpiryService":            "proxy_expiry_service.go",
		"ProvideSubscriptionExpiryService":     "subscription_expiry_service.go",
		"ProvideOpsMetricsCollector":           "ops_metrics_collector.go",
		"ProvideOpsAggregationService":         "ops_aggregation_service.go",
		"ProvideOpsAlertEvaluatorService":      "ops_alert_evaluator_service.go",
		"ProvideOpsCleanupService":             "ops_cleanup_service.go",
		"ProvideIdempotencyCleanupService":     "idempotency_cleanup_service.go",
		"ProvideScheduledTestRunnerService":    "scheduled_test_runner_service.go",
		"ProvideOpsScheduledReportService":     "ops_scheduled_report_service.go",
		"ProvideBackupService":                 "backup_service.go",
		"ProvidePaymentOrderExpiryService":     "payment_order_expiry_service.go",
		"ProvideChannelMonitorRunner":          "channel_monitor_runner.go",
		"ProvideChannelMonitorV2Aggregator":    "channel_monitor_v2_aggregator.go",
		// This flushes per-process request observations, not a global cron job.
		"ProvideOpsIngressRejectAggregator": "per-process",
	}
	f, err := parser.ParseFile(token.NewFileSet(), "wire.go", nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	for _, decl := range f.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok {
			continue
		}
		gated := false
		ast.Inspect(fn.Body, func(n ast.Node) bool {
			if call, ok := n.(*ast.CallExpr); ok {
				if name, ok := call.Fun.(*ast.Ident); ok && name.Name == "autonomousWorkersEnabled" {
					gated = true
				}
			}
			return true
		})
		if !gated {
			continue
		}
		file, exists := known[fn.Name.Name]
		if !exists {
			t.Errorf("unreviewed autonomous provider %s", fn.Name.Name)
			continue
		}
		if file == "per-process" {
			continue
		}
		source, err := parser.ParseFile(token.NewFileSet(), file, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		lease := false
		ast.Inspect(source, func(n ast.Node) bool {
			if call, ok := n.(*ast.CallExpr); ok {
				if name, ok := call.Fun.(*ast.Ident); ok && name.Name == "beginDeploymentJob" {
					lease = true
				}
			}
			return true
		})
		if !lease {
			t.Errorf("provider %s has no worker ownership guard", fn.Name.Name)
		}
	}
}
