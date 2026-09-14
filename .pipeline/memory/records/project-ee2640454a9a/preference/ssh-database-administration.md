---
authority_role: record
confidence: confirmed
created_at: 2026-09-14
dedupe_key: developer_ssh_database_administration
id: preference-ssh-database-administration
kind: preference
schema_version: '1'
scope:
  ref: project:vsp-sub2api
  type: project
source_refs:
  - locator: 用户纠正远程后台管理操作方式
    ref: conversation:2026-09-14
    type: user_request
supersedes: []
updated_at: 2026-09-14
---
# 后台管理与审计默认通过 SSH / 数据库

用户是远程使用者，看不到 Agent 所在机器的浏览器。今后用户要求修改 Sub2API 用户、角色、额度或核查账号用量时，应以开发者身份通过 SSH 检查数据库并执行受控管理操作，不默认模拟人类点击管理后台，也不要求用户在 Agent 本机浏览器登录。

先核对目标唯一身份、实际数据库字段和操作副作用；查询/报告不输出密码、API Key 或完整凭据。写操作限定于用户授权范围，保留必要的操作前后核验。若现有 SSH 用户缺少 sudo 或数据库维护权限，提供可在用户远程终端执行的精确命令，由用户输入 sudo 密码；不索取聊天中的密码，不借用发布器免密入口扩大权限。

这条偏好适用于项目后台管理/数据库审计，不改变已建立的普通应用发布流程。它纠正此前由 Agent 选择的浏览器后台操作方式；没有替代其他项目记忆记录。
