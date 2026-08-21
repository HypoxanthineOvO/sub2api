---
kind: cycle-progress
cycle: native-blue-green-release
plan: PLAN.md
status: active
current: M10
next: M10
updated: 2026-08-21T10:53:01Z
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
| `M7` | Nginx upstream 切换 | `completed` | commit `6340913d8` 安装成功；`nginx -t`/reload 通过，active symlink 指向 blue，HTTPS health 正常 | 无 |
| `M8` | blue-green 发布 | `completed` | green `40fb634ad` 已完成 canary、切回、active worker 晋升和最终切流；19821 排空后旧 App 停止 | 无 |
| `M9` | 上线验证 | `completed` | active=green/19822；GLM 测试和 CN 查询通过；HTTPS health 正常；green 零重启且切流后无 5xx/panic/fatal | 无 |
| `M10` | 上游跟进与同步风险 | `pending` | fork 据先前记录落后 upstream 约 110 commits，需重新 fetch 核验 | 查询 PR 状态和分支差异 |
| `M11` | 常规 App 单 sudo 发布入口 | `completed` | commit `1331e8f0d` 已 push；完整 build 通过且 `source-commit` 与 HEAD 一致；两轮独立失败路径审查通过 | 后续 App 更新复用该入口 |

## 当前阻塞与风险

- 当前线上 native production 已核验：App/PG/Redis/allocator/Selected Node active，`19821/health` 返回 `{"status":"ok"}`，`current -> /opt/vsp-sub2api/releases/f1fdd39e3`。
- Nginx root 下配置测试尚未完成；普通用户运行 `nginx -t` 因证书权限失败，且 `sites-enabled` 与 `sites-available` 存在证书路径差异。
- `backend/cmd/server/main.go:182` 当前 shutdown timeout 已确认为 5 秒；旧实例停止策略必须先在 Nginx 层显式留出连接排空窗口。systemd 的 `TimeoutStopSec=90` 不会延长应用自身窗口。
- 主 worktree 有用户未提交文件 `deploy/native/resume-production.sh`，后续修改必须保留并先确认其用途。
- VSPi 历史记录显示该续跑脚本已在生产现场实际使用但未提交；本 Cycle 不应覆盖或遗失它，是否回合到主脚本需单独评估。
- 仓库级验证已通过：`deploy/native/verify.sh`、autonomous worker 单测、Shell 语法、临时 Nginx upstream 语法；生产安装和真实切流尚未执行。
- 首次 canary 命令的即时 health curl 早于 App 开始监听约 1 秒，fail-fast 在 Nginx 修改前退出；green 随后正常启动。runbook 已加入有界 readiness 重试（commit `e10b7bbaf`）。
- Nginx 安装后现场核验通过：active=blue，两个 App 和 HTTPS health 均正常，green 无重启或错误日志。
- 最终状态：green active/enabled，legacy App inactive/disabled，production target active/enabled 且依赖 green；PG/Redis/allocator/Selected Node 未重启。旧 `f1fdd39e3` 与 blue upstream 仍保留作显式回滚。
- 常规 App 发布已收敛为 `deploy/native/deploy-app-release.sh`：默认 canary soak 15 秒、排空上限 120 秒，超时回切且不强停连接；现有架构下 worker 晋升允许排空窗口内短暂重叠。
