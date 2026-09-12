# Babel 迁移后的代理退役记录

日期：2026-09-12，Asia/Shanghai。本文件只记录本轮已确认的清理范围、执行结果与待办；不是新发布流程已经上线的声明。

## 当前结论：本轮代码与系统服务退役已完成

用户已在 Genesis 和 Babel 执行清理命令，两边均返回 `COMPLETE`。2026-09-12 20:33–20:36 的独立只读验收确认：

| 范围 | 实际结果 |
| --- | --- |
| Babel Slot A–F | 全部 inactive / disabled，PID=0；配置与运行目录已移出，仅保留供 general 使用的 Mihomo 模板 |
| Babel allocator / selected-node / proxy dashboard | unit 均 not-found，PID=0；专用代码、配置及状态路径已不存在 |
| Babel 端口 | 17901–17905、17907、19290、19291、29091–29096 均不再监听 |
| Babel 保留代理 | general active，PID `876` 不变，7890/7892/29090 继续监听，两个 Mihomo 根目录均只剩 general |
| Babel 主服务 | blue PID `39097`、PostgreSQL `912`、Redis `926`、cloudflared `788` 均与清理前一致；Nginx active，PID `989`，清理器亦报告保护检查通过 |
| Babel production target | active，Requires 仅 PostgreSQL / Redis；不再依赖旧槽位或 sidecar，Wants 包含 general 和当前 blue |
| Genesis | 旧原生 systemd 注册、App/allocator 提权发布入口及对应 sudoers 文件已不存在；数据库诊断工具保留 |
| Genesis 保护项 | 用户 Mihomo PID `10876` 不变、NRestarts=0，7890/7892 监听；lichf 的 17906 进程仍为 PID `10915` |
| 健康路径 | 应用直连、8081 回源、本机 HTTPS、经 general 转发及 Genesis 外部公网检查均返回 200、`status=ok`；HTTPS 校验通过 |

资源快照：Babel 内存 available 约 822 MiB，根盘剩余约 23 GiB。该快照不是受控性能实验，不能把前后内存差额全部归因于清理。

本文件同步到 `Babel:/home/heyx/VSP-Sub2API/RETIREMENT.md`；Babel 原 README 顶部添加了清理完成提示与本文件链接，原有清理前快照保留为历史，避免被误当作当前操作指引。

归档保存在各主机 `/var/backups/vsp-sub2api-retirement/` 下的运行子目录，root 所有、0700；本机用户级 unit 另有下文所列归档。用户贴回了成功摘要，但未贴每次 `ARCHIVE=` 的完整子目录名；普通 SSH 账号不能直接列出该受保护目录。本轮没有销毁归档。

边界：数据库中的六条旧代理配置记录、历史数据、旧应用 release、Docker 数据容器仍保留。清理器成功结果确认环境文件已关闭 selected-node，但没有重启 App；运行进程中的旧开关留待下次受控发布生效。清理阶段未发布新应用版本、未调整产品代码。随后按用户要求，将已有生产源码单独提交为 `04218bfbf`；2026-09-13 用户批准将退役和发布流程改动归入本次第二批源码提交，详见 [RELEASE-REVIEW.md](RELEASE-REVIEW.md)。

## 已确认范围

- 本轮先清理退役代理代码和服务。国模适配、复制 URL / API Key、客户端配置等产品微调全部后置。
- Babel 保留应用蓝绿槽位、PostgreSQL、Redis、Nginx、cloudflared，以及一个通用代理。
- Babel 通用代理是 `vsp-mihomo-production@general.service`，配置在 `/etc/vsp-sub2api/production/mihomo/general/config.yaml`，监听 `127.0.0.1:7890`，控制器为 `127.0.0.1:29090`。保留其配置、订阅和运行数据。
- Genesis 保留用户级 `mihomo.service`，以及 `~/.config/mihomo` 和 Mihomo 二进制。当前会话使用 `7890/7892`，不能将它与退役的 `mihomo-llm@` 混淆。
- 退役范围：内部 Slot A–F、allocator、selected-node sidecar、专用代理看板及其维护任务。通用产品代理能力和数据库结构本轮不删除。
- 不删除账号、用量、历史数据库、备份、应用 release 或归属未确定的 Docker 数据服务。

## 已完成：仓库代码

