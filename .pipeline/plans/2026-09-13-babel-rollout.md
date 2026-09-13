# Babel 下一版上线与回退清单（待审批）

核查时间：2026-09-13 17:14–17:20 +08:00。本文是部署方案，不是已执行记录。本轮仅只读核查 Git、源码和 Babel 状态，没有 push、构建正式包、sudo、上传、安装或生产切换。

2026-09-14 准备更新：用户已授权完成本地准备。管理员维护入口、恢复演练与故障测试已实现；Go 工具链记录已修正，installer 可安全创建缺失的 libexec 父目录。下文“尚未实现/待补”是规划时状态，现以 `deploy/native/SCHEMA-MAINTENANCE.md` 为准。生产仍未安装、未执行。现在只需要用户在 Genesis 交互终端运行 `python3 /home/heyx/Workspace/VSP/VSP-Sub2API/deploy/native/inspect_babel.py`，提供只读结果后才能填写实际数据库和发布 ID。

## 结论

建议 **同一个低流量维护窗口，分两个独立验收段**：

1. 先把现有 v0.2.1 接入新发布器，用只含已审阅维护改动的过渡版验证首次启动。
2. 第一段成功后，单独做数据库维护升级，再启用 v0.2.4 和新界面。

不重做蓝绿架构、不追求旧版热交接、不新增常驻代理服务。发生失败就停在上一验收点。普通同 schema 发布继续用现有 Agent 免 sudo 入口；数据库结构升级/恢复不混入普通自动发布。

**目前不能直接执行第二段：现有首次启动与普通发布都拒绝迁移清单变化；管理员数据库维护路径尚未实现。** 这是一项待补的有限上线准备工作，不是把门禁关掉或修改旧 manifest。正式包也尚未生成，本文中的 release ID 只能在构建后填写。

## 1. 当前事实

| 项目 | 核查结果 |
| --- | --- |
| 生产 | Babel，blue active，green inactive；blue PID 39097，直接 health 正常 |
| 生产目录 | `/opt/vsp-sub2api/releases/63e0a0f02-2b03fab94` |
| 生产 binary SHA-256 | `751804b943589c74bac0d8c885179619b59f5e7ef46715a12011e93744fbb6fe`，与历史基线包一致 |
| PostgreSQL / Redis | 主进程 PID 912 / 926；生产 PostgreSQL 使用 16 系列二进制，OS 用户 postgres |
| 保留服务 | general proxy PID 876、Nginx master PID 989、cloudflared PID 788，均 active |
| 发布器 | `/usr/local/bin/vsp-release`、managed 路径和配置未安装；sudoers 文件普通用户不能完整检查，但无其他已安装迹象 |
| 资源 | 物理内存 1613 MiB，MemAvailable 947 MiB；swap 2047 MiB、已用 143 MiB；磁盘可用约 23 GiB |
| 当前 API 展示地址 | 公开设置仍为 `https://api.vsplab.cn` |
| 模型目录 | Babel 仍为 SHA `3568de7af80215a1dbc8fc9d64414945352e128c5eb926250c8ee65959f7f985` |
| Git | 本地 `vsp/main` 为 `869d54b1a`；远端 `origin/vsp/main` 为 `63e0a0f02cd127942a5f93394d6a1a5d07e2b5f2` |
| 功能候选 | `codex/next-version-v0.2.4` 的 `281fadae57933ef6d41c1b2dd86788fcdc0ae999`；若补部署脚本提交，需重新冻结最终 SHA |
| 待发布目录 | 已准备 SHA `256f507c2bb0ebd07221de7206675ee7daf1ad2ed604c60fbb400bd4b0a79a06`，64 条，源数据 commit `cf252f8b905d9eaa00e0ce61d02a845909a0f74c` |

`.cn` HTTPS、`.tech` HTTPS 和 `.tech` 的 127.0.0.1:8081 回源入口均代理到 `sub2api_app`。维护措施必须覆盖三处，不能只关其中一个域名。Nginx 同时承载其他站点，只修改 API 相关配置。

