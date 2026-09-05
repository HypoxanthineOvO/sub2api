package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/Wei-Shaw/sub2api/internal/config"
	"golang.org/x/sync/singleflight"
)

const (
	maxSelectedNodeSlotBytes = 128
	maxSelectedNodeNameBytes = 256
	selectedNodeClockSkew    = 5 * time.Second
)

// SelectedNodeEnricher attaches host-side slot observations to runtime proxy objects.
type SelectedNodeEnricher interface {
	EnrichProxies(ctx context.Context, proxies []*Proxy)
}

type selectedNodeObservation struct {
	Name         string
	ObservedAt   time.Time
	SourceStatus string
}

type selectedNodeResponse struct {
	Slots map[string]json.RawMessage `json:"slots"`
}

type selectedNodeResponseItem struct {
	SelectedNodeName string `json:"selected_node_name"`
	ObservedAt       string `json:"observed_at"`
	Status           string `json:"status"`
}

type selectedNodeResolution struct {
	Observation selectedNodeObservation
	Status      string
}

// SelectedNodeService fetches one bulk host-side snapshot and maintains a bounded in-memory cache.
type SelectedNodeService struct {
	cfg        config.SelectedNodeConfig
	httpClient *http.Client
	now        func() time.Time

	mu          sync.Mutex
	lastGood    map[string]selectedNodeObservation
	lastFetchAt time.Time
	nextAttempt time.Time
	refresh     singleflight.Group
}

func NewSelectedNodeService(cfg *config.Config) *SelectedNodeService {
	selected := config.SelectedNodeConfig{}
	if cfg != nil {
		selected = cfg.SelectedNode
	}
	timeout := time.Duration(selected.TimeoutMS) * time.Millisecond
	if timeout <= 0 {
		timeout = 800 * time.Millisecond
	}
	baseTransport, ok := http.DefaultTransport.(*http.Transport)
	if !ok {
		baseTransport = &http.Transport{}
	}
	transport := baseTransport.Clone()
	transport.Proxy = nil
	transport.DialContext = selectedNodeDialContext
	return &SelectedNodeService{
		cfg: selected,
		httpClient: &http.Client{
			Timeout:   timeout,
			Transport: transport,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		now: time.Now,
	}
}

func (s *SelectedNodeService) EnrichProxies(ctx context.Context, proxies []*Proxy) {
	if s == nil || len(proxies) == 0 {
		return
	}
	requestedSlots := make(map[string]struct{})
	for _, proxy := range proxies {
		if proxy == nil {
			continue
		}
		proxy.SelectedNodeName = ""
		proxy.SelectedNodeObservedAt = ""
		proxy.SelectedNodeStatus = SelectedNodeStatusNotConfigured
		if slot := strings.TrimSpace(s.cfg.ProxySlots[strconv.FormatInt(proxy.ID, 10)]); s.cfg.Enabled && slot != "" {
			requestedSlots[slot] = struct{}{}
			proxy.SelectedNodeStatus = SelectedNodeStatusUnavailable
		}
	}
	if !s.cfg.Enabled || len(requestedSlots) == 0 {
		return
	}

	resolved := s.resolve(ctx, requestedSlots)
	for _, proxy := range proxies {
		if proxy == nil {
			continue
		}
		slot := strings.TrimSpace(s.cfg.ProxySlots[strconv.FormatInt(proxy.ID, 10)])
		if slot == "" {
			continue
		}
		resolution, ok := resolved[slot]
		if !ok {
			proxy.SelectedNodeStatus = SelectedNodeStatusUnavailable
			continue
		}
		proxy.SelectedNodeName = resolution.Observation.Name
		proxy.SelectedNodeObservedAt = resolution.Observation.ObservedAt.Format(time.RFC3339)
		proxy.SelectedNodeStatus = resolution.Status
	}
}

func (s *SelectedNodeService) resolve(ctx context.Context, requested map[string]struct{}) map[string]selectedNodeResolution {
	now := s.now()
	if cached, allFresh := s.cachedResolutions(requested, now); allFresh || s.shouldSuppressAttempt(now) {
		return cached
	}
	_, _, _ = s.refresh.Do("selected-nodes", func() (any, error) {
		now := s.now()
		if cached, allFresh := s.cachedResolutions(requested, now); allFresh || s.shouldSuppressAttempt(now) {
			return cached, nil
		}
		fetched, fetchErr := s.fetch(ctx)
		if fetchErr != nil {
			s.markFetchFailure(s.now())
			return nil, fetchErr
		}
		s.mergeObservations(fetched)
		s.markFetched(now)
		return fetched, nil
	})
	resolved, _ := s.cachedResolutions(requested, s.now())
	return resolved
}

func (s *SelectedNodeService) shouldSuppressAttempt(now time.Time) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	recentSuccess := !s.lastFetchAt.IsZero() && !now.Before(s.lastFetchAt) && now.Sub(s.lastFetchAt) <= time.Duration(s.cfg.FreshTTLSeconds)*time.Second
	return recentSuccess || now.Before(s.nextAttempt)
}

func (s *SelectedNodeService) markFetched(now time.Time) {
	s.mu.Lock()
	s.lastFetchAt = now
	s.nextAttempt = time.Time{}
	s.mu.Unlock()
}

