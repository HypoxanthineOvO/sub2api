# 固定数据库维护入口

用户批准：以开发者身份 SSH/数据库管理；由用户输入一次 sudo 安装，之后 Agent 调用固定入口免密维护。应用发布器的 sudoers 不变，另设 `/usr/local/bin/vsp-db-maint` → 唯一无参数 root launcher。不是任意 root shell 或任意 SQL 执行器。

## 一次安装

Genesis 已提交源码后运行 `python3 deploy/dbmaint/install_babel.py prepare`，生成并上传小安装包、验证远端 SHA，输出精确安装命令。用户在自己的交互终端执行该命令并输入 Babel sudo 密码。root 校验同一份归档字节，再在私有目录执行安装器。

安装器只创建自己的 root-owned 程序、配置、审计目录及限定 sudoers，检查 DB 的集群标识/名称/OID/owner，并以 heyx 身份执行一次免密 inspect 自检。**安装不改用户角色/额度，不写数据库，不重启服务。** 已有安装不覆盖；失败仅撤销本次新建路径。

## 日常调用：不加 sudo、不输入密码

在 Babel 使用 `vsp-db-maint`；在 Genesis 可运行 `python3 deploy/dbmaint/client.py`，它固定通过 SSH Babel 调用相同入口。

```sh
vsp-db-maint inspect
vsp-db-maint find-users 李宇轩
vsp-db-maint find-accounts 李宇轩
vsp-db-maint user <USER_ID>
vsp-db-maint account <ACCOUNT_ID>
vsp-db-maint user-role <USER_ID> --expect-name 李宇轩 --expect-role user --role admin --reason '用户明确要求设为管理员'
vsp-db-maint usage account <ACCOUNT_ID> --since <ISO_START_WITH_TIMEZONE> --until <ISO_END_WITH_TIMEZONE>
vsp-db-maint usage user <USER_ID> --since <ISO_START_WITH_TIMEZONE> --until <ISO_END_WITH_TIMEZONE>
vsp-db-maint key-limits <KEY_ID> --user-id <USER_ID> --expect-updated-at <INSPECTED_UPDATED_AT> --limit-5h 10 --reason '已批准的限额调整'
vsp-db-maint key-reset-window <KEY_ID> --user-id <USER_ID> --window 5h --expect-start <INSPECTED_WINDOW_START_OR_null> --reason '已批准的窗口清零'
vsp-db-maint audit <REQUEST_ID>
```

所有写操作必须有原因和预期目标信息。角色修改校验 ID/姓名/旧角色，保护最后一个有效管理员；限额修改校验 owner/updated_at；窗口重置校验 owner/原窗口起点，只重置选择的 5h、1d 或 7d。**Key 的 0 限额表示不限额；窗口重置仅重置站内 Key 统计，不会重置厂商套餐额度。** 查李宇轩的历史使用不能先重置窗口或刷新覆盖原始证据。

## 权限、缓存和失败处理

- `heyx` 只被授予固定 `control ""` 的 NOPASSWD；不开放 python、psql、shell、文件路径参数或 SQL 文本。输入严格字段校验，查询值使用显式 PostgreSQL E 字符串转义；列名和动作来自代码白名单。
- 使用本机 postgres 子进程身份与固定 socket，凭据仅在 root 进程内处理；不提高应用 DB 账号权限。读取和写入前核对安装时的数据库绑定。
- 与发布 request.lock 互斥；发布、迁移、恢复未结束时拒绝维护，不趁维护门控阶段写用户数据。
- 修改放在数据库事务内，有超时及目标漂移检查。只删除目标 Key 的认证缓存并向既有 `auth:cache:invalidate` 广播；Key 窗口重置另失效该 Key 的 `apikey:rate:<id>`。不 FLUSHDB、不重启 App、不重置他人额度。
- `/var/lib/vsp-sub2api-db-maint/audit/<request_id>.json` 为 root 私有记录，保存 SSH 操作者、请求原因、前后值和阶段；不保存密码、Key、对话内容。数据库写入只发生一次，同 request_id/同参数重试不会重复提交。
- `complete` 才是完成；`cache_pending` 表示 DB 已提交，复用同 request_id 可只补做缓存；`intent` 可能是提交结果不明，拒绝自动重放。先用 audit 查证，再决定下一步，不能把错误退出一概理解为数据库没改。

## 用量审计口径

`account` 返回安全的上游额度缓存快照及 session window；`user` 返回 Key 的 DB 窗口及 Redis 用量窗口，两者若不一致要明确说明。快照里的 next-reset 减五小时只能在厂商窗口语义和采集时效已确认时使用，不能把猜测当成真实重置时间。

`usage` 按显式的 account/user/key ID、带时区时间范围查询（左闭右开，最多七天），输出用户 ID/姓名、Key ID、IP/UA、模型、次数和 token/费用汇总。查询只使用 usage_logs.created_at，不包含对话文本或 Key 值；结果截断有标记。

- 不同站内 user_id 调用了某上游 account_id，可以证明中转站记录中有其他站内用户使用该上游账号。
- 同一用户的不同 IP/UA 不能证明不同自然人；共享 Key 也不代表发生了网页登录。中转站之外的厂商直接调用不在这些记录里。
- 角色、窗口和账户归属需要先核实唯一目标，不以中文姓名直接批量 UPDATE。

## 验证与待办

17 项新增测试通过，包含真实隔离 PostgreSQL 的角色/限额/窗口修改、身份和最后管理员保护、注入/秘密泄露防护、用量归属、失败/重试边界，以及真实隔离 Redis 的定向缓存删除；合并既有发布回归共 104 项通过。日志位于 dist/validation/db-maint。未对生产数据做测试写入。

2026-09-14 用户已执行一次安装，返回 INSTALLED；随后 Agent 已通过固定入口免密完成 inspect、用户/账号查询及指定时间范围的用量审计。安装没有隐式修改用户或额度。涉及个人身份与实际使用者的操作结果保留在服务器私有审计目录，不写入共享 Git 文档。首版明确支持以上命令；任意 SQL、删库、改数据库权限、修改厂商凭据等不在这个免密入口的权限范围。
