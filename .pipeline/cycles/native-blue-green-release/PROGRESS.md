---
kind: cycle-progress
cycle: native-blue-green-release
plan: PLAN.md
status: active
current: M7
next: M7
updated: 2026-08-21T09:45:00Z
---

# 进度

| ID | 工作项 | 状态 | 证据 | 下一动作 |
| --- | --- | --- | --- | --- |
| `M1` | GLM 测试 404 修复 | `completed` | fork commit `7f32c356f` | 无 |
| `M2` | CN 额度/余额刷新 UX | `completed` | fork commit `40fb634ad` | 无 |
| `M3` | 官方 PR #6009 | `completed` | PR #6009 | 等待上游审阅 |
| `M4` | 官方 PR #6011 | `completed` | commit `a749673de`、PR #6011，service 包单测通过 | 等待上游审阅 |
| `M5` | 推送 `vsp/main` | `completed` | origin `refs/heads/vsp/main` 已指向 `08da1720e`，其中包含目标代码和 blue-green 实现 | 无 |
| `M6` | app-only canary unit | `completed` | green 固定到 `40fb634ad`，19822 health 正常，`NRestarts=0`，canary worker 模式生效，binary hash 与构建产物一致 | 无 |
| `M7` | Nginx upstream 切换 | `in_progress` | commit `08da1720e` 已加入 upstream/active 片段和切换脚本；尚未改写生产 Nginx | root 下安装配置、`nginx -t`、reload |
| `M8` | blue-green 发布 | `pending` | native production 已 LIVE，19821 health 正常；本轮只做 App release 切换 | M6/M7 验证后安装 40fb、启动 19822、切流、排空旧 App |
| `M9` | 上线验证 | `pending` | 历史基线已验证 native 数据面；40fb 尚未验证在线 | 发布后确认 40fb release、GLM/CN UX、health 和 journal |
| `M10` | 上游跟进与同步风险 | `pending` | fork 据先前记录落后 upstream 约 110 commits，需重新 fetch 核验 | 查询 PR 状态和分支差异 |

## 当前阻塞与风险

- 当前线上 native production 已核验：App/PG/Redis/allocator/Selected Node active，`19821/health` 返回 `{"status":"ok"}`，`current -> /opt/vsp-sub2api/releases/f1fdd39e3`。
- Nginx root 下配置测试尚未完成；普通用户运行 `nginx -t` 因证书权限失败，且 `sites-enabled` 与 `sites-available` 存在证书路径差异。
- `backend/cmd/server/main.go:182` 当前 shutdown timeout 已确认为 5 秒；旧实例停止策略必须先在 Nginx 层显式留出连接排空窗口。systemd 的 `TimeoutStopSec=90` 不会延长应用自身窗口。
- 主 worktree 有用户未提交文件 `deploy/native/resume-production.sh`，后续修改必须保留并先确认其用途。
- VSPi 历史记录显示该续跑脚本已在生产现场实际使用但未提交；本 Cycle 不应覆盖或遗失它，是否回合到主脚本需单独评估。
- 仓库级验证已通过：`deploy/native/verify.sh`、autonomous worker 单测、Shell 语法、临时 Nginx upstream 语法；生产安装和真实切流尚未执行。
- 首次 canary 命令的即时 health curl 早于 App 开始监听约 1 秒，fail-fast 在 Nginx 修改前退出；green 随后正常启动。runbook 已加入有界 readiness 重试（commit `e10b7bbaf`）。
