package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestDeploymentIdentity(t *testing.T) {
	for _, instance := range []string{"", "blue:123456789-abcdef012", "bad\r\nheader"} {
		t.Setenv("SUB2API_DEPLOYMENT_INSTANCE", instance)
		r := httptest.NewRecorder()
		withDeploymentIdentity(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(200) })).ServeHTTP(r, httptest.NewRequest("GET", "/health", nil))
		want := ""
		if instance == "blue:123456789-abcdef012" {
			want = instance
		}
		if r.Header().Get("X-VSP-Deployment") != want {
			t.Fatal("unexpected deployment identity")
		}
	}
}
