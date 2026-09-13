package service

import "strings"

// Keep VSP's legacy default compatible without rewriting administrator settings
// or changing unrelated/custom endpoints. This is a public-display overlay.
func vspPublicAPIBaseURL(value string) string {
	if strings.TrimRight(strings.TrimSpace(value), "/") == "https://api.vsplab.cn" {
		return "https://api.vsplab.tech"
	}
	return value
}
