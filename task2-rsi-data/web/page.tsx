'use client';

import { useEffect, useState } from 'react';
import styles from './task2.module.css';

type FlowId = 'single-table' | 'multi-agent';
type Runtime = 'python' | 'spring-boot';
type Step = { agent: string; input: string; output: string; model: { returned: string | null } };
type Result = {
  run_id: string;
  runtime?: Runtime;
  question: string;
  steps: Step[];
  sql: string;
  columns: string[];
  rows: (string | number | null)[][];
  matches_reference: boolean | null;
  error: string | null;
};

const endpoint = '/api/engine/flow';
const runtimes: Record<Runtime, string> = { 'spring-boot': '课程 Spring Boot', python: '本地 Python' };
const flows = {
  'single-table': { courseId: 'TASK2_SINGLE_TABLE', name: '单表 Agent', question: '有多少位歌手来自法国？', tables: ['singer'] },
  'multi-agent': { courseId: 'TASK2_MULTI_AGENT', name: '多 Agent 协作', question: '统计每位歌手参加的演唱会数量，包含 0 场。', tables: ['singer', 'singer_in_concert'] },
};

export default function TaskTwo() {
  const [flow, setFlow] = useState<FlowId>('single-table');
  const [runtime, setRuntime] = useState<Runtime>('spring-boot');
  const [question, setQuestion] = useState(flows[flow].question);
  const [results, setResults] = useState<Partial<Record<`${Runtime}:${FlowId}`, Result>>>({});
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const result = results[`${runtime}:${flow}`];

  useEffect(() => {
    const controller = new AbortController();
    fetch(endpoint, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('后端暂时不可用');
        const payload = await response.json();
        const latest = payload.latest as Partial<Record<FlowId, Result>>;
        setResults(Object.fromEntries(Object.entries(latest).map(([id, data]) => [
          `${data.runtime ?? 'python'}:${id}`, data,
        ])));
      })
      .catch(() => { if (!controller.signal.aborted) setError('暂时无法读取运行记录'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setRunning(true);
    setError('');
    try {
      const course = runtime === 'spring-boot';
      const response = await fetch(course ? '/api/task2/course-flow' : endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ flowId: course ? flows[flow].courseId : flow, params: { question: question.trim() } }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '请求失败');
      const data = course ? payload.data?.value?.result : payload.data;
      if (!data) throw new Error('流程未返回结果，请检查后端日志');
      setResults(previous => ({ ...previous, [`${runtime}:${flow}`]: course ? JSON.parse(data) : data }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '请求失败');
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <a href="/">← 编排画布</a>
        <code>SQLite / concert_singer</code>
      </header>
      <div className={styles.content}>
        <h1>数据 Agent 编排</h1>
        <form onSubmit={run} className={styles.form}>
          <div className={styles.switch} aria-label="流程选择" role="group">
            {(Object.keys(flows) as FlowId[]).map(id => (
              <button key={id} type="button" aria-pressed={flow === id} disabled={running} onClick={() => {
                setFlow(id);
                setQuestion(flows[id].question);
                setError('');
              }}>{flows[id].name}</button>
            ))}
          </div>
          <div className={styles.tables} aria-label="可读的数据表">
            {flows[flow].tables.map(table => <code key={table}>{table}</code>)}
          </div>
          <label htmlFor="runtime">执行后端</label>
          <select id="runtime" className={styles.runtime} value={runtime} disabled={running}
            onChange={event => { setRuntime(event.target.value as Runtime); setError(''); }}>
            {(Object.keys(runtimes) as Runtime[]).map(id => <option key={id} value={id}>{runtimes[id]}</option>)}
          </select>
          <label htmlFor="question">查询问题</label>
          <textarea id="question" value={question} onChange={event => setQuestion(event.target.value)}
            maxLength={500} disabled={running} required rows={2} />
          <button className={styles.run} disabled={loading || running || !question.trim()}>
            {running ? '正在运行…' : '运行流程'}
          </button>
          {error && <p role="alert" className={styles.error}>{error}</p>}
        </form>

        <div className={styles.results} aria-live="polite" aria-busy={running}>
          {result ? (
            <>
              <p className={styles.record}>最近一次运行 · {runtimes[runtime]} · {result.question}</p>
              <div className={styles.grid}>
                <section className={styles.panel}>
                  <h2>Agent 交接</h2>
                  {result.steps.map(step => (
                    <details key={step.agent} className={styles.step}>
                      <summary><code>{step.agent}</code><small>{step.model.returned}</small></summary>
                      <div className={styles.stepBody}>
                        <h3>输入</h3><pre>{step.input}</pre>
                        <h3>输出</h3><pre>{step.output}</pre>
                      </div>
                    </details>
                  ))}
                </section>
                <section className={styles.panel}>
                  <h2>SQL 与执行结果</h2>
                  <pre className={styles.sql}>{result.sql}</pre>
                  {result.error ? <p className={styles.error}>SQLite 执行失败 · {result.error}</p> : (
                    <>
                      {result.matches_reference !== null && <p className={result.matches_reference ? styles.pass : styles.error}>
                        {result.matches_reference ? '与参考查询一致' : '与参考查询存在差异'}
                      </p>}
                      <div className={styles.tableWrap}>
                        <table>
                          <thead><tr>{result.columns.map((column, index) => <th key={index} scope="col">{column}</th>)}</tr></thead>
                          <tbody>{result.rows.map((row, rowIndex) => (
                            <tr key={rowIndex}>{row.map((cell, index) => <td key={index}>{cell ?? 'NULL'}</td>)}</tr>
                          ))}</tbody>
                        </table>
                      </div>
                      {result.rows.length === 0 && <p>查询返回 0 行。</p>}
                    </>
                  )}
                  <p className={styles.record}>运行编号 <code>{result.run_id}</code></p>
                </section>
              </div>
            </>
          ) : <p className={styles.record}>{loading ? '正在读取运行记录…' : '运行后显示 Agent 输出、SQL 和查询结果。'}</p>}
        </div>
      </div>
    </main>
  );
}
