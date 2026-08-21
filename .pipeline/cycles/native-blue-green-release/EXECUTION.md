---
kind: cycle-execution
cycle: native-blue-green-release
updated: 2026-08-21T09:05:00Z
---

# Execution

## 2026-08-21 初始化与接续

- 从 Local Plan `plan-46b07bd5-7edd-4b00-9647-80d871216a1b` 接续已有进度。
- 已确认主分支 `vsp/main` 位于 `40fb634ad`，4 个前置工作项完成。
- 将下一项设为 M5：先推送 fork 分支保全本地提交，再进入 blue-green 基础设施实现。
- Hypo-Workflow 初始化完成，Cycle `native-blue-green-release` 的 Plan/Progress ID 校验通过。
- PR worktree 已从仓库外移动到 `.worktrees/sub2api-pr`，分支 `fix/cn-anthropic-protocol-account-test` 和 HEAD `a749673de` 保持不变。
- 远端核验确认 origin 尚无 `vsp/main`；现有 app unit 带数据面 `Requires`；应用 shutdown timeout 为 5 秒。
- VSPi 历史恢复记录补充：2026-08-20 native production 已达到 `LIVE`，当前线上 release 经只读核验为 `f1fdd39e3`，19821 health 正常；本轮目标是 App-only release 切换，不再执行旧的 Docker/native 数据迁移。
- 只读核验发现 `/etc/nginx/sites-enabled/api.vsplab.cn` 直接 `proxy_pass http://127.0.0.1:19821`，且与 `sites-available` 使用不同证书路径；`nginx -t` 需要 root 才能得到有效结果。
- 用户反馈前次重启/切换方案质量不可接受。复盘确认原方案存在确定性的 PostgreSQL 认证错误、把单次外网探测当作生产就绪条件、Bash 失败路径可能绕过 rollback，以及 Redis TTL 场景下过严的 key 相等判断；静态检查和 dry-run 未覆盖这些真实失败。当前 blue-green 设计必须独立且最小，不继承旧状态机。
- commit `08da1720e` 已推送 origin：加入 app-only slot unit、固定 release 的 slot symlink、Nginx upstream active link、切换/排空脚本以及最小验证契约。仓库验证通过；生产 root 安装与流量切换留待下一步。
- 生产 green canary 已在 19822 启动并核验：release `40fb634ad`、`NRestarts=0`、health 正常、journal 无 fatal/panic/error。第一次命令因启动后立即 curl 产生约 1 秒竞态并在改 Nginx 前安全退出；commit `e10b7bbaf` 已将 runbook 改为有界 readiness 重试。下一步仅安装 Nginx upstream 结构，active 仍保持 blue/19821。
- Nginx upstream 安装脚本 `6340913d8` 执行成功；root `nginx -t` 与 reload 通过，active=blue，旧/新 App direct health 和 Nginx HTTPS health 均通过。下一步进入第一次 green canary 切流。
- green canary 切流后 GLM 测试与 CN 额度查询均由用户确认通过，生产真实 `/responses` 与用户 API 持续返回 200。随后切回 blue，将 green 晋升为 active worker 模式，再最终切到 green；19821 排空后停止 legacy App。
- 最终验收：active upstream=green，只有 19822 监听；green active/enabled、零重启，production target active/enabled 并依赖 green；旧 App inactive/disabled。PG、Redis、allocator、Selected Node 保持原 PID/启动时间。切流后未发现 5xx/panic/fatal，并观测到 181 个 HTTP 200；binary hash 与构建产物一致。