权限检查：App env 是 root:root 0600，PostgreSQL 数据目录 postgres:postgres 0700，socket 目录 0750；普通用户读取运行进程环境也被拒绝。没有继续绕过权限或索取/输出密钥。数据库实际大小、角色/认证、schema_migrations 内容、已启用的模型列表配置、DeepSeek 现有价卡及恢复耗时尚未核实，需管理员只读预检；不为方便检查而放宽 env 权限。另确认 `/usr/local/libexec` 不存在，安装前需要管理员创建该标准父目录，否则当前安装器的 trusted-parent 检查会失败。

## 2. 版本与物料，不混用

| 物料 | 身份 | 用途 |
| --- | --- | --- |
| L：历史基线 | `baseline-04218bfbf222-a3cc2054ba98.tar`，worker_gate=0，v0.2.1 | 现有运行 binary 的原样归档，用于安装核验和最初恢复；不是重新编译的新版 |
| A：过渡应用 | 源码 `869d54b1ad1da9a8fd8dc451cb8d13c3b5a3d166`，worker_gate=1，v0.2.1 | 首次验证新发布流程，不混入上游 SQL 与产品变化；正式包待构建 |
| B：功能应用 | 当前功能源码 `281fadae5`，最终 SHA 待准备工作结束后锁定，worker_gate=1，v0.2.4 | 新功能与 235–237；正式包待构建 |
| 控制器 | 审阅后的 Python 源码、installer、release 与 app-slot 两份 unit | 单独交付，不是应用包内的 root hook |
| 模型目录 | `dist/catalogs/256f507c…/` 下 JSON + manifest | 独立元数据发布，不依赖重编译 App |

已经逐文件比较迁移清单：L → A 无新增、删除或变更；L/A → B 仅新增 235、236、237，既有 SQL 无修改。237 保留本项目的平台超集补丁，不能用官方同名文件覆盖本项目版本。

## 3. 窗口前准备（不停止生产）

### 我方准备

- 补齐管理员受控数据库维护入口：固定 Babel、候选版本、数据库目标和备份范围；使用现有发布互斥/持久化记录，仍由管理员明确启动，不加入普通 Agent sudoers 的授权范围。
- 该入口必须在任何候选连接生产库之前核对受审阅的迁移差异；不能让 `release_initial.py` 绕过当前门禁，也不能把旧包的 migrations 改成新包的值。
- 修正构建器 Go 工具链记录的工作目录：现在在仓库根目录取 `go version`，可能记到 go1.25.1 launcher，而 backend 实际选用 go1.27.0；应在导出的 backend 模块取值，并与 binary build info 交叉核对。
- 固定已验证的 Node24.16.0/pnpm10.5.0 PATH，避免嵌套 pnpm 调用混入其他版本；这是选择现有工具，不安装全局软件。
- 对管理员迁移/恢复路径演练中断、迁移失败、候选启动失败、状态恢复；获准后在窗口前使用受控生产快照完成恢复/迁移演练并测时，现有 5 项 SQL 夹具测试不能替代它。
- 所有准备改动先独立提交并通过验证，保持工作区干净。实际 DB 大小与演练耗时明确后再建议窗口长度，现阶段不承诺固定停机分钟数。

### 需要你批准并执行的管理员只读预检

- 核实实际 DB endpoint、数据库名、恢复角色/认证及完整备份权限，密钥不贴到聊天或日志。
- 只读检查迁移记账、groups 的旧/新列、已启用模型列表配置数量及内容差异；235 会把原列表配置同时用于请求准入，必须确认预期，不能因 SQL 成功就认为业务兼容。
- 核实实际 DB 大小、可用磁盘、应用外的逻辑写入者和待落账任务；确定备份/恢复所需空间。
- 核对两槽位的有效 systemd 配置及 drop-in，不只检查模板文件；确认新安装路径、权限与资源上限不会被其他配置覆盖。
- 列出 DeepSeek 渠道、分组及账号统计价卡，确认哪些覆盖默认价格；读取前不盲猜 ID，不覆盖整张价卡或无关厂商。
- 确认 DB 回退时本应用 Redis 可重建缓存的失效范围；不对 Redis 执行 FLUSHALL/FLUSHDB，不清除其他服务数据或未落账状态。

