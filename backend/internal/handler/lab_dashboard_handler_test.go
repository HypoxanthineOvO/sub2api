package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Wei-Shaw/sub2api/internal/service"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type labDashboardReaderStub struct{ response *service.LabDashboardResponse }

func (s labDashboardReaderStub) Get(context.Context) (*service.LabDashboardResponse, error) {
	return s.response, nil
}

func TestLabDashboardHandlerReturnsOnlyAllowlistedResponse(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := NewLabDashboardHandler(labDashboardReaderStub{response: &service.LabDashboardResponse{
		Summary:  service.LabDashboardSummary{TodayRequests: 3},
		Accounts: []service.LabDashboardAccount{{Name: "lab-card"}},
	}})
	router := gin.New()
	router.GET("/lab/dashboard", h.Get)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/lab/dashboard", nil))
	require.Equal(t, http.StatusOK, recorder.Code)
	var payload map[string]any
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &payload))
	for _, forbidden := range []string{"email", "credentials", "extra", "host", "port", "username", "password", "ip_address"} {
		require.NotContains(t, recorder.Body.String(), `"`+forbidden+`"`)
	}
}
