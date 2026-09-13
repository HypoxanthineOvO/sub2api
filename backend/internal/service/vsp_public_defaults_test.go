package service

import "testing"

func TestVSPPublicAPIBaseURL(t *testing.T) {
	for _, tc := range []struct{ input, want string }{
		{"https://api.vsplab.cn", "https://api.vsplab.tech"},
		{" https://api.vsplab.cn/ ", "https://api.vsplab.tech"},
		{"https://api.vsplab.tech", "https://api.vsplab.tech"},
		{"https://custom.example/v1", "https://custom.example/v1"},
		{"https://api.vsplab.cn.example", "https://api.vsplab.cn.example"},
		{"https://api.vsplab.cn/custom", "https://api.vsplab.cn/custom"},
		{"", ""},
	} {
		if got := vspPublicAPIBaseURL(tc.input); got != tc.want {
			t.Errorf("vspPublicAPIBaseURL(%q) = %q, want %q", tc.input, got, tc.want)
		}
	}
}
