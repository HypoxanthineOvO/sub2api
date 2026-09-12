package main

import (
	"net/http"
	"os"
	"regexp"
)

func withDeploymentIdentity(next http.Handler) http.Handler {
	instance := os.Getenv("SUB2API_DEPLOYMENT_INSTANCE")
	if !regexp.MustCompile(`^(blue|green):[a-f0-9][a-f0-9-]{8,100}$`).MatchString(instance) {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-VSP-Deployment", instance)
		next.ServeHTTP(w, r)
	})
}
