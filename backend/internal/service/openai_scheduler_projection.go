package service

import (
	"time"
)

// OpenAIAccountQuotaTaperFactor exposes the production quota taper for read-only projections.
func OpenAIAccountQuotaTaperFactor(account *Account, now time.Time) float64 {
	return openAIAccountQuotaTaperFactor(account, now)
}

// OpenAIWeightedSelectionProbability projects the official non-sticky first-choice
// pool. It intentionally uses the same score shift and quota taper as production.
func OpenAIWeightedSelectionProbability(accounts []*Account, scores map[int64]OpenAIAccountSchedulerScoreSnapshot, topK int, now time.Time) map[int64]float64 {
	if len(accounts) == 0 {
		return map[int64]float64{}
	}
	candidates := make([]openAIAccountCandidateScore, 0, len(accounts))
	for _, account := range accounts {
		if account == nil {
			continue
		}
		snapshot, ok := scores[account.ID]
		if !ok {
			continue
		}
		candidates = append(candidates, openAIAccountCandidateScore{
			account:  account,
			loadInfo: &AccountLoadInfo{},
			score:    snapshot.BaseScore,
		})
	}
	if len(candidates) == 0 {
		return map[int64]float64{}
	}
	ranked := selectTopKOpenAICandidates(candidates, topK)
	weights := buildOpenAIWeightedSelectionWeights(ranked, now, true)
	total := 0.0
	for _, weight := range weights {
		total += weight
	}
	result := make(map[int64]float64, len(ranked))
	if total <= 0 {
		return result
	}
	for i := range ranked {
		result[ranked[i].account.ID] = weights[i] / total
	}
	return result
}
