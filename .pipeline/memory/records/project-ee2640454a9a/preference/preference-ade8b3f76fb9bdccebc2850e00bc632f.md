---
authority_role: record
confidence: confirmed
created_at: 2026-08-21T10:53:01Z
dedupe_key: routine_app_release_operator_flow
id: preference-ade8b3f76fb9bdccebc2850e00bc632f
kind: preference
schema_version: '1'
scope:
  ref: project:vsp-sub2api
  type: project
semantic_hash: ade8b3f76fb9bdccebc2850e00bc632fe3460dba596aa077b1c60fe057ce501c
source_refs:
  - locator: routine App release workflow
    ref: conversation:2026-08-21
    type: user_request
supersedes: []
updated_at: 2026-08-21T10:53:01Z
---
# Routine App release operator flow

今后常规 App 更新由 Agent 完成代码修改、相关测试、精确 commit 构建和 push；用户最后只执行一次 `sudo deploy-app-release.sh`。该入口自动完成 inactive slot canary、晋升、最终切流、连接排空、开机 enablement 更新和停止旧 slot，不触碰 PostgreSQL、Redis、allocator 或 Selected Node。
