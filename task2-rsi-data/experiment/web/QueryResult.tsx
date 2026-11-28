import styles from './query-result.module.css';

export type QueryScore = { correct: boolean; status: string; reference_rows: number; prediction_rows: number | null };
type Output = { sql?: string; columns?: string[]; rows?: unknown[][]; row_count?: number; reason?: string };

export default function QueryResult({ score, output }: { score: QueryScore; output: unknown }) {
  const query = output as Output | undefined;
  const verdict = score.correct ? '通过 · 与参考结果一致'
    : score.status === 'mismatch' ? '未通过 · 与参考结果不一致'
    : score.status === 'clarification' ? '未通过 · 流程要求澄清'
    : '未通过 · 未得到可比较的结果';
  return <div className={styles.outcome}>
    <div className={styles.summary} data-correct={score.correct}>
      <strong>{verdict}</strong>
      <span>实际 {score.prediction_rows ?? '—'} 行 · 参考 {score.reference_rows} 行</span>
    </div>
    <p className={styles.note}>判分比较 SQLite 返回内容。参考 SQL 包含 ORDER BY 时也比较行顺序。</p>
    {query?.sql && <><h3>最终 SQL</h3><pre>{query.sql}</pre></>}
    {query?.reason && <p>{query.reason}</p>}
    {query?.columns && query.rows && <>
      <h3>实际查询结果</h3>
      <div className={styles.table}><table>
        <thead><tr>{query.columns.map((column, index) => <th key={index} scope="col">{column}</th>)}</tr></thead>
        <tbody>{query.rows.map((row, index) => <tr key={index}>{row.map((value, cell) =>
          <td key={cell}>{String(value ?? 'NULL')}</td>)}</tr>)}</tbody>
      </table></div>
      {query.rows.length === 0 && <p className={styles.note}>查询返回 0 行。</p>}
      {query.row_count !== undefined && query.row_count > query.rows.length &&
        <p className={styles.note}>预览前 {query.rows.length} 行，共 {query.row_count} 行。</p>}
    </>}
  </div>;
}
