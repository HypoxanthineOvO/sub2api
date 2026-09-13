# 产品界面外挂与上游升级计划（已批准，分阶段实施）

日期：2026-09-13。当前本地分支 `vsp/main`，HEAD `869d54b1a`；应用基于上游 v0.2.1。本轮只检查代码、公开配置和官方资料，没有修改产品源码、生产配置或部署状态。

实施授权（2026-09-13）：用户批准按下个版本计划推进；上述分支与 HEAD 是实施前基线。Provider Configuration 与 `/vsp/models` 的具体模型配置内容必须先讨论确认，不擅自填值或发布。先实施本地上游升级并审阅迁移与 VSP 保留项；生产部署、数据库迁移、sudo 操作另行确认。执行进展见同目录 `2026-09-13-upstream-v0.2.4-progress.md`。

后续确认（2026-09-13）：MiMo 等非官方扩展保留代码与历史数据兼容性，本轮先不接入，不新增账号、路由或默认推荐；官方 MiniMax 去重。用户确认 VSPi 模型配置已经核对，应作为标准，后续 `/vsp/models` 向其权威源文件对齐，不再以线上旧快照覆盖它。协议缺省字段的解释与六个客户端模板仍需讨论，且目录声明不等同于线上已开放。

计费补充（2026-09-13）：用户要求 DeepSeek 费率查询最新官方并以官方为准。这一具体价格决定覆盖该模型目录中的旧价格来源；其余模型信息仍以 VSPi 标准为准。实现与上线边界见 `2026-09-13-deepseek-pricing.md`，不把更新元数据等同于改完数据库中所有渠道/分组价卡。

范围修正：用户明确 Provider Configuration / `/vsp/models` 只负责完整提供已维护的配置信息，不负责实时可用性或 Key 权限筛选。暂时没有服务的模型仍保留元数据；用户实际调用时，由现有网关返回结果或不可用/无权限等错误。撤销“先选实际可用模型才生成配置”的额外要求，不新增探活、预检或权限查询，也不改动已有运行时鉴权。配置声明不承诺服务可用；VSPi 中既有的展示标记保留为元数据，不据实时服务状态自动删改。

## 结论

采用“官方已有设置 + VSP 独立前端模块 + 两个薄接入点”，不建设新插件框架，不通过 CSS/DOM 注入隐藏已运行的组件。先整理上游 v0.2.4 升级，再在目标基线上接入界面调整，升级与定制分开提交和验收。

用户补充：更新 `/vsp/models` 的模型信息，与 VSPi 对齐，并整理稳定、易扩展的接口。该项作为独立的跨仓库目录契约任务纳入计划，不扩成新的模型管理平台。“两个薄接入点”仅指前三项 UI 调整，不代表新增的模型目录任务完全没有客户端改动。

## 下个版本审阅摘要

本版定位：**更新官方基线、精简客户端接入、统一 VSP 模型目录**。以已核查的上游 v0.2.4 为固定候选目标；实施前复核 tag，若出现更新版本只汇报，不擅自扩大升级范围。

| 交付包 | 本版必须完成 | 审阅点 |
| --- | --- | --- |
| 1. 官方基线升级 | 合并 v0.2.4，保留 VSP 发布/任务协调行为，评估官方 MiniMax 与现有实现的重叠，审阅三条 SQL | 合并冲突、数据迁移、回退前提 |
| 2. 模型目录 | 对齐 `/vsp/models` 与 VSPi，确定单一数据源和最小兼容契约，让已有协议下新增模型主要只改目录数据 | 模型差异表、字段优先级、下线/缓存语义、客户端契约测试 |
| 3. 接入体验 | .tech BaseURL；默认三个复制动作；六个客户端配置入口；关闭自动欢迎引导 | 默认界面预览、实际复制文本、六份配置格式与元数据完整性 |

按“升级 → 目录与 VSPi → 复制界面 → 联合验收”推进，每块独立提交，不混成一个大改动。BaseURL 的官方设置修改可在批准后独立先做。

上线前另有一个已有前置：新发布工具已经提交，但尚未安装到 Babel、尚未完成首次启动验收。它不阻塞本地产品开发；正式上线前按用户同意的低流量维护窗口完成收尾，不再重做旧版热交接设计。