func (s *SelectedNodeService) markFetchFailure(now time.Time) {
	backoff := time.Duration(s.cfg.FailureBackoffSeconds) * time.Second
	if backoff <= 0 {
		backoff = 5 * time.Second
	}
	s.mu.Lock()
	s.nextAttempt = now.Add(backoff)
	s.mu.Unlock()
}

func selectedNodeDialContext(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, errors.New("selected-node dial address is invalid")
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return nil, errors.New("selected-node dial host is not a literal loopback address")
	}
	return (&net.Dialer{}).DialContext(ctx, network, net.JoinHostPort(ip.String(), port))
}

func (s *SelectedNodeService) cachedResolutions(requested map[string]struct{}, now time.Time) (map[string]selectedNodeResolution, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	resolved := make(map[string]selectedNodeResolution, len(requested))
	allFresh := len(requested) > 0
	for slot := range requested {
		observation, ok := s.lastGood[slot]
		if !ok {
			allFresh = false
			continue
		}
		status := s.observationStatus(observation, now)
		if status == SelectedNodeStatusUnavailable {
			allFresh = false
			continue
		}
		if status != SelectedNodeStatusFresh {
			allFresh = false
		}
		resolved[slot] = selectedNodeResolution{Observation: observation, Status: status}
	}
	return resolved, allFresh
}

func (s *SelectedNodeService) mergeObservations(fetched map[string]selectedNodeObservation) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.lastGood == nil {
		s.lastGood = make(map[string]selectedNodeObservation, len(fetched))
	}
	for slot, observation := range fetched {
		previous, ok := s.lastGood[slot]
		if !ok || !observation.ObservedAt.Before(previous.ObservedAt) {
			s.lastGood[slot] = observation
		}
	}
}

func (s *SelectedNodeService) observationStatus(observation selectedNodeObservation, now time.Time) string {
	if observation.ObservedAt.After(now.Add(selectedNodeClockSkew)) {
		return SelectedNodeStatusUnavailable
	}
	age := now.Sub(observation.ObservedAt)
	if age < 0 {
		age = 0
	}
	if age <= time.Duration(s.cfg.FreshTTLSeconds)*time.Second {
		if observation.SourceStatus == SelectedNodeStatusStale {
			return SelectedNodeStatusStale
		}
		return SelectedNodeStatusFresh
	}
	if age <= time.Duration(s.cfg.StaleTTLSeconds)*time.Second {
		return SelectedNodeStatusStale
	}
	return SelectedNodeStatusUnavailable
}

func (s *SelectedNodeService) fetch(ctx context.Context) (map[string]selectedNodeObservation, error) {
	endpoint, err := url.Parse(strings.TrimSpace(s.cfg.Endpoint))
	if err != nil || endpoint == nil || !endpoint.IsAbs() || (endpoint.Scheme != "http" && endpoint.Scheme != "https") || endpoint.Host == "" {
		return nil, errors.New("selected-node endpoint is invalid")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
	if err != nil {
		return nil, errors.New("create selected-node request")
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Authorization", "Bearer "+s.cfg.Token)
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return nil, errors.New("selected-node request failed")
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("selected-node response status %d", resp.StatusCode)
	}
	mediaType, _, err := mime.ParseMediaType(resp.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		return nil, errors.New("selected-node response content type is not application/json")
	}
	maxBytes := s.cfg.MaxResponseBytes
	if maxBytes <= 0 {
		maxBytes = 65536
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBytes+1))
	if err != nil {
		return nil, errors.New("read selected-node response")
	}
	if int64(len(body)) > maxBytes {
		return nil, errors.New("selected-node response exceeds configured limit")
	}
	var decoded selectedNodeResponse
	if err := json.Unmarshal(body, &decoded); err != nil || decoded.Slots == nil {
		return nil, errors.New("selected-node response is invalid JSON")
	}
	result := make(map[string]selectedNodeObservation, len(decoded.Slots))
	now := s.now()
	for rawSlot, rawItem := range decoded.Slots {
		slot := strings.TrimSpace(rawSlot)
		if !validSelectedNodeText(slot, maxSelectedNodeSlotBytes) {
			continue
		}
		var item selectedNodeResponseItem
		if err := json.Unmarshal(rawItem, &item); err != nil {
			continue
		}
		name := strings.TrimSpace(item.SelectedNodeName)
		if item.Status != SelectedNodeStatusFresh && item.Status != SelectedNodeStatusStale {
			continue
		}
		if !validSelectedNodeText(name, maxSelectedNodeNameBytes) {
			continue
		}
		observedAt, err := time.Parse(time.RFC3339, item.ObservedAt)
		if err != nil || observedAt.After(now.Add(selectedNodeClockSkew)) {
			continue
		}
		observation := selectedNodeObservation{Name: name, ObservedAt: observedAt, SourceStatus: item.Status}
		if s.observationStatus(observation, now) == SelectedNodeStatusUnavailable {
			continue
		}
		result[slot] = observation
	}
	return result, nil
}

func validSelectedNodeText(value string, maxBytes int) bool {
	if value == "" || len(value) > maxBytes || !utf8.ValidString(value) {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}