这组预检命令将在准备工具完成后单独交付；当前没有已安装的数据库诊断入口，不能把一个尚不存在的命令当成可执行操作。

## 4. Git 与正式构建顺序

当前构建器要求 **指定 commit 恰好等于远端 `origin/vsp/main` 的头**，所以不能先推 B，再用同一命令构建 A。审批后按以下顺序，不 force push：

1. 再读一次远端头，确认没有其他会话推进；与本文不同就先审阅差异。
2. 将远端以 fast-forward 推到 A，构建并保留 A 包。
3. 将完成准备工作的候选以 fast-forward 合入本地 `vsp/main`，推送最终 B，再构建 B 包。
4. A、B 都先在 Genesis 构建并校验完，才安排实际停服。开发验证 binary 不当正式包使用。

审批后的命令形状（下面不是现在要执行的指令）：

```sh
export PATH="/home/heyx/.volta/tools/image/packages/pnpm/bin:/home/heyx/.volta/tools/image/node/24.16.0/bin:$PATH"
git push origin 869d54b1ad1da9a8fd8dc451cb8d13c3b5a3d166:refs/heads/vsp/main
./deploy/native/vsp-release build --commit 869d54b1ad1da9a8fd8dc451cb8d13c3b5a3d166
# 保存该命令产生的 A_PACKAGE / A_RELEASE_ID；之后再合并、推送、构建最终 B。
```

两次 FF 关系本轮已核实，但执行时必须重新核实。metadata/控制器对应源码也需保存到批准的远端；不推送 VSPi 工作区中其他会话未审阅的改动。

## 5. 第一段：安装发布器，再启用过渡版 A

### 交付与安装

- 我方将控制器源码和 L 基线包用普通 SSH/SCP 放到 Babel 的专用 staging 目录并核对哈希。**第一次不能用 `vsp-release upload` 传 L**，因为远端 receive 入口尚未安装。
- staging 必须包含 `install-release-control.py`、当前 `SOURCES` 清单内的全部模块与 `schema_policy.json`，以及 `vsp-sub2api-release.service` / `vsp-sub2api-app-slot@.service`。实际目录和文件 SHA 在执行前交付，不能混入其他版本文件。
- 你审核后运行现有安装器。它备份旧 slot unit，创建 root 管理目录、受限入口和 19820 回环探针，校验并 reload Nginx；不重启 App/PG/Redis/general proxy。

安装命令模板（`<已交付目录>` 尚未创建，**现在不要粘贴执行**）：

```sh
sudo install -d -o root -g root -m 0755 /usr/local/libexec
sudo /usr/bin/python3 "/home/heyx/VSP-Sub2API/<已交付目录>/install-release-control.py" \
  --baseline "/home/heyx/VSP-Sub2API/<已交付目录>/baseline-04218bfbf222-a3cc2054ba98.tar"
```

安装验收：旧 blue 仍提供服务，受保护主进程 PID 未变；19820 验证仍指向 blue；普通用户 `vsp-release status` 不要求密码。此时自动 deploy 仍应因 legacy gate 被拒绝，这是预期保护。

安装失败时不直接重跑、不删除整片 managed 目录：安装器并非全目录事务回滚，部分新路径可能留下；先核对 `/var/backups/vsp-sub2api-release-install/<时间>/` 和现场差异，只恢复本次修改范围。旧 App 未被主动重启，修复前不推进 A。

### 首次启动 A

安装成功后我方普通用户上传 A；你在选定的低流量时间启动管理员初始事务：

