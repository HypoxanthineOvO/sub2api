---
kind: cycle-plan
cycle: native-blue-green-release
status: active
progress: PROGRESS.md
created: 2026-08-21T09:05:00Z
---

# Sub2API GLM 修复与 native blue-green 零停机发布

## 目的

将已完成的 GLM/CN provider 修复可靠保存到 fork，并在已经运行的 native production 栈上建立 app-only blue-green 零停机发布能力，使用该流程把线上 App 从当前 release `f1fdd39e3` 切换到 `vsp/main` 的 `40fb634ad`，完成线上验证。

## 边界

- 本 Cycle 覆盖 fork 推送、app-only canary systemd unit、Nginx upstream 切换、发布与线上验证。
- 官方 PR 跟进保留为后续项，不阻塞本轮生产发布。
- 本轮不是 Docker -> native 数据迁移；native PostgreSQL、Redis、proxy allocator、Selected Node 和五个 Slot 已在线，本轮只切换 App release 与 ingress upstream。
- canary unit 不携带 PostgreSQL/Redis 等数据面 `Requires`；两个 app 实例共享既有数据面。
- Nginx reload 后必须允许存量连接排空；停止旧实例前要考虑服务当前 5 秒 shutdown timeout。
- 保持最小实现：不增加通用验证框架、发布状态机、清单/账本、兼容层或额外抽象；验证仅覆盖阻止错误切流和确认发布成功所必需的检查。
- 切换前必须保留并核对当前线上 release、`19821` 健康、生产 target 和数据面状态；失败时只回到此前 active App release，不触碰数据库和代理控制面。
- blue/green 实例必须各自固定到明确 release 路径（或各自 slot symlink）；不能只共享全局 `/opt/vsp-sub2api/current`，否则旧实例重启时会失去旧版本回滚语义。

## 计划

| ID | 工作项 | 验收标准 |
| --- | --- | --- |
| `M1` | 修复 GLM 测试 404 | 后端按 `api_protocol` 分流并具备配置防呆；提交 `7f32c356f` 已验证 |
| `M2` | 修复 CN 额度/余额刷新 UX | 查询入口可发现且可操作；提交 `40fb634ad` 已完成 |
| `M3` | 提交官方 PR #6009 | CN 刷新入口修复已形成独立上游 PR |
| `M4` | 提交官方 PR #6011 | Anthropic 协议测试路由修复及回归测试已形成独立上游 PR |
| `M5` | 推送 `vsp/main` 到 origin | GitLab origin 可读取 `40fb634ad` |
| `M6` | 盘点并实现 app-only canary unit | 当前线上 App 为 `f1fdd39e3`；canary 监听 `127.0.0.1:19822`，不依赖或控制数据面 unit；两个 slot 分别固定 release |
| `M7` | 改造 Nginx upstream 与切换脚本 | 当前 `api.vsplab.cn` 直接 proxy 到 `19821`；改为 active upstream 片段，可在 19821/19822 间切换，root 下 `nginx -t` 和 reload 成功 |
| `M8` | 在 native 栈上切换 App release | 构建/安装 `40fb634ad`，启动 19822，健康检查通过后切流，旧 App 排空并停止；不迁移或修改 PG/Redis/proxy 数据 |
| `M9` | 完成上线验证 | GLM 测试、CN 查询入口、`/health`、生产 target、关键日志通过；确认当前 release 已变为 `40fb634ad` |
| `M10` | 跟进上游 PR 与同步风险 | 记录 PR #6009/#6011 状态及 fork 落后 upstream 的后续处理建议 |
| `M11` | 收敛常规 App 发布入口 | Agent 完成测试、构建和 push 后，用户用一条 sudo 命令自动完成 blue-green canary、晋升、切流、排空与停旧 slot |

## 验证入口

- Git：`git status --short --branch`、`git log`、远端 ref 查询。
- 后端：相关 service package 单元测试及定向回归测试。
- Native：systemd unit 状态、两个 app 端口健康检查、发布脚本 dry-run/检查模式。
- Nginx：root 下 `nginx -t`、reload、切换前后请求与长连接排空观察；先统一 `sites-enabled`/`sites-available` 的证书与配置来源。
- 线上：管理端 GLM provider 测试、CN provider 额度查询、journal 无 panic/重启循环。

## 历史基线（VSPi 2026-08-20）

- native production 已成功接管 `127.0.0.1:19821`，最终 state 为 `LIVE`；snapshot 为 `/var/backups/vsp-sub2api/20260820T220418`。
- 当次切换验证过：`vsp-sub2api-production.target` active/enabled、14 个 loopback listener、五个 fresh 且互不重复的 Slot、`/health`、`/v1/models`、pricing、Dashboard、一次真实请求及 usage 写入。
- 当次正式切换曾因 native Slot 上游瞬时 SSL 抖动失败，随后使用未提交的 `deploy/native/resume-production.sh` 成功续跑；该脚本修复了 Redis key 容差、Slot 重试和 Bash EXIT/ERR 回退路径问题。
- 这些历史事实只作为当前线上基线，不授权重跑旧的 data cutover，也不代表 `40fb634ad` 已经在线。

## 前次方案复盘约束

- 前次 `cutover-production.sh` 的问题属于方案与验证缺陷，不归因于执行 Agent：host 使用 SCRAM 后又以无密码 TCP 连接 postgres、Slot 以单次外网 curl 判死、若干 `|| { exit 1; }` 路径可能绕开预期 ERR rollback，导致脚本承诺的自动回退不可靠。
- Redis key 精确相等也不适合作为两个独立运行实例的恢复判据，TTL 自然过期会产生正常漂移。
- 当时的 `bash -n`、dry-run 和 fixture 没有覆盖 sudo 后的真实执行路径、瞬时外网失败和 rollback 分支，不能作为端到端可靠性的证据。
- 本轮 blue-green 不复用或扩展旧 data cutover 状态机；只实现 App slot 启动、local health、Nginx 切流、旧连接排空和明确回切。检查失败必须发生在切流前，切流失败时 active upstream 直接指回旧 slot。
