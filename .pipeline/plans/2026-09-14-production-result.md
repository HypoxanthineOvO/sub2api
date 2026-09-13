# Babel v0.2.4 真实上线结果

后续微调已正常免密发布：当前 Green `f6c33441c315-d7d502064cb6`，公开默认 API 端点已返回 .tech，八个客户端默认位置/不推荐标记已发布；旧 Blue 保留为同 schema 回滚目标。详见 `2026-09-14-client-defaults.md`。下文为首次 schema 升级的历史验收记录，BaseURL 待办已由公开展示兼容层解决（数据库原值不改），不再表示页面仍显示 .cn。

## 结论与证据

用户已完成管理员续跑，Agent 随后通过 SSH 做只读验收。**应用和模型目录已上线；公网访问和两个独立配置项尚未验收完成。** 不以回源健康代替公网访问成功。

| 项目 | 验收结果 |
| --- | --- |
| 当前应用 | Blue，release `af8b6ea163e6-1da8e3276114`，v0.2.4，PID 186879 |
| 过渡版首启 | 作业 `602d1f42ba7b4e06ab8387955597cf87` complete |
| 数据库升级/放量 | 作业 `8f9dd6789f214886b8a24c65343e0e71` complete，traffic_opened=true，executor inactive |
| 回源健康 | `127.0.0.1:8081/health` + Host api.vsplab.tech：HTTP 200，X-VSP-Deployment 与当前版本一致 |
| 模型目录 | 8081 `/vsp/models`：HTTP 200，64 条；HTTP 正文和磁盘文件 SHA 均为 `256f507c2bb0ebd07221de7206675ee7daf1ad2ed604c60fbb400bd4b0a79a06` |
| 公开设置 | 回源 settings/public HTTP 200，仍返回 `api_base_url=https://api.vsplab.cn` |
| 公网探针 | Babel 请求 `https://api.vsplab.tech/health` 仍为 HTTP 403 / Server cloudflare，public_access_verified=false |
| 备用槽 | Green inactive / MainPID 0；active.previous=null，是新 schema 基线，不是可热回滚到旧 schema |

PostgreSQL、Redis、general proxy、Nginx、cloudflared 主 PID 分别仍为 912、926、876、989、788，与升级前一致。没有重启这些受保护服务；Nginx 发生的是发布所需的平滑 reload。

## Git 与部署对应关系

- 应用源码：`af8b6ea163e624bb18640b828e6205f5ffa92e65`；正式包保留在 dist/releases。
- 已安装发布器修复：`b71d47f9c09712cd98ea67e8df80b444f536c49c` 中的 release_host.py；它与应用 binary 的提交不同，属于独立维护物料，不伪装成重新构建了 App。
- 全量上线包 SHA `c2c9e5d1ce3c8b3db92cc0920c774e3a96ce211111e9654848517428f7eab63c`；续跑补丁 SHA `310a85d9638b5c229432f2598acf8050f69a5ce3ceab3a8b51e70d9999d1bea0`。
- 续跑前 90 项运维回归通过；本轮仅做生产只读验收和文档归档，没有再改生产配置。

## 备份与回退边界

作业记录的 root 私有备份路径：`/var/backups/vsp-sub2api-schema/8f9dd6789f214886b8a24c65343e0e71`。用户输出及作业状态确认已经过 schema_backup、schema_migrating、schema_ready 再开放；维护工具在这些阶段执行既定备份和 SQL/记账校验。本轮没有读取 root-only 备份内容，且按用户决定没有执行生产恢复演练，不宣称恢复耗时/可恢复性已实测。

新版本已开放真实流量/worker，不能再自动回灌该备份而丢弃新写入，也不能直接启动 v0.2.1 读取已变更 schema。后续同 schema 版本可以走已安装的普通 Agent deploy/rollback 流程；如要跨 schema 降级，必须独立处理数据兼容与新写入。

## 剩余工作

1. Cloudflare：公网自动探针 403 原因与实际浏览器/客户端访问需单独核查；没有修改 WAF。当前 root 配置仅对已知 Cloudflare 403 允许验证真实回源，作业保留明确警告；其他错误和错误版本仍会阻断发布。
2. BaseURL：通过官方后台/API 改为 `https://api.vsplab.tech` 并核对公开设置及复制界面；本轮没有直接 SQL 修改。
3. DeepSeek：已有三条自定义分时价卡不会自动跟随新版默认价格；执行修改前重查官方当前费率及工作日时段，只更新相应配置，不重算历史账单。
4. 用户界面验收：真实登录后确认六类客户端配置、纯复制界面/完整 API Key、欢迎引导不自动弹出。先前本地 UI 验证通过，但本轮未冒用用户凭据做生产登录。

本次上线主体已完成，剩余项目不应混记为已完成，也无需为此重复安装或重复迁移。
