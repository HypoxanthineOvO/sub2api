# VSP Key Access

本模块接替 KeysView 的 UseKeyModal，保持 show/apiKey/baseUrl/platform/allowMessagesDispatch 与 close 契约（platform 可以为 null）。默认视图只有三个复制动作和可选客户端入口；不加载模型，不自动选择客户端，也不根据分组切换到 Claude 配置。

- `credentials.ts`：根地址、协议后缀、组合复制文本、TOML/两种 shell 转义。
- `catalog.ts`：只读 `/vsp/models`，不带 Cookie/API Key，不跳转，不做在线或权限查询；有取消和 4 MiB 大小限制。
- `clientConfigs.ts`：八个客户端的纯格式转换函数和静态默认路径，不读取用户文件或探测自定义目录；完整模型数组不因 hidden/offline/Key 权限被过滤。
- `KeyAccessModal.vue` / `messages.ts`：复用现有 Dialog、样式和 Clipboard/Toast，独立中英文文案；关闭或更换凭证/地址取消请求，失败可重试，重读失败保留当前弹窗中的最后有效目录。

## 客户端配置

| 客户端 | 内容 |
| --- | --- |
| Codex | 用户级 `~/.codex/config.toml` 的 Responses Provider，`VSP_API_KEY` 环境变量；不改默认模型 |
| Pi | `~/.pi/agent/models.json`，按声明协议分组到 Provider，保留所有模型 ID；API Key 用环境变量，避免其命令/变量解析误解 Key 字符 |
| ZCode | 默认 `~/.zcode/v2/config.json`，引导用应用内 Settings → Model Providers → Add Provider 填写字段，不覆写内部文件 |
| Kimi Code | 当前官方默认 `~/.kimi-code/config.toml`，不再展示旧 ~/.kimi 路径；按协议生成声明，不设默认模型 |
| VSP-Codex | 独立 `~/.vsp-codex/config.toml`，使用本项目首次初始化的 vsp / experimental_bearer_token 形态，不复用原版认证目录 |
| VSPi | 独立 `~/.vspi/config.toml`，引用 `/vsp/models` 自动读取元数据 |
| Claude Code（不推荐） | `~/.claude/settings.json`，env 配置 Anthropic 根端点及 AUTH_TOKEN，不强行选择模型 |
| OpenCode（不推荐） | `~/.config/opencode/opencode.json` 按协议声明 Provider/模型；Key 单独放 `~/.local/share/opencode/auth.json` 的 api/key 项，避免配置插值解析密钥 |

每个客户端静态列出 macOS/Linux 与 Windows 主目录写法，可复制默认路径。不读取本机文件、不检测用户名或自定义目录；用户改过位置需自行查找。OpenCode 额外展示凭据位置；两个不推荐客户端在入口和详情处同时标注，其余六个不加该标签。已有文件须合并，不能整份覆盖。

通用 BaseURL 是根地址，OpenAI 协议补 `/v1`，Anthropic 模板用根地址由 SDK 补消息路径。协议缺省时 Pi/Kimi 模板按 OpenAI Chat Completions 生成；这是配置默认值，不是根据模型名猜测能力或在线状态。

所有原始元数据保留在可复制的完整目录 JSON 中。原版客户端仅投影其文档明确支持的格式，不把 VSP 扩展字段生硬塞入不兼容配置，也不承诺每个客户端能呈现全部思考档位。客户端不支持的显式协议会给出格式提示，仍可查看完整原始目录；不删模型来伪装成功。

配置片段需合并到已有用户配置，不是全文件覆写脚本。按用户确认，默认页直接展示完整 API Key，不加遮罩或显示开关；长 Key 自动换行，复制仍保持原始完整值。Key 不写日志、localStorage 或外部链接。无效地址、空 Key 或剪贴板错误有明确反馈。

## 与上游的接入点

KeysView 一处 import 指向本模块，AppLayout 的 onboarding 设置 `autoStart: false`，不删除公告、合规提示或手动引导。旧 UseKeyModal 和测试恢复官方内容；因 VSP 仍扩展 GroupPlatform 联合类型，旧组件保留两行 Partial 类型与标签 fallback 兼容，避免通过排除文件来逃避类型检查。

2026-09-14：默认端点通过独立后端 `vsp_public_defaults.go` 的窄范围展示兼容层处理：仅将公开设置中的旧默认 `https://api.vsplab.cn`（含末尾斜杠）映射为 `https://api.vsplab.tech`，供默认端点卡片和复制弹窗统一使用。其他自定义域名/路径不变；不写数据库、不增加迁移，管理员原始设置值保留。未来存储值改为 .tech 后，该兼容规则自然不再介入。

## 资料与验证

2026-09-14 核对：[Codex](https://learn.chatgpt.com/docs/config-file/config-reference)、[Pi](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)、[ZCode](https://zcode.z.ai/en/docs/configuration)、[Kimi Code 默认位置](https://moonshotai.github.io/kimi-code/en/configuration/data-locations.html)、[Claude Code](https://code.claude.com/docs/en/settings)、[OpenCode](https://opencode.ai/docs/config/)，以及 VSP-Codex/VSPi 仓库默认契约。OpenCode 凭据格式核对官方 auth/index.ts；Anthropic SDK 自定义 baseURL 使用 /v1，与 Kimi/Claude Code 根地址规则区分。没有读取用户本机配置或用真实 Key 请求推理服务。

```sh
pnpm -C frontend test:run src/features/vsp-key-access/__tests__
pnpm -C frontend typecheck
```

浏览器脚本 `deploy/tests/key-access-browser-test.py` 使用本地 Vite 与合成 Key，可通过 `CATALOG_FILE` 指定实际公开目录，并通过 `CHROMIUM_EXECUTABLE` 选择已安装 Chromium。用 webapp-testing 的 with_server helper 启动 127.0.0.1:5120 后运行；脚本自动删除临时 HTML、拒绝其他外部请求，截图写入 `dist/validation/key-access/`。它验证真正 Vue 组件、剪贴板、八个入口、默认路径/不推荐标记、JSON/TOML 语法、模型完整性、窄屏、暗色及 Escape；不等同于八个客户端的真实线上端到端测试。
