# VSP 模型配置目录

`/vsp/models` 是公开配置元数据，不是可用性、路由或授权接口。以 VSPi 仓库 `ops/vsplab/model-catalog.json` 为唯一数据源，保留完整声明及扩展字段，不按 Key、服务在线状态或 `hidden` 标记过滤响应。运行时调用继续由既有网关处理。

## 校验与准备

在本仓库根目录执行（将 `<VSPi>` 换成实际仓库路径）：

```sh
python3 deploy/catalog/catalog.py <VSPi>/ops/vsplab/model-catalog.json
python3 deploy/catalog/catalog.py <VSPi>/ops/vsplab/model-catalog.json --output dist/catalogs
```

源 JSON 必须已提交，但不要求 VSPi 仓库中其他无关文件干净。工具只读源文件和 Git，不联网、不访问数据库、不执行 sudo、不修改生产。

产物目录是 `dist/catalogs/<SHA-256>/`，包含原样复制的 `model-catalog.json` 及记录 source commit、路径、哈希、模型数的 `manifest.json`。同一哈希目录不可覆盖。要检查思考档位修订是否倒退，可加 `--previous <上次目录.json>`；主动恢复旧目录是独立的运维操作，不要伪装成正常升级。

## version 1 契约

- 顶层 `models` 数组中的 `id` 唯一；除 ID 外其余模型字段可选。空值不是“未知”的通用表示，未声明字段应省略。
- 原字段沿用：`name`、`protocol`、`contextWindow`、`maxTokens`、`input`、`reasoning`、`cost`、`effortLevels`、`effortMode`、`defaultEffort`、`effortRevision`、`thinkingLevelMap`、`releasedAt`、`curated`、`hidden`。
- 新增可选 `capabilities: string[]`，使用 VSPi 的现有能力名称，例如 `tool_use`。省略时保留旧推导行为；明确提供时以声明为基准，`input` 继续描述媒体输入。字段只声明能力，不授予工具权限或保证后端有服务。
- `effortRevision` 只管理思考配置修订，不是整个目录的全局版本。VSPi 现在也会保护未收录在本地模型表中的模型，旧修订不能覆盖其已保存的新思考配置。用户 overrides 保留。
- `cost` 使用 USD / 百万 tokens，展示基准不等同于实时账单。DeepSeek 的当前官方价格说明见产品计划中的计费核查记录。
- 接口结构仍为 version 1，新增模型不需要升级结构版本。产物 SHA 和 source commit 提供完整数据身份；当前没有引入全目录持久化版本状态机。
- 校验器拒绝重复 JSON 成员、重复模型 ID、非法数字/日期、错误字段结构和明显凭据字段；保留未知元数据字段。公开前仍需审阅内容，不能把字段检查当成完整秘密扫描。

已有协议新增模型示例：

```json
{
  "id": "new-model",
  "protocol": "openai",
  "contextWindow": 200000,
  "maxTokens": 32000,
  "input": ["text", "image"],
  "capabilities": ["tool_use"]
}
```

流程为：修改唯一目录 → 校验 → 提交 → 准备产物 → 审批并发布 JSON → 客户端刷新。无需添加按模型名判断的代码。新增协议类型时才扩展校验与客户端适配器。

## 发布与回退边界

`nginx-location.conf` 是供审阅的精确 `/vsp/models` 路由片段，不是完整站点配置；不要覆盖 Babel 现有 server block，也不要修改 `/v1/models`。它允许无凭据的跨域 GET、提供 JSON 类型及 300 秒 HTTP 缓存，实际消费者刷新频率仍由客户端控制。

本轮没有发布目录或安装此片段。批准部署时：

1. 核对现有 Nginx 路由、目标文件权限及当前响应哈希，备份现有 JSON 和配置；检查不存在不明软链接或重叠修改。
2. 确认 source commit 已保存到批准的远端，再上传完整的已校验产物，核对源 JSON 和 manifest 的 SHA。目录文件不与应用版本包混用，不需要重编译或重启 App。
3. 在 `/etc/vsp-sub2api/` 同一文件系统准备只读候选 JSON（例如 mode 0644），验证后用原子 rename 替换目标，不能直接向正在服务的文件写入半份数据。此步骤涉及 sudo，由用户批准执行。
4. 只有路由配置发生变化才先 `nginx -t` 再平滑 reload；单纯更新 JSON 无需 reload。
5. 验证实际 HTTP 正文哈希、完整模型数、CORS 和客户端解析，再记为成功。保留旧 JSON；失败时原子恢复旧文件并复核。客户端已有 HTTP 缓存或刷新周期可能延迟观察到更新，不承诺瞬时推送。

## 验证命令

```sh
PYTHONDONTWRITEBYTECODE=1 python3 deploy/tests/model-catalog-test.py
```

测试包含完整数据保留、错误输入、修订倒退、不可变产物及真实私有 Nginx HTTP/CORS/拒绝写入验证。测试服务器和目录自动清理，不使用生产配置。
