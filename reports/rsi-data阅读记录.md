# rsi-data-visual 工程阅读记录

2026 年 11 月 19 日读取老师后来指定的 `ymxiong/rsi-data-visual`。核对的分支为 `dev_main`，提交为 `b80f121c3752f5cb2b566983f0ba664c57c9d13c`。包名为 `@horsecoder/visual-core`，版本 `0.3.12`，源码采用 React、TypeScript 和 Redux。安装项目依赖后，包配置的 `start` 脚本通过 Parcel 打开 `demo/index.html`，`build:lib` 通过 Rollup 构建。本次完成源码阅读，启动情况待验证。[仓库提交](https://github.com/ymxiong/rsi-data-visual/commit/b80f121c3752f5cb2b566983f0ba664c57c9d13c) · [包配置](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/package.json)

1. `demo/index.html` 加载 `demo/index.tsx`。点击“新增模型”时，`onCreateModel` 构造 `elementState`，把节点 ID、类型、名称和坐标传给 `visualDiagramRef.current.createElement`。[示例页面](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/demo/index.tsx)
2. `src/index.ts` 导出 `App`。`src/App.tsx` 将 `createElement` 转发给内部的 `VisualDiagram`。[导出入口](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/src/index.ts) · [组件入口](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/src/App.tsx)
3. `VisualDiagram` 调用 `buildFromElementState` 组装节点，再向 Redux 派发 `createElement`。组件订阅 `state.canvas.view`，视图变化后可通过 `onChange(viewState)` 通知外部。[画布组件](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/src/VisualDiagram/index.tsx)

这条调用链可用于展示节点、连线和视图状态。接入 Dr.Spider 时，还需确定承载 Agent 执行、模型调用及 SQL 执行的工程入口与接口。实验比较可沿用本次样本标识及单库 EX。[任务1实验报告](任务1实验报告.md)
