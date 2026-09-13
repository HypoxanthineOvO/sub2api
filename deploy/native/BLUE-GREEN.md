# VSP Sub2API 发布流程

2026-09-14 补充：已在本地加入管理员专用的 235–237 维护入口与只读预检，仍未部署。数据库维护需单独 `rehearse → stage → activate/abort`，不会放宽下文普通发布的迁移门禁。第一步命令与限制见 [SCHEMA-MAINTENANCE.md](SCHEMA-MAINTENANCE.md)。

状态（2026-09-13）：用户已批准将本地实现、清理、测试与文档归入本次维护提交，**尚未安装到 Babel，尚未执行首次切换**。生产源码基线为 `04218bfbf`；提交代码不等于批准生产安装或发布。本文取代旧的同机发布操作说明。

## 已确认的边界

- 生产在 Babel，开发与构建在 Genesis。
- 普通发布入口不需要调用者加 sudo 或输入密码；内部只调用固定的 root 执行器。一次性权限安装由用户批准。
- 普通发布失败应回到已知可用版本，不主动停止健康旧实例，不强断存量请求；不承诺任意应用、主机或数据库故障下零失败请求。
- **旧版首次接入只做一次维护窗口切换**：由用户选择低流量时间，允许短暂停服；失败恢复旧版。不为旧版实现热备用 worker 转换或复杂兼容状态机。
- 首次新版仅加入发布支持，不混入后续 Bug、上游升级和国模/UI 微调。

## 一次性安装与首次启动

以下是待审阅的顺序，不是当前已经执行的操作：

1. 验收本地实现，形成确定的候选提交并推送。
2. 从该提交构建正式应用包；控制器源码和两个 systemd unit 单独交付，不能把包内任意脚本作为 root hook。
3. 用户批准并执行一次 `install-release-control.py --baseline <已有生产产物包>`。它校验现有进程二进制及价格资源，建立 root 管理的版本目录、受限 sudo 入口和 19820 本地健康探针；reload Nginx，但不重启当前 App、数据库或代理。
4. 用户选择维护窗口，执行管理员专用 `release_initial.py <release-id> --maintenance-window`。
5. 首次流程先验证候选启动，再停止旧 App、转移后台任务执行权、切到新版并验证。发生失败则停止候选，启动旧版并恢复入口；窗口内允许短暂中断。
6. 首次成功后旧版停止、文件保留。新版本之间以后全部走普通蓝绿流程。若需要退回最初不支持任务协调的旧版，仍按维护操作处理，不假装它支持普通热回滚。

本地已有历史基线包：`dist/releases/baseline-04218bfbf222-a3cc2054ba98.tar`。它不是新版发布产物，也没有被当作新版本部署。

## 后续日常发布

安装完成后，Agent 在 Genesis 使用普通用户入口：

```bash
./deploy/native/vsp-release build --commit <已提交并推送的完整commit>
./deploy/native/vsp-release upload dist/releases/<release-id>.tar
./deploy/native/vsp-release deploy <release-id>
./deploy/native/vsp-release status
./deploy/native/vsp-release rollback
```

Babel 上对应入口是 `/usr/local/bin/vsp-release`。同属 heyx 且有 Babel SSH 访问的 Agent 可共用；权限按 Unix 账号授权，不只授予某个 Agent 产品。其他账号不自动获得权限。

正式构建要求工作区干净、指定提交等于 `origin/vsp/main` 的远端头；源码隔离导出，临时目录自动清理，不积累 worktree。产物为 Linux amd64 应用、价格资源和 manifest；记录源提交、tree、构建工具版本、迁移文件及文件哈希。校验值证明内容完整性，不代表恶意或错误应用已经过可信审计。

发布按以下顺序执行：

1. 主机级排他锁、固定请求 schema、不可变产物导入与校验。
2. 校验可回退版本、迁移清单和资源余量。
3. 在备用槽位启动、验证应用身份，不先停主实例。
4. 等旧定时任务完成并交接执行权，再切流。
5. 检查实际 Nginx upstream、版本标识和公网入口；等待旧 Nginx worker 的请求结束，覆盖 HTTP/2/SSE 和慢上传。
6. 完成记录与开机启用状态更新，旧进程保留为 worker-gated 热备用，不在成功检查之后再贸然停止它。

新版本间手动回滚不要求坏版本先恢复健康，也不重启已经运行的回滚目标。发布失败与主动回滚使用明确的结果语义；“queued”不是成功，调用端默认等待最终状态。SSH 断开不会取消 Babel 上的 systemd 发布任务。

## 权限与失败处理

- 普通入口内部使用 `sudo -n`；sudoers 只授权 root 所有的无参数 `control` launcher。请求通过有大小限制的 JSON 传递，仅允许 deploy、rollback、status。
- root 执行器、依赖、配置和父目录不可由普通用户替换；应用本身仍以 heyx 运行。
- 不开放任意 unit、shell、路径、环境变量或数据服务重启权限；首次维护入口不在 Agent 免密授权中。
- 定时任务使用单机共享文件锁和 root 管理的 owner 记录；交接先等待旧任务结束，不能双活。手动业务请求和进程自己的日志/队列处理不被当作全局定时任务停掉。该机制不宣称业务层 exactly-once。
- systemd 的独立恢复入口会读取持久化发布记录；无法验证恢复时明确返回 recovery_failed，不掩盖错误、不自动杀掉仍承载请求的普通发布实例。
- 新旧 SQL 迁移清单不同会拦截自动发布，必须另行审阅迁移与恢复方案。
- 旧 Nginx worker 还持有其他站点长连接时，普通发布可能等待或拒绝完成；不会为完成发布而强停它们。

## 当前代码位置

| 文件 | 职责 |
| --- | --- |
| `release_client.py` / `vsp-release` | 普通用户构建、上传、调用和结果等待 |
| `release_core.py` | 包契约、普通发布及一次性维护流程 |
| `release_host.py` | Babel 固定范围操作、身份验证与任务交接 |
| `release_control.py` / `release_runner.py` | 受限请求入口、独立执行与恢复 |
| `release_initial.py` | 管理员专用首次维护窗口启动 |
| `install-release-control.py` | 一次性安装，未在生产执行 |
| `ops/systemd/vsp-sub2api-release.service` | systemd 发布执行器及 ExecStopPost 恢复 |

旧 `build.sh`、`install.sh`、`deploy-app-release.sh`、`switch-app-slot.sh` 和旧免密安装器已从工作区移除，历史仍在 Git 中；不要再使用旧命令绕开新流程。

## 验证与待办

- 本地 Python/结构/故障模拟检查已通过。
- 真实私有 Nginx 测试验证了 HTTP/2 流、慢上传和无效配置；不使用生产端口或真实推理请求。
- Go service / server 两包全量测试及完整 embed 构建已通过。
- 正式构建拒绝未提交工作区的行为已验证；当前未生成正式新版包、未安装权限、未切换 Babel。

剩余步骤是推送候选提交并正式构建、审阅一次性安装操作、用户安排维护窗口并首次启动验收。生产安装和切换仍分别确认；之后再处理后续 Bug、版本升级和功能调整。
