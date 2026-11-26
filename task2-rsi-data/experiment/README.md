# Dr.Spider 十题人工编排

[首次提交报告](../../reports/任务2先验知识与人工编排实验.md) · [画布截图与实测证据](../../results/task2/submission/README.md)

本目录保存首次提交的代码快照。课程 Visual 页面在 [web/page.tsx](web/page.tsx)，Spring Boot 的图注册与事件调度在 [spring/](spring/)，Python 节点入口在 [serve_canvas.py](serve_canvas.py)。先验实验运行入口是 [prior_round1.py](prior_round1.py)。实验代码在运行时以 Git 基点和文件 SHA-256 定位，各批的配置、题单和报告保存于证据目录。

| 题号 | 节点源码 | 课程页面预设 |
|---:|---|---|
| 1 | [v1](projection_canvas.py) · [v2](projection_generalization.py) | `projection`、`projection_v2` |
| 2 | [筛选值核验](format_canvas.py) | `filter_format` |
| 3 | [候选同义配对](synonym_canvas.py) | `filter_synonym` |
| 4 | [编码核验](boolean_canvas.py) · [字段取样](boolean_evidence_canvas.py) | `filter_boolean`、`filter_boolean_evidence` |
| 5 | [缺失明细与计数范围](count_scope_canvas.py) | `count_scope` |
| 6 | [v1](split_output_canvas.py) · [v2](split_output_v2.py) | `split_output`、`split_output_v2` |
| 7 | [v1](top_n_canvas.py) · [v2](top_n_original.py) | `top_n`、`top_n_interactive`、`top_n_original` |
| 8 | [v1](sort_direction_canvas.py) · [v2](sort_direction_v2.py) | `sort_direction`、`sort_meaning_v2` |
| 9 | [筛选列核验](filter_column_canvas.py) | `filter_column` |
| 10 | [筛选条件和统计对象](filter_count_canvas.py) | `filter_count` |

## 课程画布

按[根目录的环境与复现](../../README.md#环境与复现)准备 Dr.Spider 数据和评测器，按[课程工程说明](../README.md#课程-spring-boot)准备课程源码、Maven 设置、Java 及 H2。先使用课程构建脚本初始化本地后端源码副本。前端的课程源码和依赖按[平台演示页说明](../README.md#平台演示页)准备。

在仓库根目录安装画布路由并构建课程节点。其后分别启动 Python worker、课程后端与 Next.js。

```powershell
& .\task2-rsi-data\experiment\build-course.ps1
& .\task2-rsi-data\experiment\install-preview.ps1
```

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .\task2-rsi-data\experiment\serve_canvas.py
```

```powershell
& .\task2-rsi-data\spring-boot\start-course.ps1
```

```powershell
Set-Location .local/platform-preview/rsi-data-platform
npm.cmd run dev -- --hostname 127.0.0.1 --port 3210
```

打开 `http://127.0.0.1:3210/task2-experiment`，选择画布及题面，点击运行。Visual 将图和样本 ID 送到 Spring Boot，由 `rsi-flow` 依序调度 Python 节点。浏览器可以看到执行结果和节点状态。这个版本将新生成的本地追踪写到 `task2-rsi-data/experiment/runs/canvas/`。

## 本地核对与模型实验

从仓库根目录验证节点分支与 SQLite 核对。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s task2-rsi-data/experiment -p 'test_*.py' -v
```

历史运行可直接检查[证据目录](../../results/task2/submission/README.md)。重跑先验批测时，使用当前环境配置的 Thingo 账号，在独立工作副本中按下列顺序验证题单和运行两批模型对照。重跑脚本将响应写入 `runs/task2-prior-round1/`，并把结果追加到该副本中的报告。

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -B -X utf8 .\task2-rsi-data\experiment\prior_round1.py prepare
& $py -B -X utf8 .\task2-rsi-data\experiment\prior_round1.py post
& $py -B -X utf8 .\task2-rsi-data\experiment\prior_round1.py paired
```

两档 Thinking 以请求的 `reasoning_effort=none/high` 表示。报告各节记载了题单、响应复用和接口异常。部分历史统计入口引用当时本地的证据路径，查看这些结果可使用提交目录里的原始评分和汇总。
