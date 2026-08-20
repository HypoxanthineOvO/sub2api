package service

import "testing"

func TestAutonomousWorkersEnabled(t *testing.T) {
	t.Setenv("SUB2API_DISABLE_AUTONOMOUS_WORKERS", "")
	if !autonomousWorkersEnabled() {
		t.Fatal("autonomous workers should be enabled by default")
	}

	t.Setenv("SUB2API_DISABLE_AUTONOMOUS_WORKERS", "1")
	if autonomousWorkersEnabled() {
		t.Fatal("autonomous workers should be disabled for rehearsal")
	}
}
