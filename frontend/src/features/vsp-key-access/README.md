# VSP Key Access

本模块接替 KeysView 的 UseKeyModal，保持 show/apiKey/baseUrl/platform/allowMessagesDispatch 与 close 契约（platform 可以为 null）。默认视图只有三个复制动作和可选客户端入口；不加载模型，不自动选择客户端，也不根据分组切换到 Claude 配置。

- `credentials.ts`：根地址、协议后缀、组合复制文本、TOML/两种 shell 转义。
- `catalog.ts`：只读 `/vsp/models`，不带 Cookie/API Key，不跳转，不做在线或权限查询；有取消和 4 MiB 大小限制。
- `clientConfigs.ts`：六个客户端的纯格式转换函数，不请求服务；完整模型数组不因 hidden/offline/Key 权限被过滤。
- `KeyAccessModal.vue` / `messages.ts`：复用现有 Dialog、样式和 Clipboard/Toast，独立中英文文案；关闭或更换凭证/地址取消请求，失败可重试，重读失败保留当前弹窗中的最后有效目录。

## 客户端配置

| 客户端 | 内容 |
| --- | --- |
| Codex | 用户级 `~/.codex/config.toml` 的 Responses Provider，`VSP_API_KEY` 环境变量；不改默认模型 |
| Pi | `~/.pi/agent/models.json`，按声明协议分组到 Provider，保留所有模型 ID；API Key 用环境变量，避免其命令/变量解析误解 Key 字符 |
| ZCode | GUI Provider 字段、OpenAI/Anthropic 地址和完整模型 ID 列表，不覆写内部文件 |
| Kimi Code | `~/.kimi/config.toml`，按协议生成 Provider 和模型声明，不设默认模型 |
| VSP-Codex | 独立 `~/.vsp-codex/config.toml`，保留自己的 Provider ID，不复用原版认证目录 |
| VSPi | 独立 `~/.vspi/config.toml`，引用 `/vsp/models` 自动读取元数据 |

通用 BaseURL 是根地址，OpenAI 协议补 `/v1`，Anthropic 模板用根地址由 SDK 补消息路径。协议缺省时 Pi/Kimi 模板按 OpenAI Chat Completions 生成；这是配置默认值，不是根据模型名猜测能力或在线状态。

所有原始元数据保留在可复制的完整目录 JSON 中。原版客户端仅投影其文档明确支持的格式，不把 VSP 扩展字段生硬塞入不兼容配置，也不承诺每个客户端能呈现全部思考档位。客户端不支持的显式协议会给出格式提示，仍可查看完整原始目录；不删模型来伪装成功。

配置片段需合并到已有用户配置，不是全文件覆写脚本。Key 只出现在用户主动查看/复制的配置内，不写日志、localStorage 或外部链接。默认页显示遮罩但复制完整 Key。无效地址、空 Key 或剪贴板错误有明确反馈。

## 与上游的接入点

KeysView 一处 import 指向本模块，AppLayout 的 onboarding 设置 `autoStart: false`，不删除公告、合规提示或手动引导。旧 UseKeyModal 和测试恢复官方内容；因 VSP 仍扩展 GroupPlatform 联合类型，旧组件保留两行 Partial 类型与标签 fallback 兼容，避免通过排除文件来逃避类型检查。

BaseURL 的 `.tech` 变更仍使用官方站点设置，本模块不硬编码替换 `.cn`。本轮只在测试中使用 `.tech` 配置；Babel 的设置修改单独确认。

## 资料与验证

配置格式核对：[Codex](https://learn.chatgpt.com/docs/config-file/config-reference)、[Pi](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)、[ZCode](https://zcode.z.ai/en/docs/configuration)、[Kimi Code](https://moonshotai.github.io/kimi-code/en/configuration/providers)，以及 VSP-Codex/VSPi 当前本地配置契约。没有用真实 Key 调用推理服务。

```sh
pnpm -C frontend test:run src/features/vsp-key-access/__tests__
pnpm -C frontend typecheck
```

浏览器脚本 `deploy/tests/key-access-browser-test.py` 使用本地 Vite 与合成 Key，可通过 `CATALOG_FILE` 指定实际公开目录，并通过 `CHROMIUM_EXECUTABLE` 选择已安装 Chromium。用 webapp-testing 的 with_server helper 启动 127.0.0.1:5120 后运行；脚本自动删除临时 HTML、拒绝其他外部请求，截图写入 `dist/validation/key-access/`。它验证真正 Vue 组件、剪贴板、六个入口、JSON/TOML 语法、模型完整性、窄屏、暗色及 Escape；不等同于六个客户端的真实线上端到端测试。