- 移除 `ops/llm-proxy`、`ops/selected-node` 的实现与测试，以及旧槽位配置生成器。
- 移除 allocator、selected-node、rehearsal Mihomo 的 systemd 模板；保留 production Mihomo 模板用于 general。
- 解除 production/rehearsal target 和旧应用 unit 对退役代理的依赖。production target 用 `Wants` 引入 general，不因其停止而停止数据库。
- 应用 release 安装器不再附带 allocator / selected-node 代码。
- 提权安装器仅保留 App-only wrapper，不再创建 allocator release、drop-in 或免密入口；未运行该安装器。
- 原生环境示例关闭 `SELECTED_NODE_ENABLED`；随后用户执行系统清理时也关闭了 Babel 的 `app.env` 开关，现有进程未重启。
- 删除旧 Docker-to-native cutover、rehearsal restore、配置生成器和代理迁移 SQL，防止旧流程重建已退役组件。历史可从 Git 的 `63e0a0f02` 检索。
- 更新蓝绿文档，明确现有脚本不是已经适配完成的 Genesis-to-Babel 发布流程。
- 本轮没有修改 backend/frontend 产品源码；开始工作前已有的 12 个修改文件及 2 个未跟踪测试文件全部保留，随后按用户要求归入生产基线提交 `04218bfbf`。

## 已完成：Genesis 用户级服务

确认以下 unit 和槽位实例均 inactive/disabled、没有运行进程后，已归档并移除：

- `~/.config/systemd/user/llm-proxy-allocator.service`
- `~/.config/systemd/user/llm-proxy-docker-forward.service`
- `~/.config/systemd/user/mihomo-llm@.service`

归档：`/home/heyx/.local/state/vsp-sub2api/retired-user-units-20260912/`，目录权限 0700。

随后仅执行用户级 `daemon-reload`。受保护的 `mihomo.service` 保持 active，前后 PID 均为 `10876`，7890/7892 持续监听；未重启代理。

## 已核实的 Babel 业务依赖

使用会话只读保护、10 秒语句超时查询了代理表和账号绑定汇总，没有输出凭据，也没有写数据库。

- 未删除代理共六条：ID 4–9，对应端口 17901–17905 和 17907。
- 六条代理均没有未删除账号引用。
- 当前所有未删除账号的 `proxy_id` 均为空，OpenAI 账号不可调度。
- 代理记录仍在数据库中，尚未禁用或软删除；历史备份表和已删除账号未清理。
- 停服务前另外完成了 root 环境文件、后台任务和系统依赖检查，不能只凭上述绑定判断无依赖。

## 已完成：系统级清理（以下保留执行过程）

用户先执行并返回两份无读取错误的 root 预检，再执行两边的清理命令，均返回 `COMPLETE`。具体现场验收见顶部。以下预检结论描述的是清理前状态，不是当前残留清单。

### 先运行脱敏只读预检

Genesis：

```bash
sudo python3 /home/heyx/Workspace/VSP/VSP-Sub2API/deploy/native/inspect-retirement.py --host genesis
```

Babel（预检脚本已交付到家目录管理入口）：

```bash
sudo python3 /home/heyx/VSP-Sub2API/bin/inspect-retirement.py --host babel
```

脚本验证主机名，只读取受保护的环境、systemd 依赖、相关 cron / Nginx / sudoers 引用和端口归属。代理地址去掉认证、路径及查询参数；任务只报告文件名或行号。不修改配置、不启停服务、不查询业务数据。

### root 预检结论与最终执行入口

- Genesis 旧原生服务全部停止，但 blue 仍有开机启用链接，需要移除；旧提权发布入口也需要退役。
- Genesis 的 17906 已确认属于 `lichf` 的 `mihomo-docker-forward.py`，不在本轮范围。数据库诊断工具与发布脚本共用 libexec 目录，清理只能删除四个指定发布脚本，不能移除整个目录。
- Babel target 仍 Requires 六个槽位和 selected-node。必须先更新 target 并解除相关 wants/requires 链接，再 daemon-reload，然后才能停止组件。
- Babel root cron 有两条相关任务；预检只返回行号，没有返回完整命令。已审阅 `refresh_xyz.sh`、`revive_daily.sh` 及调用链，它们只更新内部六槽和 allocator；general 为三个静态节点，没有 proxy-provider 文件依赖。执行器会现场核对 cron，仅接受这两种固定任务，遇到复合命令或未知任务立即拒绝，不能仅凭行号删除。
- Babel 当前进程的 `SELECTED_NODE_ENABLED=true`。代码中唯一调用者是 Lab Dashboard 的代理节点展示：账号无代理时不请求 sidecar，失败也不会进入请求转发路径。因此本轮可移除 sidecar，但不重启 App；配置文件关闭开关，进程中的旧值留待下次正常发布生效。