```sh
# Genesis，A_PACKAGE 为真实构建输出
./deploy/native/vsp-release upload "$A_PACKAGE"

# Babel，A_RELEASE_ID 为包 manifest 中真实 ID
sudo /usr/bin/python3 /usr/local/libexec/vsp-sub2api-release/release_initial.py \
  "$A_RELEASE_ID" --maintenance-window

# Babel，普通用户查询
vsp-release status
```

不是看到 queued 就结束，要看到 complete，并验证请求路径和版本身份。A 默认进入 green；实际以状态文件为准。脚本先启动并检查候选，再停止旧 App、转移 worker、切流；若仍有旧连接，会拒绝停止，应换更安静时段或执行经批准的 API 维护门控，不强杀请求。

**检查点 A：**A 正常服务，worker 单活，旧 L 已停止且产物保留，数据/代理服务未重启。失败由现有 InitialEngine 恢复 L；recovery_failed 必须停下人工处理。验收未通过，不进入第二段。

## 6. 第二段：数据库维护 + v0.2.4 功能版 B

本节是待实现并演练的操作顺序，**不能用现在的 deploy 或 release_initial 命令代替**：

1. 获取同一发布互斥锁，确认 A 的状态、两个槽位和待导入 B 的完整身份；禁止其他 Agent 同时部署。
2. 仅对 API 的 `.cn` / `.tech` HTTPS 与 8081 回源启用维护响应，保留必要只读健康探针；不改其他站点。等待已有 API 请求排空、待落账工作完成，再停止两个 App 槽位及本应用其他逻辑写入者。PG、Redis、general proxy、cloudflared 不重启。
3. 记录最后写入点，制作本应用一致性备份：DB（含 schema_migrations）、必要恢复角色/权限信息、共享应用数据、app env/slot env、发布状态、Nginx 相关配置、原目录 JSON。放在 Babel root-only 的唯一备份目录，不把密钥或生产 dump 贴到聊天。未经批准不把敏感数据传到 Genesis。
4. 检查窗口内新鲜 dump 的完整性，按窗口前已经演练通过的恢复流程核对备份材料。若前置演练没做完，不开始迁移；不能只用 `pg_restore --list` 成功冒充恢复通过。逻辑 dump 只代表快照时点，因此冻结写入必须覆盖最终备份到验收这一段；参考 [PostgreSQL 16 SQL dump](https://www.postgresql.org/docs/16/backup-dump.html)。
5. 在获准的维护路径中允许本次 **精确的 235–237** 差异，由候选启动走官方迁移 runner；不能把手工执行 SQL 后漏写迁移记账作为方案。每份 SQL 是独立事务，后面一份失败不意味着前面全部撤销。记账 checksum 基于 TrimSpace 后 SQL，包 manifest 的文件哈希则是原始字节，两者不能直接混比。
6. 在公网仍维护的情况下，通过受控本地访问验证 B：健康、数据库查询、登录/Keys 页面、用户/余额/订阅等关键数据、模型准入语义、单一 worker。失败即执行下面的数据库恢复流程，不让旧程序碰已更名的新库。
7. 按第 7 节更新已批准设置/价卡和目录；使用受控测试凭据核验必要功能，不枚举用户 Key、不默认请求已暂停的 GPT、不对目录做可用性过滤。
8. 验收通过，记录新的 schema 基线和应用状态，**旧 v0.2.1 不能登记为普通热回滚目标**；保留为维护恢复材料。然后显式开放流量，观察错误率、延迟、重启/OOM、实际用量和计费，最后记录完成。

**检查点 B：**应用、DB schema、worker owner、Nginx 实际流向和版本记录一致。之后同 schema 的新版本可用普通蓝绿发布；跨 schema 的恢复仍需管理员流程。不要复制同一个 B 到另一个槽位，就宣称有一份能规避 B 业务 Bug 的旧版。

## 7. 本次配套配置清单

| 项目 | 做法 | 验收与回退 |
| --- | --- | --- |
| BaseURL | 官方后台/API 将 api_base_url 改为 `https://api.vsplab.tech`，保留其他设置 | 公开设置、Keys 页面及复制内容一致；失败仅恢复该设置，不直接 SQL 绕缓存 |
| DeepSeek 价卡 | 执行前复核官方最新价格，读取现有渠道/分组/账号统计价卡，逐项对齐 | 确认实际计价来源与工作日峰谷规则；保留旧价卡快照，不能用整库恢复代替一次价格纠正；不改历史扣款 |
| 模型目录 | 发布已审阅 JSON，保留全部 64 条配置元数据，不筛选在线状态或 Key 权限 | 同文件系统临时文件 + 原子替换；检查正文 SHA、JSON、CORS，失败原子恢复旧文件。仅 JSON 更新不重启 App，不需 Nginx reload |
| Nginx 目录路由 | 现有三个入口已有 `/vsp/models`，只合并必要响应头/路径变化，不再复制一段造成重复 location | 配置有改动才 `nginx -t` 并 reload；保留前快照；不改其他站点 |
| 界面 | 随 B 发布：完整 Key 展示、三复制动作、六客户端、关闭自动 onboarding | 桌面/手机确认；公告、合规提示、手动引导保留 |
| 代理 | 不新增接入或改动 general proxy；不删除数据库中保留的代理记录 | general PID 和必要出口不变；不恢复 allocator/内部代理 |

配置与目录变更分别记账。目录回退不等于 App 回退，App 回退也不会自动恢复设置或价卡。VSPi 源码消费适配的客户端发版走其自身维护流程，不在本次 Babel 操作里私自重启/升级 VSPi daemon。

## 8. 失败处理表

| 失败位置 | 处理 | 不允许做的事 |
| --- | --- | --- |
| 构建/传输/包校验 | 停止推进，生产仍原版本 | 使用开发 binary 或未校验半包顶替 |
| 安装发布器 | 核对安装备份，恢复本次 unit/探针/权限差异；确认旧 App 正常 | 盲目反复安装、删除用户原发布目录 |
| A 首次启动 | InitialEngine 恢复 L；失败状态需人工核验 | 把 queued 当成功、继续做 DB 升级 |
| B 迁移/启动/验收，尚未开放流量 | 保持维护门控，停止 B，恢复备份 DB（含迁移记账）和配套文件/必要缓存状态，恢复 A 的槽位/worker/入口；验证后才开放 | 只切回 A binary、只改一列名、在部分迁移状态强启旧程序 |
| 配置或目录单项错误 | 恢复该项前快照并验证 | 为小配置错误回灌整库、覆盖其他厂商设置 |
| B 已开放真实流量后发现问题 | 先停止进一步损害并保留新数据，评估前滚修复或经过审批的数据恢复 | 自动回灌维护前 dump，丢弃开放后用户请求、充值或账单 |

DB 恢复必须显式核对数据库目标和备份 ID，在已演练的恢复流程中完成；不对共享 PG 集群执行全局清库，不重启 PG 来替代正确恢复。`pg_restore` 只恢复归档中包含的数据，不能恢复开放后才产生的写入；参考 [PostgreSQL 16 pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html)。

## 9. 你的操作与下一步审批

- 我负责：补齐有限的维护入口/构建记录修正、测试、整理只读预检命令、冻结并提交、按批准范围 push/build/upload、现场观察和汇报。
- 你负责批准：两段维护安排、管理员只读检查、安装和初始启动、数据库备份/升级/必要恢复范围、配置和目录应用；需要 sudo 的命令由你执行。
- 本轮先审核这套顺序。**现在无需执行本文命令**。准备项完成后，会给一份填好实际路径、release ID、文件 SHA、备份位置的短命令清单；管理员数据库入口未做好前不约“直接运行”第二段。
- 全部上线结束后再更新 Babel 工作目录说明、生产 active release、配置前后值/目录 SHA、迁移结果、备份位置和后续回滚边界；不把本地 commit 或编译成功写成生产已完成。
