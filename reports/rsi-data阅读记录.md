# rsi-data-visual 工程阅读记录

2026 年 11 月 19 日完成 `ymxiong/rsi-data-visual` 的静态阅读，核对分支 `dev_main` 和提交 `b80f121c3752f5cb2b566983f0ba664c57c9d13c`。包名为 `@horsecoder/visual-core`，版本 `0.3.12`，源码采用 React、TypeScript 和 Redux。包配置的 `start` 入口是 Parcel 的 `demo/index.html`，`build:lib` 调用 Rollup。启动情况待验证。[仓库提交](https://github.com/ymxiong/rsi-data-visual/commit/b80f121c3752f5cb2b566983f0ba664c57c9d13c) · [包配置](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/package.json)

1. `demo/index.html` 加载 `demo/index.tsx`。点击“新增模型”时，`onCreateModel` 构造 `elementState`，把节点 ID、类型、名称和坐标传给 `visualDiagramRef.current.createElement`。[示例页面](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/demo/index.tsx)
2. `src/index.ts` 导出 `App`。`src/App.tsx` 将 `createElement` 转发给内部的 `VisualDiagram`。[导出入口](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/src/index.ts) · [组件入口](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/src/App.tsx)
3. `VisualDiagram` 调用 `buildFromElementState` 组装节点，再向 Redux 派发 `createElement`。组件订阅 `state.canvas.view`，视图变化后可通过 `onChange(viewState)` 通知外部。[画布组件](https://github.com/ymxiong/rsi-data-visual/blob/b80f121c3752f5cb2b566983f0ba664c57c9d13c/src/VisualDiagram/index.tsx)

本次核对的调用链覆盖了新增节点和视图更新。Agent 执行、模型调用与 SQL 执行的项目入口和接口仍待确认。
