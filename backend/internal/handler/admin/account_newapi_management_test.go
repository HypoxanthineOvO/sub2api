package admin

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestProbeNewAPIManagementValidatesAccountID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	handler := NewAccountHandler(nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil)
	router := gin.New()
	router.POST("/admin/accounts/:id/management-probe", handler.ProbeNewAPIManagement)

	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/admin/accounts/not-an-id/management-probe", nil))
	require.Equal(t, http.StatusBadRequest, recorder.Code)
}

func TestProbeNewAPIManagementReportsUnavailableService(t *testing.T) {
	gin.SetMode(gin.TestMode)
	handler := NewAccountHandler(nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil)
	router := gin.New()
	router.POST("/admin/accounts/:id/management-probe", handler.ProbeNewAPIManagement)

	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/admin/accounts/1/management-probe", nil))
	require.Equal(t, http.StatusServiceUnavailable, recorder.Code)
}
