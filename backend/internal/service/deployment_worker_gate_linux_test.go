//go:build linux

package service

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestDeploymentWorkerGateLegacy(t *testing.T) {
	t.Setenv("SUB2API_DEPLOYMENT_CONTROL_DIR", "")
	t.Setenv("SUB2API_DEPLOYMENT_INSTANCE", "")
	release, ok := beginDeploymentJob()
	require.True(t, ok)
	release()
}

func TestDeploymentWorkerGateOwnershipAndBarrier(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SUB2API_DEPLOYMENT_CONTROL_DIR", dir)
	t.Setenv("SUB2API_DEPLOYMENT_INSTANCE", "blue:123456789-abcdef012")
	require.NoError(t, os.WriteFile(filepath.Join(dir, "workers.lock"), nil, 0600))
	require.NoError(t, os.WriteFile(filepath.Join(dir, "workers.json"), []byte(`{"owner":"blue:123456789-abcdef012"}`), 0600))
	release, ok := beginDeploymentJob()
	require.True(t, ok)
	control, err := os.OpenFile(filepath.Join(dir, "workers.lock"), os.O_RDWR, 0600)
	require.NoError(t, err)
	defer control.Close()
	err = syscall.Flock(int(control.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	require.Error(t, err, "ownership cannot change while a scheduled job is running")
	release()
	release() // Idempotent cleanup cannot close an unrelated reused descriptor.
	require.NoError(t, syscall.Flock(int(control.Fd()), syscall.LOCK_EX|syscall.LOCK_NB))
	_, ok = beginDeploymentJob()
	require.False(t, ok, "no job starts during handover")
	require.NoError(t, os.WriteFile(filepath.Join(dir, "workers.json"), []byte(`{"owner":"green:987654321-fedcba987"}`), 0600))
	require.NoError(t, syscall.Flock(int(control.Fd()), syscall.LOCK_UN))
	_, ok = beginDeploymentJob()
	require.False(t, ok, "standby does not execute scheduled jobs")
	t.Setenv("SUB2API_DEPLOYMENT_INSTANCE", "green:987654321-fedcba987")
	release, ok = beginDeploymentJob()
	require.True(t, ok)
	release()
}

func TestDeploymentWorkerGateFailsClosed(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SUB2API_DEPLOYMENT_CONTROL_DIR", dir)
	t.Setenv("SUB2API_DEPLOYMENT_INSTANCE", "blue:123456789-abcdef012")
	_, ok := beginDeploymentJob()
	require.False(t, ok)
	require.NoError(t, os.WriteFile(filepath.Join(dir, "workers.lock"), nil, 0600))
	for _, body := range []string{"", `{broken}`, `{"owner":"other"}`, string(make([]byte, 4097))} {
		require.NoError(t, os.WriteFile(filepath.Join(dir, "workers.json"), []byte(body), 0600))
		_, ok := beginDeploymentJob()
		require.False(t, ok)
	}
}
