# 星铁开源生态调研与本轮实现

调研日期：2026-09-14。星数来自当日 GitHub API 快照，不是固定排名。筛选优先考虑可运行工具、实际界面和接口文档；搜索结果中的同名或错误匹配项目（例如网络代理内核 mihomo）未纳入。

| 项目 | 星数 | 核实内容 | 对本项目的启发 |
| --- | ---: | --- | --- |
| [March7thAssistant](https://github.com/moesnow/March7thAssistant) | 11,452 | README 界面截图、`app/home_interface.py`、示例配置；GPL-3.0 | 常用任务卡片、独立设置页、设备与运行状态 |
| [StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot) | 4,195 | README 仪表盘、配置与框架说明；GPL-3.0 | UI 与运行器分离、持续运行状态、结构化配置 |
| [star-rail-warp-export](https://github.com/biuuu/star-rail-warp-export) | 1,643 | README 数据读取、导出和多账号流程；MIT | 数据要能导入、验证、保存和恢复，而不只是显示 |
| [StarRailOneDragon](https://github.com/OneDragon-Anything/StarRailOneDragon) | 1,515 | README、`src/one_dragon/base/config/basic_game_config.py`；GPL-3.0 | 分辨率、显示器与窗口模式应当是显式配置 |
| [Fribbels HSR Optimizer](https://github.com/fribbels/hsr-optimizer) | 671 | 实际网站导航、角色与 Import / Save 入口、`docs/guides/en/live-import.md`；MIT | 以人物和数据为中心组织工作台，提供独立接入通道 |
| [StarRailRes](https://github.com/Mar-7th/StarRailRes) | 515 | README 多语言角色与素材索引；AGPL-3.0 | 角色数据采用明确结构，与运行场景分开 |

## 调研判断

这些项目中的大多数解决自动化、养成或记录管理问题。它们提供的跃迁记录接口、Enka 展柜数据和静态角色索引，都不是实时剧情接口，不能直接用来恢复任务现场或人物真实内心。

WhatIfStarRail 应借鉴其产品结构和接入方式，把重点放在「剧情数据进入系统后，如何可靠地记录、选择、修改和继续」。继续堆更多没有状态、没有保存能力的按钮，或者移植与叙事无关的日常自动化功能，都无法解决当前问题。

## 已落地

1. **后台采集服务**：独立线程持有 OCR 生命周期，页面仅观察状态。支持启动、停止、错误状态、帧数、保存条数、延迟和最新识别文本；停止后不提交仍在识别的帧。
2. **可恢复配置**：采样区域、人物、间隔、置信度、模型名称和协议保存在 SQLite。主屏底部字幕与中央对话提供比例预设，仍需预览校准。
3. **剧情桥接接口**：可选 FastAPI 服务，固定 localhost、Bearer 认证、Pydantic 输入契约、8 MB 请求上限、分页查询、时间线自动衔接和原子事件去重。
4. **故事档案**：按标题、人物、正文检索，来源筛选，祖先时间轴，父子节点对照与文本差异，v1 JSON 校验导入。导入使用全新 ID 并在事务内完成，不覆盖旧故事。
5. **角色档案**：内置公开角色概述，可编辑身份、语气与行为边界，添加原创人物；生成时仅传入当前人物或当前在场人物的卡片。
6. **上下文连续性**：当前分支最近 16 个节点内的同角色聊天可以承接到后续节点，兄弟分支仍被隔离。模型支持 Responses 与 Chat Completions 两种协议。
7. **工作台布局**：角色视觉横幅、紧凑状态卡、控制台与快捷开局并列、五个明确工作区。内容使用现有已注明来源的本地素材。

## 接口边界与来源

本轮没有调用上述项目的私有服务，也没有复制它们的 GPL / AGPL 源码或新增第三方美术素材。借鉴的是功能组织与交互方式，实现代码为本仓库独立编写。现有美术来源见 [素材说明](../app/assets/README.md)。

新接口是 **WhatIfStarRail 自己的接入协议**，并不代表已兼容上述工具的原生导出格式。外部工具须显式转换成 `/v1/ingest` 或故事归档 schema。跃迁记录、账号 Cookie、authKey 均不参与本项目的剧情采集。

## 仍需后续验证

真实游戏下不同分辨率、HDR、动态背景、字幕速度和窗口遮挡的识别效果；实际模型的角色还原和长篇连续性；游戏内悬浮窗、按游戏窗口跟随采集、自动人物识别与流式模型输出仍未实现。后台线程随 Python 服务退出而停止，不是操作系统常驻服务。

本轮检查使用模拟字幕、离线 / mocked 模型、API TestClient 和真实浏览器 UI，不把这些结果宣传为真实游戏实测。
