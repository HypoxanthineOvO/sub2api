---
authority_role: record
confidence: confirmed
created_at: 2026-09-14
dedupe_key: passwordless_database_maintenance
id: decision-passwordless-database-maintenance
kind: decision
schema_version: '1'
scope:
  ref: project:vsp-sub2api
  type: project
source_refs:
  - locator: 用户要求固定脚本维护数据库且只输入一次安装器 sudo
    ref: conversation:2026-09-14
    type: user_request
supersedes: []
updated_at: 2026-09-14
---
# 一次安装、固定入口免密数据库维护

用户批准创建固定数据库维护脚本：用户在自己的远程终端输入一次安装器 sudo 密码，之后 Agent 以 SSH 开发者身份调用固定维护入口，不再每次要求用户复制 SQL/输入密码，也不转回浏览器操作。

沿用 SSH/数据库管理偏好。实现采用独立 root-owned 控制器、限定的无参数 NOPASSWD launcher、明确维护子命令、目标校验、事务、缓存一致性和私有审计；不将应用发布器权限扩大成任意 root shell。具体能力和失败处理见 deploy/dbmaint/README.md。安装未完成前，不声称已具备免密数据库维护能力。
