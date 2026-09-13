# Babel 数据库维护入口

本地实现已完成，尚未安装或执行于生产。只支持当前已审阅的 v0.2.1 → v0.2.4 / SQL 235–237，不是任意数据库运维框架。普通 `vsp-release deploy/rollback` 仍拒绝 SQL 清单差异，Agent sudoers 不增加数据库权限。

## 现在只需做只读预检

在 Genesis 的交互终端运行，不要加本机 sudo：

```sh
python3 /home/heyx/Workspace/VSP/VSP-Sub2API/deploy/native/inspect_babel.py
```

该入口将已提交的 `release_inspect.py` 复制到 Babel 用户工作目录，用完整 SHA-256 验证读入内存的脚本，再通过远端 sudo 执行同一份字节。sudo 密码只在终端输入，不贴到聊天。它不安装、不重启、不修改数据库；SQL 会话强制只读，不输出密码、API Key 或完整环境变量。输出服务状态、DB 绑定/权限/大小、迁移概要、模型列表配置计数、DeepSeek 价卡计数和目录权限。

数据库查询失败会明确标记，不能因此假定数据库为空或已有备份。本入口尚未由本会话连接或上传到生产。`--dry-run` 可只查看传输目标和命令。

## 管理员工作流（安装与预检验收后才执行）

复用 `vsp-sub2api-release.service`、既有发布锁和持久化作业记录。不增加常驻进程；Nginx 增加一个仅回环监听的 19823 维护响应，切换同一个 `sub2api_app` 上游可以覆盖 `.cn`、`.tech` 和 8081 回源。路由检查要求现有三个代理均使用该上游，不接受未审阅的额外路由；不修改其他站点。

一、管理员先做恢复演练（可在维护窗口前、旧应用仍运行时进行）：

```sh
sudo /usr/bin/python3 -I /usr/local/libexec/vsp-sub2api-release/release_schema.py \
  rehearse --database "$DB_NAME"
vsp-release status
```

它生成受保护的逻辑备份，创建仅本作业拥有的临时数据库，恢复数据、执行审阅过的三条 SQL，再测试事务化恢复旧 schema；不启动克隆 App、不向模型服务发请求。临时数据库自动清理，失败也只清理本作业克隆，不停止生产 App。成功证明绑定数据库身份、迁移记账和本次 SQL 策略，24 小时内有效；这不替代新版 App 的功能验收。

二、在已选定窗口暂存升级（A 过渡版须已通过首次启动验收）：

```sh
sudo /usr/bin/python3 -I /usr/local/libexec/vsp-sub2api-release/release_schema.py \
  stage "$B_RELEASE_ID" --from-release "$A_RELEASE_ID" --database "$DB_NAME" \
  --maintenance-window --accept-restore --accept-model-allowlist --accept-cache-prefixes
vsp-release status
```

这些变量要根据真实预检、构建包和当前状态填写，不使用源码短 hash 代替 release ID。三个确认项分别确认数据库恢复范围、235 的模型准入语义，以及下面缓存命名空间仅属于本 App。

暂存过程：核对版本/精确 SQL 哈希/恢复演练/资源 → 维护响应并排空旧 Nginx 请求 → 暂停 worker、停止 App、确认没有其他数据库连接或未完成图像批任务 → 备份 DB、缓存和共享文件 → 启动 B 执行官方迁移 runner → 验证新 schema/记账 → **停在 `schema_ready`，公网仍维护，worker 尚未启用**。

三、通过受控本地访问验收 B 后，由管理员明确选择：

```sh
# 确认放量
sudo /usr/bin/python3 -I /usr/local/libexec/vsp-sub2api-release/release_schema.py \
  activate "$JOB_ID" --maintenance-window

# 或者在尚未放量时取消并恢复 A
sudo /usr/bin/python3 -I /usr/local/libexec/vsp-sub2api-release/release_schema.py \
  abort "$JOB_ID" --maintenance-window --accept-restore
```

`queued` 不是成功；`schema_ready` 是等待人工验收，不是已开放服务。确认放量后才建立 B 的 schema 基线、启用 worker 并切入口；旧 v0.2.1 不登记为普通热回滚目标。之后同 schema 发布沿用普通蓝绿流程。

## 恢复边界

- 在候选可能修改数据库前失败，不回灌 DB；尽量恢复旧入口，不为等待无关 Nginx 长连接而重启健康旧 App。
- 候选开始迁移后、开放之前失败：保持维护，停止 App，校验数据库身份和备份 SHA；使用 `pg_restore --clean --if-exists --single-transaction` 恢复同一个数据库，核对表集合、行数和迁移记账，再恢复缓存/文件与 A。生产恢复不执行 DROP DATABASE 或集群清理。
- 恢复旧库后、启用旧 worker/入口前写入独立持久化边界；进程中断后只继续恢复旧服务，不会再回灌数据库、覆盖刚恢复服务后的新写入。
- 启用新 worker/开放 B 前同样写入不可回灌边界；此后失败保留数据库，尝试关入口/暂停 worker并报告 `recovery_failed`，不自动丢弃新用户数据。恢复无法核实时不报告成功。
- 不重启 PostgreSQL、Redis、general proxy、cloudflared；保留受保护 PID，并将快照跨执行进程校验。审批期间不要修改 App env 或 API Nginx 路由；变化会阻止继续。

## 数据与权限

备份目录固定 `/var/backups/vsp-sub2api-schema/<job>/`，父目录/作业目录 root-only，凭据与备份清单 0600，不出服务器。共享 App 数据完整拷贝，恢复在私有目录组装后原子替换；不沿用户软链接写入其他路径，失败现场目录保留。配置快照供审计，脚本不自动覆盖被其他操作更改的 env/Nginx 文件。

Redis 仅快照/恢复已审阅的 `apikey:auth:*`、`billing:balance:*`、`billing:sub:*`、`sched:*` 和 `sub2api:dashboard:stats:v1`，保留原 TTL；不执行 FLUSHDB/FLUSHALL，其他服务键和图像任务队列不变。必须确认命名空间所有权。此恢复与冻结写入后的 DB 快照配对，不是任意时间点的缓存清理命令。

本工具假定已冻结其他逻辑写入者；受控验收写入可随取消被恢复掉。它不是对抗并发数据库管理员的隔离系统，也不提供磁盘损毁或整机故障后的异地灾备。价格、BaseURL 和静态目录发布仍分别审阅/记录，不等于数据库维护命令自动替你完成。

执行服务的 start/stop 总超时提高到一小时，以容纳备份和恢复；各步骤仍有自己的超时与空间限制。普通发布的步骤和权限不变。第一条只读预检不启动此执行服务。

## 本地验证

```sh
PYTHONDONTWRITEBYTECODE=1 python3 deploy/tests/schema-release-test.py
PYTHONDONTWRITEBYTECODE=1 bash deploy/native/verify.sh
PYTHONDONTWRITEBYTECODE=1 python3 deploy/tests/release-nginx-test.py
```

包含故障矩阵、开放/恢复边界、精确 SQL 策略、凭据保密、脚本校验、文件软链接保护，以及真实隔离 PostgreSQL / Redis / Nginx 演练。生产数据库的实际权限和数据恢复尚待管理员预检与 `rehearse` 验证，不以本地测试冒充生产已通过。