执行器为 `retire-proxy-plane.py`，默认仅展示计划；带 `--execute` 才变更。每次执行创建 root 所有、0700 的 `/var/backups/vsp-sub2api-retirement/<host>-<timestamp>-*/`，记录修改前配置、原 cron 和被移出的 unit / 专用代理配置 / 状态 / 运维脚本。保留全部应用 release、数据库与其数据目录、备份、通用代理、无关容器和用户数据。数据库只查绑定，不写代理表。

Genesis：

```bash
sudo python3 -I /home/heyx/Workspace/VSP/VSP-Sub2API/deploy/native/retire-proxy-plane.py --host genesis --execute
```

Babel：

```bash
ssh -t Babel 'sudo python3 -I /home/heyx/VSP-Sub2API/bin/retire-proxy-plane.py --host babel --execute'
```

执行器有主机校验、只读账号绑定检查、后台任务检查、外部服务依赖检查和存量代理连接保护；Babel 每停止一个退役服务都复核受保护 PID 与应用 / 回源健康。Genesis 仅接受本地原生栈已经停止的状态。程序不调用 App / 数据库 / general / Nginx / Tunnel 的 stop、restart 或 reload。

成功应出现 `COMPLETE`。失败则输出 `STOPPED ON ERROR` 和归档路径；已经完成的动作留在 `actions.json`，不会假装全部回滚，也不会重启整个生产栈。请将输出交回核对后再继续，不自行追加 `rm` 或整栈 restart。

执行器已交付 Babel，SHA-256 为 `e538a900e1766e802b67953501928f813d3b82f6b830268994e72ac0be6a2198`；root 清理由用户执行，Agent 负责交付和后续只读验收。

### 已执行流程与有意保留的后续项

1. 归档精确范围内的 unit、配置和任务；不将秘密放进 Git。
2. 确认 general 不依赖退役脚本或订阅更新任务，再解除 target、环境和定时任务引用。
3. 明确当前 App 的 selected-node 是否启用及如何让关闭配置生效。不能为了删 sidecar 直接重启承载流量的应用。
4. 停用 Babel 六个槽位、allocator、selected-node、看板；验证应用、数据库、Redis、general、Nginx 与 Tunnel 不受影响。
5. 移除已停用 unit、专用脚本与配置及本机旧发布入口。Babel 当前启用的 Nginx 文件中未发现看板回源；Cloudflare 远程路由不在本轮核查范围。代理表条目仍保留，后续配置整理时单独处理。
6. Genesis 移除旧 Sub2API 系统级代理及部署残留。保留旧数据库容器及已确认属于 lichf 的 17906 监听。
7. 记录实际结果，并再次检查关键服务 PID、健康状态和保留代理。

## 验证

```bash
bash deploy/native/verify.sh
git diff --check
```

本轮新增 10 项回归检查，覆盖退役入口不存在、打包和提权路径不再引用退役代码、target 依赖、general 保留、示例配置、产品代码保留、wrapper 参数与生成结果，以及预检输出脱敏。静态和隔离测试不等同于生产清理已执行。

执行结果：10 项检查、Shell 语法、`git diff --check` 均通过；将模板实例化为 blue / rehearsal 后的 `systemd-analyze verify --recursive-errors=no` 返回 0。再次逐文件校验 3719 个 backend/frontend 条目，未发现相对本轮起点的产品源码变化。

预检脚本已交付 Babel，远端与本地 SHA-256 均为 `d0fc7cc0c474790c1e5c75130b041e9a1a93aa3181d0bd84de6021c50925cafa`。交付后 Babel blue 仍为 PID `39097`、general 为 PID `876`，两者 active，应用 `/health` 正常。之后用户执行 root 预检并返回结果，见上文。

执行器补充验证：原有 10 项检查 + 16 项新测试全部通过，覆盖配置保留、cron 精确匹配、路径归档、符号链接、数据库诊断工具保护，以及模拟执行中先解依赖后停服务、外部依赖拒绝、活动连接拒绝、停服务失败不归档其数据。`go test ./internal/service -run '^TestSelectedNodeService' -count=1` 通过。测试与真实 root 执行分开记账；真实执行已由用户完成，另有顶部只读验收证据。

## 后续边界

本轮代码和系统服务退役已完成。随后已单独提交既有生产源码、清理旧 worktree 和项目临时文件，并完成新发布流程的本地实现与验证。2026-09-13 用户批准将这些维护改动归入第二批提交；本次不推送、不安装权限、不发布生产，也不重写历史。首次接入改为用户安排的低流量维护窗口，生产验收仍待执行；产品调整继续后置。最新进展见 [RELEASE-REVIEW.md](RELEASE-REVIEW.md)。