本版不顺带重写鉴权、计费、提供者路由、VSPi runtime/daemon，不新增模型管理平台或常驻服务。此前提及但尚未提供具体描述的 Bug、非官方适配回退清单继续列为待定，不擅自删除或扩大到本版；与官方重复的实现仅在升级审查中逐项处理。

待确认的展示约定仍是：通用 BaseURL 沿用根地址 `https://api.vsplab.tech`，客户端配置按协议补 `/v1`；Pi 指 Pi coding agent，ZCode 指智谱/Z.ai ZCode。

## 已核实的事实

- 线上 `GET https://api.vsplab.tech/api/v1/settings/public` 仍返回 `api_base_url=https://api.vsplab.cn`；没有 custom_endpoints。前端业务源码未找到写死的 api.vsplab.cn / .tech。
- KeysView 从 `publicSettings.api_base_url` 传值给 UseKeyModal 和 EndpointPopover；因此展示/复制的域名优先用官方设置修改。
- 复制配置弹窗是 `frontend/src/components/keys/UseKeyModal.vue`，当前 1911 行，只有 KeysView 一个实际使用点。其 Props 为 show、apiKey、baseUrl、platform、allowMessagesDispatch，事件为 close。
- 与官方 v0.2.1 相比，现有 UseKeyModal 和测试仍有少量 VSP 差异。迁出需要的行为后，可让原文件重新完全跟随目标上游版本，而不是继续在其中加分支。
- 可对应到“欢迎来到/欢迎使用 Sub2API”的文案属于 onboarding。AppLayout 传入 `autoStart: true`；composable 当前只为管理员标准模式自动启动。它与公告弹窗、管理员合规弹窗不是同一个组件。
- 官方插件 UI Bridge 当前是受限 iframe 配置页，不能访问父页面 DOM，也没有已发现的核心 API Key 弹窗替换接口；本任务不适合强行套 `.s2plugin`。
- `/vsp/models` 未在当前 Sub2API 核心路由中找到；VSPi 的 `ops/vsplab/README.md` 将 `model-catalog.json` 声明为权威目录，并记录由 Nginx 对外提供。VSPi 已有 `relayCatalog.ts` 负责地址派生、结构校验和元数据合并；本轮只核对了这些本地资料，线上 JSON 与源文件的逐项差异留待实施时确认。

## 1. BaseURL：先用已有配置，零产品代码改动

批准后，通过现有后台设置/API 把 `api_base_url` 改为 `https://api.vsplab.tech`。不直接写数据库以绕过配置缓存，不修改管理 API 的 `/api/v1`，不顺手删除旧域名的路由或证书。

默认沿用现有语义：通用复制给出网关根地址，不带末尾斜杠。客户端模板按所用协议补充 `/v1` 等路径，避免 `/v1/v1`。若用户希望通用地址也固定带 `/v1`，实施前单独确认这一展示约定。

验收：公开设置、Keys 页地址、通用复制和六个客户端配置中的目标域名都为 .tech；不得把第三方上游厂商域名全局替换。

## 2. 新复制界面：默认只做三件事

默认是“通用”视图，不根据账号平台自动打开某个客户端说明：

```text
使用 API Key

BaseURL  https://api.vsplab.tech          [复制 BaseURL]
APIKey   隐藏显示                        [复制 APIKey]

[复制 BaseURL + APIKey]

客户端配置（可选，进入后才展示）
```

一起复制的内容严格使用一行：

```text
BaseURL: https://api.vsplab.tech, APIKey: <完整APIKey>
```

- 复制完整 Key，不复制遮罩；成功/失败反馈复用现有 useClipboard 与 Toast。
- 默认不查询模型目录、不下载文件、不生成 CLI 安装命令。只有进入需要模型配置的客户端界面时才加载必要信息。
- Key 不写日志、localStorage、埋点或外部链接；不新增保存 Key 的后端 API。
- 沿用 BaseDialog、现有明暗主题和图标，支持键盘、窄屏和关闭后取消异步请求，不另换 UI 库或字体。

客户端配置只保留六个入口：

