---
kind: discussion-summary
cycle: native-blue-green-release
updated: 2026-08-21T09:05:00Z
---

# Discussion Summary

用户要求把此前 GLM 修复、两个官方 PR 和 native blue-green 发布的 Local Plan 接入 Hypo-Workflow；同时把仓库外的 PR worktree 移入主仓库目录，并基于当前真实状态制定后续计划。

已确认的长期约束：项目相关 worktree 应收纳在主仓库目录内；生产发布目标是通过 app-only canary 和 Nginx upstream reload 实现存量连接可排空的 blue-green 切换。

实现偏好：blue-green 采用最小闭环，不演变成复杂验证机器。只保留两个 app 端口、app-only unit、Nginx active 配置入口、切换脚本，以及切流前健康检查和切流后确认；不额外建设通用框架或状态管理体系。

VSPi 历史核对结论：native production 已于 2026-08-20 上线，当前只读现场确认线上 release 为 `f1fdd39e3`、19821 健康、生产数据面 active。本 Cycle 是从 `f1fdd39e3` 到 `40fb634ad` 的 App-only blue-green 更新，不重跑 Docker/native 数据迁移。历史未提交的 `resume-production.sh` 曾用于现场续跑，必须保留；Nginx enabled/available 配置来源及证书路径差异需在改造前统一。

用户明确反馈前一版由助手设计、交给 GLM 执行的重启/切换方案质量不可接受。复盘将其认定为方案与验证责任：复杂状态机没有覆盖真实执行和失败分支，自动回退承诺与 Bash 行为不一致，并包含 PostgreSQL 认证、外网瞬时探测和 Redis TTL 判据问题。本轮不得将故障归因于执行 Agent，也不得继续扩展旧脚本。
