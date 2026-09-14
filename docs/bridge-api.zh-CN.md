# WhatIfStarRail 剧情桥接 API v1

这个可选服务用于让你自己的字幕工具向工作台发送剧情。它与界面共享 SQLite，不执行游戏操作，也不自动调用付费模型。

## 启动

在项目根目录执行：

```powershell
python -m pip install -e ".[bridge]"
$env:WHATIF_BRIDGE_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
whatifstarrail bridge
```

服务固定绑定 `127.0.0.1:8502`；可使用 `--port` 修改端口。令牌至少 24 字符，仅保存在运行终端环境中，不要提交至 Git。自定义数据库可使用 `--database`，路径应与界面的 `ASTRAL_COMPANION_DATABASE` 一致。

访问 [本地接口文档](http://127.0.0.1:8502/docs)，在 Authorize 中填入令牌即可测试。文档与 schema 本身公开，本表中的所有业务接口都要求 `Authorization: Bearer <token>`。服务不启用跨域访问。

## 接口

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | `/v1/health` | 服务与 schema 版本；不是游戏连接状态 |
| GET | `/v1/nodes?q=&offset=0&limit=50` | 按标题、正文、人物检索；每页最多 200 个节点 |
| POST | `/v1/nodes` | 建立手动节点或父节点明确的分支；成功返回 201 |
| POST | `/v1/ingest` | 接收外部字幕，按来源与时间线自动追加 |
| GET | `/v1/branches/{node_id}` | 导出祖先链与对话；不存在返回 404 |
| POST | `/v1/import` | 验证并导入 v1 归档，重新分配全部节点 ID |

请求正文最多 8 MB；单节点最多 24000 字符。未知字段、空人物、格式错误返回 422。相同事件 ID 但正文不同返回 409。

## 推送一条字幕

在设置令牌的同一终端运行：

```powershell
$headers = @{ Authorization = "Bearer $env:WHATIF_BRIDGE_TOKEN" }
$payload = @{
    source = "my-subtitle-tool"
    timeline = "play-session-001"
    event_id = "line-0001"
    title = "列车启程前"
    text = "三月七：你真的决定了吗？"
    cast = "三月七，丹恒"
} | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8502/v1/ingest -Method Post `
    -Headers $headers -ContentType 'application/json; charset=utf-8' `
    -Body ([Text.Encoding]::UTF8.GetBytes($payload))
```

返回 `id` 与 `created`。同一 `source + event_id` 重试时，内容相同会返回原 ID 及 `created: false`，不会增加重复节点。下一句使用新 `event_id` 和相同 `timeline`；切换任务或重新开始时更换 `timeline`。同一个来源的事件 ID 应跨时间线保持唯一。

同一时间线的事件按服务收到请求的顺序追加，发送方应串行提交有先后依赖的台词。相同事件的并发重试仍由 SQLite 事务去重。界面点击「刷新故事库」后即可选择新节点。

## 归档

继续支持旧版本导出的 `{version: 1, nodes: [...], chats: [...]}`。节点必须按父节点先于子节点的顺序排列，所有父节点和对话引用均须存在于归档中。循环、重复 ID、悬空引用与不支持的版本会在写入前被拒绝。

导入不携带密钥、模型连接设置、角色卡或运行器状态。需要迁移整个个人工作区时，应停止界面与桥接服务后备份 SQLite 文件。