| 分组 | 客户端 | 适配原则 |
| --- | --- | --- |
| 原版 | Codex | 按官方 custom provider 配置，复用已有 Codex 目录/参数工具，不按实时服务状态删减模型声明 |
| 原版 | Pi | 暂按 pi coding agent 理解，使用其 models.json provider 格式 |
| 原版 | ZCode | 暂按智谱/Z.ai ZCode 理解；优先提供官方 GUI 的 Base URL、Key、Model ID 填写说明，不强制生成内部配置文件覆写脚本 |
| 原版 | Kimi Code | 使用当前客户端 provider 配置；协议类型与目标服务匹配，不混用旧 kimi-cli 和新 kimi-code 文档字段 |
| VSP | VSP-Codex | 按 VSP-Codex 自己的配置契约，不冒用原版 Codex 的 auth/config 路径 |
| VSP | VSPi | 按 VSPi 的实际配置契约和目录，与 Pi/Kimi Code 分开维护 |

Claude Code、OpenCode 不再出现在此弹窗；不因此删除后端 Anthropic/OpenAI 协议、计费或系统管理中的相关能力。其他页面的 CC Switch 等入口不在本轮顺手删除。

模型配置信息来自完整的权威目录，不以 Key 权限或实时可用性过滤，也不强制先选模型再生成 Provider 配置。各客户端按自身配置格式消费目录，实际请求沿用现有网关处理和错误返回；不承诺目录中的每个模型当前都有服务。只针对当前实际使用的客户端版本，不建设覆盖所有历史版本的兼容平台。

## 3. 代码组织：独立模块、薄接入，不拷贝大组件

建议新增目录：

```text
frontend/src/features/vsp-key-access/
  KeyAccessModal.vue       通用复制 + 可选客户端配置
  clientConfigs.ts         六个客户端的数据与最小配置生成函数
  credentials.ts          URL 规范化、组合文本与转义
  __tests__/               单元与集成测试
```

复用官方 BaseDialog、Icon、useClipboard、已存在的 Codex 配置工具。模块内部的纯字符串生成逻辑与 Vue 渲染分开测试，但不抽象成泛化插件系统。

预计长期维护的上游接点：

1. **KeysView 一处 import**：将原名 UseKeyModal 指向 VSP 组件，保持 Props / close 契约，原页面业务逻辑不改。
2. **AppLayout 一项现有选项**：将 onboarding 的 autoStart 改为 false。

原 UseKeyModal 不再挂载，但文件保留。把现存 VSP 小补丁中需要的行为迁出后，将原组件及原版测试恢复为 v0.2.4 的官方版本，从而消除该处长期 fork 差异。不是把官方 1911 行组件复制一遍再删选项。

不采用：MutationObserver 注入、根据中文文字查找 DOM、CSS 遮住仍运行的弹窗、全局 Vite alias 偷换所有同名模块、扩大官方插件 Bridge 权限。

## 4. 欢迎弹窗：只关闭自动新手引导

使用现成 `autoStart: false`，不改引导内部状态机、不伪造 localStorage“已读”状态。手动“重新查看引导”入口先保留。公告、管理员合规提示和其他业务确认弹窗不受影响。

当前定位是代码中的 onboarding 欢迎页；若用户实际指的是普通用户登录后的自定义欢迎公告，实施前用截图确认，不能把两种弹窗一起删除。

## 5. `/vsp/models` 与 VSPi 同步、接口整理

### 内容对齐

先对比三处：Babel 实际 `/vsp/models` 响应、VSPi 仓库中的权威目录文件、VSPi 当前解析及本地基线。列出差异再修改，不凭模型名称推测能力，也不把目录中的模型数量等同于当前可用数量。

需要对齐的信息包括：稳定模型 ID / 别名、显示名称、协议、上下文与输出上限、输入及工具能力、思考模式与档位 / 默认值、展示价格及单位/依据、发布时间、隐藏或下线状态。具体要改哪些模型和值，先形成清单供确认；涉及能力与价格时保留官方来源和核对时间。展示价格元数据不替代 Sub2API 实际计费逻辑。

### 单一数据来源与接口约定

