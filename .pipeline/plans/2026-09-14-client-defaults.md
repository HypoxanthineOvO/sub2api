# 默认 API 端点与客户端默认配置位置微调

## 已上线并验收

普通发布作业 `a3afa75491464223a896d82a8d1643b6` complete，executor inactive。应用源码 `f6c33441c315`，当前 Green release `f6c33441c315-d7d502064cb6` / PID 188754；旧 Blue `af8b6ea163e6-1da8e3276114` / PID 186879 保留为同 schema 回滚目标。正式包迁移清单与旧版逐项相同；本次上传和部署由 Agent 使用已安装免密入口完成，没有要求用户输入 sudo、没有执行 schema 维护。

实际回源只读验收：health HTTP 200 且 deployment identity 匹配 Green；`/api/v1/settings/public` HTTP 200 且 `api_base_url=https://api.vsplab.tech`；`/vsp/models` 仍为 64 条、SHA `256f507c2bb0ebd07221de7206675ee7daf1ad2ed604c60fbb400bd4b0a79a06`。PG/Redis/general proxy/Nginx/cloudflared 主 PID 仍为 912/926/876/989/788，没有重启这些服务。公网探针 Cloudflare403 的已知降级记录保留，public_access_verified=false。

前端已发布，用户刷新页面即可取得新资源；本机 Chromium 验证八个入口及复制/路径布局，不冒称已用用户生产账号登录验收。构建日志 `dist/validation/schema-release/build-client-defaults.log`，前端/浏览器日志 `dist/validation/client-defaults/`，截图 `dist/validation/key-access/clients-mobile-dark.png`。

用户要求：默认端点从 .cn 改为 .tech；六个已有客户端只展示官方/本项目默认位置，不读用户文件或寻找自定义位置；新增 Claude Code 和 OpenCode，但明确标为不推荐。用户授权自行完成，沿已安装普通免密发布流程交付；不重复 schema 迁移。

## 实现

- 独立 `backend/internal/service/vsp_public_defaults.go` 只规范公开设置中的旧 VSP 默认根地址：`https://api.vsplab.cn` → `https://api.vsplab.tech`。官方接入点仅 setting_public.go 的一处调用；默认端点卡片、复制界面、HTML 注入配置与公开 API 使用同一值。其他自定义地址和路径保留。
- 这是展示兼容层，不修改管理员存储值、不写 DB、不增加 SQL；后台原始设置可能仍显示 .cn。未来管理员持久化设置为 .tech 后此规则自然不再介入。这样本次发布可保持同 schema/可普通回滚，并避免改无关后台逻辑。
- 客户端默认位置全部静态展示，含 macOS/Linux、Windows 主目录写法和复制按钮；不读取本机文件、不探测用户名或用户自定义目录。唯一个外部数据读取仍为本站公开 /vsp/models，不带 Cookie/API Key。
- Kimi Code 修正为当前官方 `~/.kimi-code/config.toml`；ZCode 补 `~/.zcode/v2/config.json` 并引导通过应用内设置填写，不能把普通字段文本当作完整配置文件覆盖。
- Codex `~/.codex/config.toml`、Pi `~/.pi/agent/models.json`、VSP-Codex `~/.vsp-codex/config.toml`、VSPi `~/.vspi/config.toml`；VSP-Codex 片段与本项目首次初始化的 vsp/experimental_bearer_token 形态一致。
- Claude Code 默认 ~/.claude/settings.json，OpenCode 默认 ~/.config/opencode/opencode.json 及 ~/.local/share/opencode/auth.json。两个入口与详情均标为不推荐，不编造安全/兼容性结论作为理由。
- OpenCode 按协议生成三个 SDK provider，完整保留所有模型 ID；Key 单独写官方 auth.json 结构，避免配置插值误解原始 Key。无真实客户端调用、不筛掉 offline/hidden、不更改用户默认模型。

## 依据与验证

官方来源链接集中在 frontend/src/features/vsp-key-access/README.md：Codex 配置参考、Pi models.md、ZCode Configuration、Kimi Code Data Locations、Claude Code Settings、OpenCode Config/Auth 源码；两个 VSP 客户端仅查仓库默认契约，未读取用户配置。

前端 275 个测试文件、2014 项测试通过；typecheck/lint 通过，后端默认地址边界测试通过。真实 Chromium 使用合成 Key 和完整 64 模型目录，验证八个入口、JSON/TOML、复制、默认位置、不推荐标签、手机/暗色/关闭行为。没有请求真实模型服务；这些不等同于八个客户端端到端测试。

发布状态以最后的生产验收补充为准；本轮不修改 Cloudflare WAF、不改 DeepSeek 自定义价卡。
