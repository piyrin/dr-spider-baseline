'use client';

import VisualDiagram, { type ViewState, type VisualCanvasConfig, type VisualDiagramHandle,
  type VisualElementProps } from '@horsecoder/visual-core';
import { useEffect, useRef, useState } from 'react';
import { flowRunFacade } from '@/src/flows/com.horsecoder.common.whuTalent.dataTesting.core/Run';
import { courseCases } from './case-options';
import QueryResult, { type QueryScore } from './QueryResult';
import styles from './course-cases.module.css';

type Side = 'pre' | 'post';
type CaseView = ViewState & { title: string; samples: Record<Side, { id: string; question: string }> };
type CourseResult = {
  run_id: string;
  course_flow_id: string;
  score: QueryScore;
  steps: { id: string; output: unknown }[];
};

function NodeCard({ element }: VisualElementProps) {
  return <div className={styles.node}>{element.state.name}</div>;
}

const config: VisualCanvasConfig = {
  elementConfig: { components: { 'task2-card': { component: NodeCard, minSize: { width: 210, height: 56 } } } },
  linkConfig: { components: { 'task2-line': { hasArrow: true, showName: false } } },
  toolbarConfig: [],
  globalConfig: { gridSize: 25 },
};
const columnGap = 262;
const rowGap = 126;

export default function CourseCases({ initialCase }: { initialCase: string }) {
  const diagram = useRef<VisualDiagramHandle>(null);
  const surface = useRef<HTMLDivElement>(null);
  const [caseId, setCaseId] = useState(initialCase);
  const [view, setView] = useState<CaseView>();
  const [side, setSide] = useState<Side>('post');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<CourseResult>();
  const [columns, setColumns] = useState(1);

  useEffect(() => {
    const canvas = surface.current;
    if (!canvas) return;
    const resize = new ResizeObserver(([entry]) => {
      setColumns(Math.max(1, Math.min(3, Math.floor((entry.contentRect.width - 60) / columnGap))));
    });
    resize.observe(canvas);
    return () => resize.disconnect();
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    setView(undefined);
    setResult(undefined);
    setError('');
    fetch(`/task2-cases/${caseId}.json`, { signal: abort.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`无法加载 ${caseId}（HTTP ${response.status}）`);
        const loaded = await response.json() as CaseView;
        if (abort.signal.aborted) return;
        setView(loaded);
      })
      .catch(failure => { if (!abort.signal.aborted) setError(String(failure)); });
    return () => abort.abort();
  }, [caseId]);

  useEffect(() => {
    if (!view) return;
    diagram.current?.setView({ ...view, elements: view.elements.map((element, index) => {
      const row = Math.floor(index / columns);
      const cell = index % columns;
      const column = row % 2 ? columns - cell - 1 : cell;
      return { ...element, x: 76 + column * columnGap, y: 58 + row * rowGap };
    }) });
  }, [columns, view]);

  async function run() {
    const displayed = diagram.current?.getView();
    if (!displayed || !view) return;
    setRunning(true);
    setError('');
    setResult(undefined);
    try {
      const structure = JSON.stringify({ ...displayed, id: view.id, sample_id: view.samples[side].id });
      const response = await flowRunFacade({ structure });
      setResult(JSON.parse(response.result) as CourseResult);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setRunning(false);
    }
  }

  const rows = Math.ceil((view?.elements.length ?? 3) / columns);
  return <main className={styles.page}>
    <header>
      <div className={styles.heading}><h1>Dr.Spider 十题验收</h1><a href="/task2-experiment">编排实验工作台</a></div>
      <div className={styles.controls}>
        <label>案例 <select aria-label="案例" value={caseId} disabled={running} onChange={event => setCaseId(event.target.value)}>
          {courseCases.map(item => <option key={item.id} value={item.id}>{item.id} · {item.title}</option>)}
        </select></label>
        <label>题面 <select aria-label="题面" value={side} disabled={running} onChange={event => {
          setSide(event.target.value as Side);
          setResult(undefined);
          setError('');
        }}>
          <option value="pre">扰动前（pre）</option><option value="post">扰动后（post）</option>
        </select></label>
        <button type="button" onClick={run} disabled={!view || running}>运行</button>
        <a href={`/task2-cases/${caseId}.json`} download>下载前端 JSON</a>
      </div>
      {view && <p className={styles.question}>{view.samples[side].question}<small>{view.samples[side].id}</small></p>}
    </header>
    <section aria-labelledby="course-case-flow">
      <div className={styles.flowHeading}><h2 id="course-case-flow">编排流程</h2><span>同一编排运行 pre 和 post · Thinking high</span></div>
      <div className={styles.canvas} ref={surface} style={{ height: Math.max(332, 88 + rows * rowGap) }}>
        <VisualDiagram ref={diagram} canvasConfig={config} />
      </div>
    </section>
    {running && <p role="status">课程后端正在执行…</p>}
    {error && <p role="alert">{error}</p>}
    {result && <section className={styles.result} aria-label="运行结果">
      <h2>运行结果</h2>
      <QueryResult score={result.score} output={result.steps.at(-1)?.output} />
      <details><summary>查看节点输出与运行标识</summary>
        <p>课程编排 <code>{result.course_flow_id}</code> · 运行 ID <code>{result.run_id}</code></p>
        <pre>{JSON.stringify(result.steps, null, 2)}</pre>
      </details>
    </section>}
  </main>;
}