- 维护一份权威模型声明，经校验后发布到 `/vsp/models`，VSPi 通过现有消费者同步，不在服务端、客户端和复制界面分别手写模型名单。优先沿用现有 `VSPi/ops/vsplab/model-catalog.json`，若确需迁移维护位置，先明确所有权并一次迁移，不保留双重权威源。
- 延续独立 JSON / 外部目录方式，不为了目录信息新增 Sub2API 核心 Provider 分支、数据库表或常驻服务。
- 区分接口结构版本与数据修订号。现有消费者接受 `version: 1`，兼容新增字段优先，不随新增模型就修改结构版本；破坏性变化必须另行审阅。
- 明确字段必需性、缺省/空值含义、价格单位、未知能力的处理及下线语义。已有 `effortRevision` 不能丢掉；旧修订不得覆盖新声明。
- 明确合并优先级：保留用户显式 overrides；有效且不倒退的远程声明更新元数据，缺省字段保留合理本地基线或标记未知，不编造能力。
- `/vsp/models` 是完整的 VSP 配置元数据接口，不能替换或破坏官方 `/v1/models` 等标准响应。公共目录不是授权或服务状态清单；配置生成不新增 Key 权限查询、服务探活或可用性筛选。实际请求继续由既有网关鉴权、路由并如实返回结果或错误。
- 复用现有刷新机制，明确缓存/修订与失败回退规则；优先使用普通 HTTP 缓存与已有客户端刷新事件，不新增推送系统。失败或坏 JSON 不覆盖最后一次有效目录。

### VSPi 接入与后续新增流程

- VSPi 优先只修改现有 relay catalog 解析/投影层，不往每个模型的执行路径添加判断；核对现有“按模型名推断”的必要性，能用明确声明表达的能力逐步收敛到数据。
- BaseURL 与目录 URL 一致切换到 .tech；默认目录地址继续从 provider 地址派生，不再散落写死的旧域名。
- 普通新增模型的目标流程：**增加一条声明 → 结构与语义校验 → 客户端契约测试 → 发布目录 → VSPi 刷新验证**。不需要改多个 switch、重编译主服务或重发客户端。
- 真正新增协议/能力类型时才扩展一次适配器；不预先建设覆盖全部未来场景的框架。
- 新 Key 配置界面在需要模型信息时复用这份完整目录，不叠加权限/可用性预检；默认三按钮视图仍不拉模型。

该项按“目录数据 / 接口契约”和“VSPi 消费适配”分别记录与验收；本次仅更新计划，不改动两个仓库的实现或线上目录。

## 6. 上游版本评估

- 核查时最新正式 release：**v0.2.4**，GitHub API 显示发布时间为 **2026-09-09 15:04:53 +08:00**，非 prerelease。
- 从 v0.2.1 到 v0.2.4：GitHub compare 返回 181 个提交；完整 tag 文件树比较为 503 个变更文件。
- compare API 的 files 列表在 300 项截断，因此未用该列表冒充完整差异。上述文件数和热点由两个完整、未截断的 Git tree 独立比较得到。
- 目标上游修改了 UseKeyModal，但没有修改 KeysView、AppLayout、useOnboardingTour、AppHeader 或 vite.config。这支持选择薄接入点而不是直接深改原弹窗。
- 新增三条 SQL：235_group_model_allowlist.sql、236_group_model_allowlist_repair.sql、237_add_minimax_platform.sql。
- 上游还修改 wire.go 和 ops_cleanup_service.go，和本轮发布任务执行权补丁有接触面，升级时必须检查。
- v0.2.4 已加入官方 MiniMax 支持，并改进长流连接与若干配置问题；需核对并尽量去重现有 VSP 的同类实现，不能再保留两套路由。

因此，升级不是改 VERSION 或一条 pull。目标固定为审阅过的 tag/commit，不追未经验证的 main。先比较依赖、迁移、后台任务和当前 VSP 行为，再合并。

当前发布器默认拒绝迁移清单变化。上面三条 SQL 必须独立审阅、备份和安排维护操作；不能用普通 App-only 命令直接上线，也不临时把迁移检查关掉。具体升级执行步骤在差异审阅后确定，本轮 UI 不承担数据库迁移职责。

## 7. 分步执行与审阅点

