package handler

import (
	"context"

	"github.com/Wei-Shaw/sub2api/internal/pkg/response"
	"github.com/Wei-Shaw/sub2api/internal/service"
	"github.com/gin-gonic/gin"
)

type LabDashboardReader interface {
	Get(context.Context) (*service.LabDashboardResponse, error)
}

type LabDashboardHandler struct{ service LabDashboardReader }

func NewLabDashboardHandler(service LabDashboardReader) *LabDashboardHandler {
	return &LabDashboardHandler{service: service}
}

func ProvideLabDashboardHandler(service *service.LabDashboardService) *LabDashboardHandler {
	return NewLabDashboardHandler(service)
}

func (h *LabDashboardHandler) Get(c *gin.Context) {
	data, err := h.service.Get(c.Request.Context())
	if err != nil {
		response.ErrorFrom(c, err)
		return
	}
	response.Success(c, data)
}
