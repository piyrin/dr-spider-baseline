# 任务 2 · RSI Data 单表 Agent 与多 Agent 编排

在课程 Spring Boot 启动后，通过 `/api/engine/flow` 调用 `rsi-flow` 执行两条流程。Java 事件节点调用本地 Python 服务，由 Thingo `gpt-6-sol` 生成 SQL，在 Dr.Spider 的 `concert_singer` SQLite 数据库执行。[课程流程验收记录](../results/task2/course-acceptance-20261120.json)

| 验收点 | 实现 |
| --- | --- |
| 启动课程工程 | Spring Boot 使用 H2 内存库支持应用事务，业务查询使用只读 SQLite。前端演示默认走课程后端，也可切换到 Python 后端。 |
| 单表 Agent | `singer` Agent 接收问题和该表的结构并生成 SQL。查询只可读取 `singer`。[流程定义](spring-boot/flow-task2-single.json) |
| 多 Agent 协作生成 SQL | `singer` 与 `singer_in_concert` 两个表 Agent 分别分析表结构，SQL Agent 接收两份输出，生成跨表查询。SQLite 执行节点回传实际结果。[流程定义](spring-boot/flow-task2-multi.json) |

流程实例可检查每个 Agent 的输入输出、最终 SQL、列和行。SQLite 授权器将生成的查询约束在流程绑定的表。[课程事件节点](spring-boot/Task2AgentNodes.java) · [Agent 与查询实现](flow.py)

## 实测结果

2026 年 11 月 20 日经前端代理向课程引擎发出 6 次复测请求，每条流程各跑两次默认题和一次变体。12 次模型生成均返回 `gpt-6-sol`。查询结果按无序行比较，保留重复次数，6 次均与独立执行的参考 SQL 一致。复测覆盖两条流程和四道固定问题，范围限于一个 SQLite 数据库。[完整复测与早期课程运行记录](../results/task2/course-acceptance-20261120.json)

| 流程 | 输入 | 查询结果 | 复测通过 |
| --- | --- | --- | ---: |
| 单表 | 有多少位歌手来自法国？ | 4 位 | 2/2 |
| 协作 | 统计每位歌手参加的演唱会数量，包含 0 场。 | 6 行，Joe Sharp 为 0 场 | 2/2 |
| 单表 | 年龄大于 50 岁的歌手有多少位？ | 1 位 | 1/1 |
| 协作 | 只返回从未参加过任何演唱会的歌手姓名。 | Joe Sharp | 1/1 |

两次默认协作复测分别生成 `COUNT(DISTINCT concert_ID)` 与 `COUNT(concert_ID)`，在当前数据上结果相同。早期 Python 演示的协作首次执行多输出 `Singer_ID`，与参考结果的列数不同。收紧 SQL Agent 的提示词后，原题复测仅输出歌手姓名和场次数，通过核对。[修正前后记录](../results/task2/python-output-columns.json)

记录包含问题、Agent 的模型输入和输出、生成 SQL、执行结果、模型 ID、参数以及数据库和源码哈希。任务 2 的源码在运行时尚未提交，工作区 Git HEAD 为任务 1 的 `20f0022`，以记录中的源码哈希定位实测版本。API 未提供可核实的模型 digest，生成设置为 `stream=false`，其他参数使用服务端默认值。

## 复现步骤

先完成[根目录的环境与数据准备](../README.md#环境与复现)，配置本地 `.env`。在仓库根目录启动 Python 节点服务。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .\task2-rsi-data\serve.py
```

### 课程 Spring Boot

使用课程组提供的源码和私服 `settings.xml`。实测采用 `rsi-data-spring-boot` 的 `1243c62e72ab7a292480cffa4c4c65bc69d4cc7f` 快照、Java 8u514、Maven 3.9.16 和 H2 1.4.199。仓库提供课程源码的增量文件，以下是脚本读取的本地路径。[构建脚本](spring-boot/build-course.ps1) · [启动脚本](spring-boot/start-course.ps1)

| 路径 | 放置内容 |
| --- | --- |
| `.local/upstream/snapshots/rsi-data-spring-boot/` | 解压后的课程后端源码，包含根 `pom.xml`。构建脚本首次运行时复制到本地构建目录。 |
| `.local/task2-rsi-data/spring-boot/settings.xml` | 课程 Maven 配置，用于下载课程依赖。 |
| `.local/task2-rsi-data/spring-boot/runtime/` | `corretto8/jdk1.8.0_514/`、`apache-maven-3.9.16/` 和 `h2-1.4.199.jar`。 |

在另一终端构建、启动课程服务。演示使用仓库内的 H2 配置。原课程配置的开发 MySQL 在实测环境中连接被拒绝。

```powershell
& .\task2-rsi-data\spring-boot\build-course.ps1
& .\task2-rsi-data\spring-boot\start-course.ps1
```

另开终端，在课程服务上运行默认单表题。协作流程使用 `TASK2_MULTI_AGENT` 和上表的协作默认题。

```powershell
$body = @{ flowId = 'TASK2_SINGLE_TABLE'; params = @{ question = '有多少位歌手来自法国？' } } | ConvertTo-Json -Compress
$payload = Invoke-RestMethod -Uri 'http://127.0.0.1:30845/api/engine/flow' -Method Post `
    -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
$payload.data.value.result | ConvertFrom-Json | Select-Object sql, rows, matches_reference, run_id
```

默认题由服务计算 `matches_reference`。变体的该字段为空，可用验收记录中的参考 SQL 核对。新运行的完整记录写入本地 `runs/task2-rsi-data/`。

### 平台演示页

在可运行的课程前端中安装演示入口。实测用 `rsi-data-platform` 的 `eb4c72dc4fd8949861574603817c0bb3b6c4c989` 快照和 `rsi-data-visual` 的 `b80f121c3752f5cb2b566983f0ba664c57c9d13c` 快照。本机预览副本已完成课程依赖和画布兼容配置。将前端放到 `.local/platform-preview/rsi-data-platform/`，其本地包 `rsi-data-visual` 位于同级目录。安装脚本复制演示页并配置两个 API 代理。[前端安装脚本](install-preview.ps1)

```powershell
& .\task2-rsi-data\install-preview.ps1
Set-Location .\.local\platform-preview\rsi-data-platform
npm.cmd run dev -- --hostname 127.0.0.1 --port 3210
```

打开[本机演示页](http://127.0.0.1:3210/task2)，选择流程并点击「运行流程」。课程服务、Python 服务和前端分别使用本机端口 `30845`、`3211` 和 `3210`。

### 离线检查

准备数据后，在仓库根目录执行以下命令，核对表权限、只读查询、Agent 输出交接和参考结果比较。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s task2-rsi-data -v
```
