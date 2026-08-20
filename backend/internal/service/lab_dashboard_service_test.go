package service

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestLabDashboardDisplayNameNeverFallsBackToEmail(t *testing.T) {
	require.Equal(t, "Alice", labDashboardDisplayName("Alice", "alice", "alice@example.com", 7))
	require.Equal(t, "alice", labDashboardDisplayName("", "alice", "alice@example.com", 7))
	require.Equal(t, "User 7", labDashboardDisplayName("", "", "alice@example.com", 7))
	require.Equal(t, "User 7", labDashboardDisplayName("alice@example.com", "alice@example.com", "alice@example.com", 7))
}

func TestLabDashboardProbabilityUnavailableWithoutConfiguredGroup(t *testing.T) {
	probability, status := labDashboardProbability(nil, nil)
	require.Nil(t, probability)
	require.Equal(t, "unavailable", status)
}

func TestLabDashboardSwitchesUsesFullRequestChain(t *testing.T) {
	oldAccount := &Account{Name: "Card A"}
	got := labDashboardSwitches([]UsageLog{
		{ID: 1, UserID: 9, RequestID: "req", AccountID: 10, Account: oldAccount, CreatedAt: time.Unix(1, 0)},
		{ID: 2, UserID: 9, RequestID: "req", AccountID: 11, Account: &Account{Name: "Card B"}, CreatedAt: time.Unix(2, 0)},
	})
	require.Equal(t, "Card A", got[2])
}
