// Package chatroles adapts Chat roles for strict upstreams independently of gateway routing.
package chatroles

import (
	"encoding/json"
	"errors"
	"net/url"
	"strings"
)

func requiresSystem(platform, target string) bool {
	switch platform {
	case "deepseek", "kimi", "zhipu":
		return true
	}
	u, err := url.Parse(target)
	if err != nil {
		return false
	}
	switch strings.ToLower(u.Hostname()) {
	case "api.deepseek.com", "api.kimi.com", "api.moonshot.cn", "api.moonshot.ai", "open.bigmodel.cn", "api.z.ai":
		return true
	}
	return false
}

// Normalize only adapts known incompatible API Key targets. It has no network,
// configuration, logging, or retry side effects and never mutates the input.
func Normalize(platform, accountType, target string, body []byte) ([]byte, error) {
	if accountType != "apikey" || !requiresSystem(platform, target) {
		return body, nil
	}
	var root map[string]json.RawMessage
	if json.Unmarshal(body, &root) != nil || root == nil {
		return nil, errors.New("chat role adapter: invalid request object")
	}
	raw, exists := root["messages"]
	if !exists {
		return body, nil
	}
	var messages []json.RawMessage
	if json.Unmarshal(raw, &messages) != nil {
		return nil, errors.New("chat role adapter: invalid messages array")
	}
	changed := false
	for i, raw := range messages {
		var message map[string]json.RawMessage
		if json.Unmarshal(raw, &message) != nil || message == nil {
			return nil, errors.New("chat role adapter: invalid message object")
		}
		var role string
		if json.Unmarshal(message["role"], &role) != nil {
			return nil, errors.New("chat role adapter: invalid message role")
		}
		if role != "developer" {
			continue
		}
		message["role"] = json.RawMessage(`"system"`)
		updated, err := json.Marshal(message)
		if err != nil {
			return nil, errors.New("chat role adapter: cannot encode message")
		}
		messages[i] = updated
		changed = true
	}
	if !changed {
		return body, nil
	}
	updated, err := json.Marshal(messages)
	if err != nil {
		return nil, errors.New("chat role adapter: cannot encode messages")
	}
	root["messages"] = updated
	return json.Marshal(root)
}