| 阶段 | 内容 | 交付 / 审阅 |
| --- | --- | --- |
| A | 确认本计划；BaseURL 配置可独立先改 | 确认根地址约定、六个客户端名单、欢迎弹窗范围及模型目录差异清单 |
| B | 冻结 v0.2.4，做上游同步、依赖/迁移检查、VSP 行为去重与保留 | 单独升级提交；汇报冲突与三条迁移，不在生产直接试 |
| C | 对齐 `/vsp/models`、权威目录和 VSPi；固定最小接口契约与新增模型流程 | 审阅字段、覆盖优先级、下线和缓存行为；目录与客户端分别验证，不双处维护名单 |
| D | 在目标基线上添加 VSP 独立弹窗和两个薄接点 | 先审默认三按钮界面，再验六个客户端内容；复用模型目录，单独 UI 定制提交 |
| E | 前后端、目录与客户端联调，升级与发布计划复核 | 生成候选包，用户确认维护窗口与实际变更后再上线 |

若新发布流程的首次生产验收尚未完成，需把它作为发布准备单独说明，不默认将“第一次装发布器 + 上游数据库升级 + UI 改造”混为一次未经演练的变更。

## 验收标准

- 默认打开只有通用复制，不再自动进入 Claude/Codex 等客户端页。
- 三个按钮复制内容准确，组合格式完全匹配要求，失败反馈不吞掉；空 Key 不复制占位符。
- 客户端列表恰好六项；Claude Code / OpenCode 不出现；原版与 VSP 配置目录不串用。
- BaseURL 与协议后缀不会重复；JSON/TOML 字符串正确转义，模型 ID 不凭空猜测。
- 新用户/管理员刷新页面不自动弹新手欢迎；公告与合规提示仍正常。
- 新 UI 只在 VSP 目录维护；KeysView 接口约束有集成测试，避免上游更新后悄悄接回原弹窗。
- `/vsp/models` 与 VSPi 对同一模型的协议、能力、上限、思考档位和价格单位解释一致；缺省、未知与不支持状态有明确差异。
- 对已有协议新增一个测试模型，只改权威目录即可被 VSPi 发现并正确展示；无需添加按模型名称分支的代码。
- 重复 ID、非法数值和版本回退被拒绝；网络失败保留有效缓存；用户 overrides 不被同步覆盖。
- 暂时无服务的模型仍保留配置声明；目录不把“有元数据”表述为“保证可用”，不按实时状态删减条目。既有隐藏/展示标记按权威源同步，不直接删除用户配置或历史会话；现有运行时鉴权和错误返回不受影响。
- 原版测试、新 VSP 测试、typecheck/build、发布执行权测试和涉及的数据库迁移测试通过。

## 证据与资料

- 代码：KeysView.vue:995/1139，AppLayout.vue:40，useOnboardingTour.ts:524，backend/pkg/pluginapi/docs/ui-bridge.md。
- [Sub2API v0.2.4 正式发布](https://github.com/Wei-Shaw/sub2api/releases/tag/v0.2.4)
- [v0.2.1 至 v0.2.4 对比](https://github.com/Wei-Shaw/sub2api/compare/v0.2.1...v0.2.4)
- [Codex 自定义 provider](https://learn.chatgpt.com/docs/config-file/config-advanced)
- [Pi 自定义模型](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/models.md)
- [ZCode 自定义 provider](https://zcode.z.ai/en/docs/configuration)
- [Kimi Code providers](https://moonshotai.github.io/kimi-code/en/configuration/providers)
- VSP-Codex 本地 docs/config.md：默认 ~/.vsp-codex/config.toml，与原版认证文件隔离。
- VSPi 本地 README：默认 ~/.vspi/config.toml，可通过 vspi config path 查询，VSPI_HOME 可覆盖。
- 模型目录来源：`/home/heyx/Workspace/VSP/VSPi/ops/vsplab/README.md`、同目录 `model-catalog.json`。
- VSPi 目录消费者：`/home/heyx/Workspace/VSP/VSPi/packages/agent-core-v2/src/app/kosongConfig/relayCatalog.ts`；已有 version=1、effortRevision、字段校验、请求超时和响应大小限制，应优先扩展这一层。
