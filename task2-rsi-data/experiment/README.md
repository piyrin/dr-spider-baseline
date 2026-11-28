# Dr.Spider 十题人工编排

[人工编排报告](../../reports/任务2先验知识与人工编排实验.md) · [版本迭代汇总](../../reports/任务2先验知识与人工编排实验.md#版本迭代汇总) · [画布截图与实测证据](../../results/task2/submission/README.md)

本目录保存课程十题验收和历版复测的编排源码。验收入口由课程首页组件和 `FLOW_CODE_RUN` 接入。实验工作台用于编辑画布和运行历版预设。Python 服务执行编排节点，Spring Boot 注册和调度流程。[十题验收页](web/CourseCases.tsx) · [实验工作台](web/page.tsx) · [课程后端接入](spring/) · [Python 节点入口](serve_canvas.py) · [先验实验程序](prior_round1.py)

| 题号 | 节点源码 | 课程页面预设 |
|---:|---|---|
| 1 | [v1](projection_canvas.py) · [v2](projection_generalization.py) | `projection`、`projection_v2` |
| 2 | [筛选值核验](format_canvas.py) | `filter_format` |
| 3 | [候选同义配对](synonym_canvas.py) | `filter_synonym` |
| 4 | [编码核验](boolean_canvas.py) · [字段取样](boolean_evidence_canvas.py) | `filter_boolean`、`filter_boolean_evidence` |
| 5 | [v1](count_scope_canvas.py) · [v2](count_scope_v2.py) · [v3](count_scope_v3.py) | `count_scope`、`count_scope_v2`、`count_scope_v3` |
| 6 | [v1](split_output_canvas.py) · [v2](split_output_v2.py) · [v3](split_output_v3.py) | `split_output`、`split_output_v2`、`split_output_v3` |
| 7 | [v1](top_n_canvas.py) · [v2](top_n_original.py) · [v3](top_n_v3.py) · [v4](top_n_v4.py) | `top_n`、`top_n_interactive`、`top_n_original`、`top_n_v3`、`top_n_v3_interactive`、`top_n_v4` |
| 8 | [v1](sort_direction_canvas.py) · [v2](sort_direction_v2.py) · [v3](sort_direction_v3.py) | `sort_direction`、`sort_meaning_v2`、`sort_direction_v3` |
| 9 | [筛选列核验](filter_column_canvas.py) · [初稿局部修订 v2](filter_column_v2.py) | `filter_column` · `filter_column_v2` |
| 10 | [筛选条件和统计对象](filter_count_canvas.py) | `filter_count` |

## 课程画布

课程 Visual 提交节点、连线和样本 ID。课程默认入口读取当前案例的后端 JSON，由 Spring Boot 使用 `rsi-flow` 调度同机 Python 节点。查询与参考 SQL 在相同的当侧 SQLite 上评测。[十题前后端 JSON 与运行结果](../../results/task2/submission/acceptance/README.md)

各题的画布图、结构、浏览器响应、课程流程 ID、逐节点调用及执行评分见[验收证据目录](../../results/task2/submission/README.md)。Thinking 以请求中的 `reasoning_effort=none/high` 表示，各批结果以其冻结题单和原始运行配置为准。
