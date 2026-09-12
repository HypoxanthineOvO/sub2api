//go:build linux

package service

import (
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sync"
	"syscall"
)

// DeploymentWorkerGateVersion is advertised by managed release manifests.
// A deployment controller changes workers.json only while holding workers.lock
// exclusively. Scheduled jobs hold a shared lock for their entire execution.
const DeploymentWorkerGateVersion = 1

var deploymentInstancePattern = regexp.MustCompile(`^(blue|green):[a-f0-9][a-f0-9-]{8,100}$`)

func beginDeploymentJob() (func(), bool) {
	dir := os.Getenv("SUB2API_DEPLOYMENT_CONTROL_DIR")
	instance := os.Getenv("SUB2API_DEPLOYMENT_INSTANCE")
	if dir == "" && instance == "" {
		return func() {}, true // Unmanaged installations retain their behavior.
	}
	if !filepath.IsAbs(dir) || !deploymentInstancePattern.MatchString(instance) {
		return nil, false
	}
	fd, err := syscall.Open(filepath.Join(dir, "workers.lock"), syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, false
	}
	lock := os.NewFile(uintptr(fd), "deployment-workers-lock")
	if err := syscall.Flock(fd, syscall.LOCK_SH|syscall.LOCK_NB); err != nil {
		_ = lock.Close()
		return nil, false
	}
	var once sync.Once
	release := func() { once.Do(func() { _ = lock.Close() }) }
	state, err := os.Open(filepath.Join(dir, "workers.json"))
	if err != nil {
		release()
		return nil, false
	}
	body, err := io.ReadAll(io.LimitReader(state, 4097))
	_ = state.Close()
	var owner struct {
		Owner string `json:"owner"`
	}
	if err != nil || len(body) > 4096 || json.Unmarshal(body, &owner) != nil || owner.Owner != instance {
		release()
		return nil, false
	}
	return release, true
}
