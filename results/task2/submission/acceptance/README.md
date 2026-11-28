# Dr.Spider 课程十题验收

每个编号对应一条 Dr.Spider 数据集案例。每条保留扰动前后的题面、SQL 和 SQLite 评分，课程页面默认加载扰动后题面。

- `frontend/caseN.json` 保存课程 Visual 画布，`elements` 和 `links` 描述节点与连线，`samples` 标识同一案例的两种题面。
- `backend/caseN.json` 保存本项目在课程 `rsi-flow` 中执行的编排，包含流程 ID、`params`、`results`、节点 `reference` 和 `routes`。
- `results/resultN.json` 保存两侧实测的 SQL、返回行、参考结果、运行标识和评分。

2026 年 11 月 28 日从课程页面运行十题的扰动前后两侧，**扰动前 10/10，扰动后 10/10，双侧通过 10/10**。表中行数是各侧实际查询返回行数，20 次均与参考结果等价。[运行索引与版本指纹](verification.json)

| 案例 | 前端画布 | 后端编排 | 逐题结果 | 扰动前 / 后行数 |
|---|---|---|---|---|
| 1 · 输出线索变宽 | [case1.json](frontend/case1.json) | [case1.json](backend/case1.json) | [结果 1](results/result1.json) | 4 / 4 |
| 2 · 筛选值大小写 | [case2.json](frontend/case2.json) | [case2.json](backend/case2.json) | [结果 2](results/result2.json) | 1 / 1 |
| 3 · 同义名称 | [case3.json](frontend/case3.json) | [case3.json](backend/case3.json) | [结果 3](results/result3.json) | 12 / 12 |
| 4 · 布尔字段编码 | [case4.json](frontend/case4.json) | [case4.json](backend/case4.json) | [结果 4](results/result4.json) | 1 / 1 |
| 5 · 明细缺失与零值 | [case5.json](frontend/case5.json) | [case5.json](backend/case5.json) | [结果 5](results/result5.json) | 149 / 21 |
| 6 · 姓名分列 | [case6.json](frontend/case6.json) | [case6.json](backend/case6.json) | [结果 6](results/result6.json) | 1 / 1 |
| 7 · Top N 重复组合 | [case7.json](frontend/case7.json) | [case7.json](backend/case7.json) | [结果 7](results/result7.json) | 3 / 5 |
| 8 · 替代列与排序 | [case8.json](frontend/case8.json) | [case8.json](backend/case8.json) | [结果 8](results/result8.json) | 12 / 12 |
| 9 · 文本属性与关联范围 | [case9.json](frontend/case9.json) | [case9.json](backend/case9.json) | [结果 9](results/result9.json) | 13 / 14 |
| 10 · 条件与计数对象 | [case10.json](frontend/case10.json) | [case10.json](backend/case10.json) | [结果 10](results/result10.json) | 1 / 1 |

## 运行方式

在代码仓库根目录按 `README.md` 准备固定版本的数据和评测器后，运行 `./.venv/Scripts/python.exe ./scripts/verify_course_acceptance.py`，可离线重执行并复核本次归档的 20 条 SQL。

现场生成按根目录 `README.md` 的「首次接入课程前端和后端」安装课程组件并启动课程 Visual、Spring Boot 与 Python 节点服务。打开[课程首页十题验收](http://127.0.0.1:3000/?case=case1)，选中 `case1` 至 `case10`，选择题面后点击「运行」。

浏览器将当前画布序列化为 `structure`，提交给课程的 `/dataTesting-core/api/engine/flow`。`FLOW_CODE_RUN` 进入已编号的 Spring Boot 编排。`rsi-flow` 按后端 JSON 调度 `@Flow` 节点，节点通过本机 Python 服务完成 Agent 调用、数据库核验与 SQL 执行。Python 使用 `gpt-6-sol`，验收请求使用 `reasoning_effort=high`。评分在各侧对应的 SQLite 上按结果等价计算。

逐题结果包含实际 SQL、完整返回行、参考 SQL、课程流程 ID 和运行 ID。本轮记录到 37 次模型调用，服务响应未提供 `system_fingerprint`。数据、评测和源码版本见运行索引。第 3 题扰动后返回 12 行美国航司，第 9 题扰动前返回 13 个符合条件的车型。

## 逐题错误与修复依据

| 案例 | 原错误与人工调整 |
|---|---|
| 1 · 输出线索变宽 | 基线把 ID、姓名和年级一并输出。画布先定位题目要求的人名，再用 SQLite 表结构核对 `Highschooler.name`，把 `grade` 用作筛选。 |
| 2 · 筛选值大小写 | 题面写 `Sky radio`，库内存 `Sky Radio`。先查原值，精确查询未命中后核对归一化候选，生成 SQL 使用库内拼写。 |
| 3 · 同义名称 | `United States` 在 `AIRLINES.Country` 中无精确匹配。画布保留查值、同义匹配和库值复核，同时将人工查证的 `United States → USA` 提供给生成节点。 |
| 4 · 布尔字段编码 | 扰动库的 `ship.is_captured` 用文本 `T`、`F` 编码。字段取样节点把实际类型和取值传给生成节点，捕获条件使用 `T`。 |
| 5 · 明细缺失与零值 | 无语言明细的地区缺少可用于比较的语言条数。画布先判断计数口径，再复核生成 SQL 是否让无明细的主体进入结果。 |
| 6 · 姓名分列 | 原库姓名是单字段，扰动库拆为 `first_name` 和 `last_name`。人工明确出参列，生成后检查题面证据和 SQLite 是否支持分列。 |
| 7 · Top N 重复组合 | 比赛记录里同一选手和排名的组合会重复。核验节点检查事件字段与重行，按不同的姓名与排名组合取 Top N，再按观察到的年龄排序。 |
| 8 · 替代列与排序 | 成立越晚对应存续越短。先核对替代字段含义，再把原题的成立年份降序换算为 `year_of_existence` 升序。 |
| 9 · 文本属性与关联范围 | 完整厂商名在 `FullName`，短码在 `Maker`。画布核对候选列。扰动前补充车型、厂商和重量表的关联关系，先确定已关联的候选记录，再应用厂商或重量条件。 |
| 10 · 条件与计数对象 | WTA Championships 和左手获胜必须同时满足。先核对赛事实际存值和手别编码，再按获胜者去重，避免把多场比赛当作多个人。 |
