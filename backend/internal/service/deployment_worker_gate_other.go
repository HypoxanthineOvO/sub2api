//go:build !linux

package service

import "os"

const DeploymentWorkerGateVersion = 0

func beginDeploymentJob() (func(), bool) {
	if os.Getenv("SUB2API_DEPLOYMENT_CONTROL_DIR") != "" || os.Getenv("SUB2API_DEPLOYMENT_INSTANCE") != "" {
		return nil, false // Managed deployment is supported only on Linux.
	}
	return func() {}, true
}
