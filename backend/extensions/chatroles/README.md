# Strict Chat role adapter

This extension normalizes `messages[].role = developer` to `system` only for known incompatible API Key upstreams. It is compiled into the release; it is not an OAuth transport plugin or a separate proxy process.

## Integration boundary

The only core integration is an import and a call to `Normalize` in `internal/service/openai_gateway_chat_completions_raw.go`, after routing/model mapping and target URL resolution, before `sendCCUpstreamRequest`. Keep this seam when merging upstream releases. The existing dynamic transport plugin currently handles OpenAI OAuth, not these API Key requests.

- Selected platforms: `deepseek`, `kimi`, `zhipu`.
- Also handles OpenAI-compatible accounts pointing to the exact official hosts `api.deepseek.com`, `api.kimi.com`, `api.moonshot.cn`, `api.moonshot.ai`, `open.bigmodel.cn`, `api.z.ai`.
- Other targets, OAuth accounts, Responses and Anthropic paths remain unchanged. No model-alias guessing, protocol pinning, extra retries, database migrations, or new runtime configuration.
- Preserves message order/content, tool calls/results, unknown fields and JSON number precision. Does not mutate the original request; failover to another account sees the original roles. Compatible requests remain byte-identical.
- Invalid message structures are rejected without echoing raw content. No request bodies, keys, or prompts are logged by this extension.

## Validation and rollout

```sh
cd backend
go test ./extensions/chatroles
go test -tags unit ./internal/service -run 'TestForwardAsChatCompletions_StrictRoleMixedPool' -count=1
```

The gateway test runs the real Chat dispatch, mapping, request encoding and usage/SSE handling against a strict upstream boundary. It covers native and OpenAI-compatible account platforms and both response modes. Removing the integration call reproduces upstream `400 unknown variant developer`.

Build and roll out using the existing `deploy/native/vsp-release` client and blue/green controller. A binary rollback removes this adapter; it does not require a configuration rollback. Release artifacts include this directory through the normal Go build. No additional daemon or administrator installation is required.
