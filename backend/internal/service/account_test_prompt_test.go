package service

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestAccountTextPayloadsUseEditablePrompt(t *testing.T) {
	const customPrompt = "请只回答你的训练数据截止年月。"

	claudePayload, err := createTestPayload("claude-test", customPrompt)
	require.NoError(t, err)
	claudeMessages := claudePayload["messages"].([]map[string]any)
	claudeContent := claudeMessages[0]["content"].([]map[string]any)
	require.Equal(t, customPrompt, claudeContent[0]["text"])

	openAIPayload := createOpenAITestPayload("gpt-test", customPrompt, false)
	openAIInput := openAIPayload["input"].([]map[string]any)
	openAIContent := openAIInput[0]["content"].([]map[string]any)
	require.Equal(t, customPrompt, openAIContent[0]["text"])

	chatPayload := createOpenAIChatCompletionsTestPayload("gpt-test", customPrompt)
	chatMessages := chatPayload["messages"].([]map[string]any)
	require.Equal(t, customPrompt, chatMessages[0]["content"])
}

func TestAccountTextPayloadsUseKnowledgeCutoffQuestionByDefault(t *testing.T) {
	claudePayload, err := createTestPayload("claude-test", "  ")
	require.NoError(t, err)
	claudeMessages := claudePayload["messages"].([]map[string]any)
	claudeContent := claudeMessages[0]["content"].([]map[string]any)
	require.Equal(t, defaultTextTestPrompt, claudeContent[0]["text"])

	openAIPayload := createOpenAITestPayload("gpt-test", "", false)
	openAIInput := openAIPayload["input"].([]map[string]any)
	openAIContent := openAIInput[0]["content"].([]map[string]any)
	require.Equal(t, defaultTextTestPrompt, openAIContent[0]["text"])

	chatPayload := createOpenAIChatCompletionsTestPayload("gpt-test", "")
	chatMessages := chatPayload["messages"].([]map[string]any)
	require.Equal(t, defaultTextTestPrompt, chatMessages[0]["content"])
}
