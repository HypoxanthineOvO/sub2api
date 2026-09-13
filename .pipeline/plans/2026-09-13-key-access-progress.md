# 模型目录与复制界面：本地实现检查点

状态：本地实现与验证完成，待界面审阅及生产变更审批。沿用已批准的下一版计划，以及“目录提供完整配置信息、不按实时可用性或 Key 权限筛选”的修正。目录准备工具提交 `9475d8672`；VSPi 消费适配提交 `7e1039d1`；界面独立提交，均未推送。

## 已实现

1. 独立 `frontend/src/features/vsp-key-access/` 模块：默认 BaseURL、APIKey、组合复制三个动作；组合文本保持 `BaseURL: xxx, APIKey: yyy` 一行。用户认可手机版，并明确要求直接显示完整 API Key；已移除遮罩，长 Key 自动换行，复制完整值，空 Key 禁止复制。
2. 六个可选客户端入口：Codex、Pi、ZCode、Kimi Code、VSP-Codex、VSPi。无 Claude Code/OpenCode 入口，不删除后端协议。Provider 配置不强制先选模型，不设置默认模型、不做可用性查询。
3. 进入高级配置才读取 `/vsp/models`，无 Authorization/Cookie、不跳转，有 4 MiB 上限与 8 秒超时，关闭/换地址/换 Key 时取消。请求失败提示重试；同一弹窗重读失败保留最后有效目录。原始 JSON 全字段、全模型保留。
4. Pi/Kimi 按协议生成配置；64 个声明全部保留，包括隐藏条目。VSPi 直接配置 `vsp-models` 数据源。Codex 两种发行版使用各自目录和 Provider ID，Key 通过环境变量提供；ZCode 给 GUI 字段和完整 ID 列表，不覆写内部配置文件。
5. KeysView 仅替换一处 import；AppLayout 只关闭 onboarding 自动启动。公告、合规提示、手动引导保留。旧 UseKeyModal 不再挂载，恢复官方内容与测试；因为 GroupPlatform 仍含 VSP 扩展，留下两行类型/标签 fallback 兼容，未通过排除文件绕过编译。
6. `deploy/catalog/` 提供离线校验、从已提交权威文件准备不可变目录产物，以及待审阅的 Nginx 精确路径片段。无新常驻服务，无数据库表，无生产写操作。
7. VSPi 接收可选 `capabilities` 字段；新模型可显式声明 `tool_use` 等能力，无需逐模型分支。修复未知模型的旧思考修订覆盖问题，保持用户 overrides。没有修改现有 64 条模型数据或增加提供商账号/路由。

## 明确的格式边界

- BaseURL 沿用站点配置；通用复制使用根地址，OpenAI 配置补 `/v1`，Anthropic 模板使用根地址。**本轮未修改 Babel 的 api_base_url 设置**，不能因预览显示 .tech 就认为线上已变更。
- 未声明协议时 Pi/Kimi 模板默认 Chat Completions，页面明确提示；源 JSON 不补猜测值。无法映射的显式协议提示格式限制，仍可复制原始目录，不删除条目伪造完整结果。
- 原版客户端只投影自身支持的配置字段；完整的思考、价格、来源和扩展元数据保留在目录 JSON 中，不保证每个客户端都能原生展示 VSP 的全部字段。没有使用真实 Key 启动推理调用。
- `capabilities` 是元数据，不授予工具权限、不保证网关有服务。已有字段缺省行为保留；使用新能力声明需要包含本次消费适配的 VSPi 版本。
- `effortRevision` 管理思考字段修订，不是全目录版本号。本轮采用源 Git commit 和数据 SHA 标识产物，不增加全目录持久化状态机。

## 验证证据

- 前端全量 275 个测试文件、2012 项测试通过；新模块 12 项专项测试通过，lint 通过，Vue 类型检查及生产前端构建通过。
- 实际 Chromium + Vue 组件验证：完整 Key 展示及长 Key 换行、精确剪贴板文本、默认无请求、六个入口、读取完整 64 条目录、不带认证头、Pi JSON 与四份 TOML 解析、375px 窄屏、暗色、Escape。临时 HTML、Vite 进程自动清理。
- 目录工具 5 项测试通过，含真实私有 Nginx：完整 JSON、CORS、缓存头、拒绝 POST，以及非法数据、修订倒退和不可变产物。
- VSPi 目录发现/合并测试 34 项通过，agent-core-v2 typecheck 通过，导入边界检查通过。回归覆盖未知模型显式能力、低修订拒绝覆盖和用户 overrides。
- Go 发布执行权 service/server 定向检查通过；本轮不改 Sub2API 后端逻辑，包含新前端的 embed 构建通过，版本输出为 0.2.4。开发验证二进制在记录 SHA 后删除，历史生产产物保留；这不是正式发布包。
- 产物 `dist/catalogs/256f507c2bb0ebd07221de7206675ee7daf1ad2ed604c60fbb400bd4b0a79a06/` 已准备，JSON 与权威源逐字节一致，共 64 条，尚未上传或安装。
- 日志/截图位于 `dist/validation/key-access/`，不提交构建文件或测试密钥。

## 并行工作区处理

VSPi 稳定性会话与本任务并行工作，其 runtime、反馈与服务脚本改动不属于本次提交。解析文件中一行 `profile && ...` 判断由该会话在 2026-09-13 08:49 UTC 补充；已通过 thread metadata 定位到会话 `01a0945c-61a7-7e71-909c-cb3ef51be4a9` 并核对具体 patch。该判断是本次修订保护变化需要的空值防护，保留并补充回归，不覆盖该会话其他工作。VSPi 提交只选择本次解析器、对应测试和目录说明三个文件。

## 尚未进行

- Babel 的 .tech 官方设置变更、目录 JSON 发布、Nginx 路由/CORS 配置核对。
- 生产 DeepSeek 渠道/分组价卡对齐，235–237 迁移的完整生产备份恢复验收。
- 新发布器首次安装、维护窗口切换、正式发布包上传及实际应用发布。
- 六个客户端带真实凭证的线上端到端调用；本轮只验证配置结构，不用探活充当目录过滤。

下一步先审阅默认与高级界面，再汇总上述上线变更清单；不以本地提交替代生产审批。日常维护方式见 `deploy/catalog/README.md`，客户端格式及验证方式见 `frontend/src/features/vsp-key-access/README.md`。
