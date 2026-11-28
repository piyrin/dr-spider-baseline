'use client';

import VisualDiagram, { type LinkState, type ViewState, type VisualCanvasConfig,
  type VisualDiagramHandle, type VisualElementProps } from '@horsecoder/visual-core';
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import styles from './workbench.module.css';

const labels = {
  extract: '字段和值提取', lookup: 'SQLite 查值', plan: '查询规划',
  generate: 'SQL 生成', execute: '执行 SQLite', review: '语义审查',
  literal: '文本值核对', year: '四位年份核对',
  scope_compact: '简短语义约束生成', scope_full: '完整语义约束生成',
  projection_match: '明确字段匹配', projection_match_v2: '明确字段匹配 v2', projection_normalize: '指代归一化',
  projection_recheck: '当前库字段复核', projection_constraint: '输出约束或回退',
  projection_generate: '按输出范围生成 SQL',
  format_extract: '筛选条件提取 Agent', format_exact: 'SQLite 精确匹配',
  format_normalize: '归一化核验 Agent', format_generate: 'SQL 生成 Agent',
  synonym_extract: '同义筛选提取 Agent', synonym_exact: 'SQLite 原值查找',
  synonym_match: '同义配对 Agent', synonym_verify: 'SQLite 库值复核', synonym_generate: '按核验值生成 SQL',
  boolean_extract: '布尔条件提取 Agent', boolean_lookup: 'SQLite 编码核验',
  boolean_generate: '按核验编码生成 SQL',
  evidence_extract: '不确定筛选列提取 Agent', evidence_lookup: 'SQLite 列值取样',
  evidence_generate: '按库值样例生成 SQL',
  count_intent: '统计题意解析 Agent', count_policy: '缺失与零值分支',
  count_policy_v2: '缺失与零值分支 v2', count_sql_check: 'SQL 统计口径核验',
  count_generate: '按统计口径生成 SQL',
  split_intent: '姓名题意解析 Agent', split_fields: 'SQLite 姓名字段核对',
  split_fields_v2: '明确姓名请求与字段核对',
  sql_review_draft: 'SQL 初稿 Agent', sql_review_audit: 'SQL 审查 Agent',
  sql_review_gate: '题面依据与 SQLite 核验', sql_review_confirm: '修订确认 Agent',
  sql_review_execute: '执行最终 SQL',
  split_decide: '多列处理判断 Agent', split_contract: '输出列约束或回退',
  split_generate: '按列约束生成 SQL', split_execute: '执行与返回列检查',
  sort_intent: '排序题意解析 Agent', sort_probe: 'SQLite 排序列核验与取样',
  sort_direction: '替代字段排序判断 Agent', sort_generate: '按排序约束生成 SQL',
  sort_meaning_v2: '字段含义与方向判断 Agent',
  sort_select_v3: '排序要求提取 Agent', sort_verify_v3: 'SQLite 候选列核对',
  sort_finalize_v3: '最终排序方向 Agent',
  sort_execute: '执行 SQLite 查询',
  column_intent: '筛选列解析 Agent', column_probe: 'SQLite 跨列查值',
  column_generate: '按列证据生成 SQL', column_execute: '只读执行 SQLite',
  column_draft_v2: 'SQL 初稿 Agent', column_inspect_v2: 'SQLite 筛选列核验',
  column_revise_v2: '局部修正或条件复核', column_execute_v2: '执行最终 SQL',
  filter_count_intent: '筛选与计数解析 Agent', filter_count_verify: 'SQLite 筛选与统计核验',
  filter_count_generate: '按筛选和计数约束生成 SQL', filter_count_execute: '检查并执行 SQLite',
  top_n_intent: 'Top N 题意解析 Agent', top_n_inspect: 'SQLite 字段与重复核验',
  top_n_policy: '结果单位分支', top_n_generate: '按已确认单位生成 SQL',
  top_n_execute: '执行并核对结果',
  top_n_intent_v3: 'Top N 结果单位与显示解析',
  top_n_inspect_v3: 'SQLite 表列与口径核验 v3',
  top_n_policy_v3: '确认结果单位和并列规则',
  top_n_generate_v3: '按计划生成 SQL 或回退',
  top_n_execute_v3: '执行 Top N 查询 v3',
  top_n_intent_v4: 'Top N 候选规则 Agent',
  top_n_inspect_v4: '核验规则与事件证据',
  top_n_policy_v4: '确定规则或回退',
  top_n_generate_v4: '生成 SQL 或调用基线',
  top_n_execute_v4: '执行 Top N 查询 v4',
};
type Kind = keyof typeof labels;
const allKinds = Object.keys(labels) as Kind[];
type Link = { source: string; target: string };
type Options = { hint?: string; probe?: boolean };
type Graph = { nodes: ({ id: string; kind: Kind } & Options)[]; links: Link[] };
type Saved = { name: string; view: ViewState; options: Record<string, Options> };
type Catalog = { graphs: Record<string, Graph>; examples: { id: string; question: string }[] };
type Step = { id: string; kind: Kind; from: string[]; output: unknown; elapsed_s: number };
type Result = { run_id: string; course_flow_id: string; steps: Step[];
  score: { correct: boolean; status: string }; graph_sha256: string;
  cost?: { model_calls: number; total_tokens: number | null } };
type Ports = { pick: (id: string) => void; send: (id: string) => void;
  receive: (id: string, explicit?: string) => void; source: string; active: string };

const initialView: ViewState = { id: 'task2', elements: [], links: [] };
const savedKey = 'rsi-task2-experiment-graphs-1';
const nodeColors: Record<Kind, string> = { extract: '#345ba0', lookup: '#128266', plan: '#345ba0',
  generate: '#345ba0', execute: '#128266', review: '#965b17', literal: '#128266', year: '#128266',
  scope_compact: '#345ba0', scope_full: '#345ba0',
  projection_match: '#345ba0', projection_match_v2: '#345ba0', projection_normalize: '#345ba0',
  projection_recheck: '#128266', projection_constraint: '#965b17', projection_generate: '#345ba0',
  format_extract: '#345ba0', format_exact: '#128266', format_normalize: '#345ba0', format_generate: '#345ba0',
  synonym_extract: '#345ba0', synonym_exact: '#128266', synonym_match: '#345ba0',
  synonym_verify: '#128266', synonym_generate: '#345ba0',
  boolean_extract: '#345ba0', boolean_lookup: '#128266', boolean_generate: '#345ba0',
  evidence_extract: '#345ba0', evidence_lookup: '#128266', evidence_generate: '#345ba0',
  count_intent: '#345ba0', count_policy: '#128266', count_generate: '#345ba0',
  count_policy_v2: '#128266', count_sql_check: '#128266',
  split_intent: '#345ba0', split_fields: '#128266', split_decide: '#345ba0',
  split_fields_v2: '#128266',
  sql_review_draft: '#345ba0', sql_review_audit: '#345ba0', sql_review_gate: '#128266',
  sql_review_confirm: '#345ba0', sql_review_execute: '#128266',
  split_contract: '#965b17', split_generate: '#345ba0', split_execute: '#128266',
  sort_intent: '#345ba0', sort_probe: '#128266', sort_direction: '#345ba0',
  sort_meaning_v2: '#345ba0',
  sort_select_v3: '#345ba0', sort_verify_v3: '#128266', sort_finalize_v3: '#345ba0',
  sort_generate: '#345ba0', sort_execute: '#128266',
  column_intent: '#345ba0', column_probe: '#128266',
  column_generate: '#345ba0', column_execute: '#128266',
  column_draft_v2: '#345ba0', column_inspect_v2: '#128266',
  column_revise_v2: '#965b17', column_execute_v2: '#128266',
  filter_count_intent: '#345ba0', filter_count_verify: '#128266',
  filter_count_generate: '#345ba0', filter_count_execute: '#128266',
  top_n_intent: '#345ba0', top_n_inspect: '#128266', top_n_policy: '#965b17',
  top_n_generate: '#345ba0', top_n_execute: '#128266',
  top_n_intent_v3: '#345ba0', top_n_inspect_v3: '#128266', top_n_policy_v3: '#965b17',
  top_n_generate_v3: '#128266', top_n_execute_v3: '#128266',
  top_n_intent_v4: '#345ba0', top_n_inspect_v4: '#128266', top_n_policy_v4: '#965b17',
  top_n_generate_v4: '#128266', top_n_execute_v4: '#128266' };
const graphLabels: Record<string, string> = { baseline: '单 Agent 基线', value: '真实库值',
  plan: '输出与关联规划', review: '语义复核', without_values: '查值消融', same_evidence: '同证据单 Agent',
  literal_check: '文本值修正', year_check: '年份修正', guarded_local: '文本与年份修正',
  scope_compact: '简短语义约束与核对', scope_full: '完整语义约束与核对',
  projection: '第 1 题 · 输出字段匹配与回退 v1',
  projection_v2: '第 1 题 · 输出字段匹配与回退 v2',
  filter_format: '第 2 题 · 筛选值精确匹配与归一化',
  filter_synonym: '第 3 题 · 筛选值同义配对',
  filter_boolean: '第 4 题 · 布尔字段编码核验',
  filter_boolean_evidence: '第 4 题 · 不确定筛选列取样第二版',
  count_scope: '第 5 题 · 缺失明细与零值',
  count_scope_v2: '第 5 题 · 缺失明细与零值 v2',
  count_scope_v3: '第 5 题 · 缺失明细与零值 v3',
  split_output: '第 6 题 · 姓名分列与拼接',
  split_output_v2: '第 6 题 · 姓名分列与拼接 v2',
  split_output_v3: '第 6 题 · SQL 生成后审查 v3',
  top_n: '第 7 题 · Top N 批测与回退',
  top_n_interactive: '第 7 题 · Top N 交互澄清',
  top_n_original: '第 7 题 · 原题按姓名和排名',
  top_n_v3: '第 7 题 · 通用 Top N 结果单位 v3',
  top_n_v3_interactive: '第 7 题 · 通用 Top N 澄清 v3',
  top_n_v4: '第 7 题 · Top N 有限规则 v4',
  sort_direction: '第 8 题 · 替代字段排序方向',
  sort_meaning_v2: '第 8 题 · 字段含义与排序方向 v2',
  sort_direction_v3: '第 8 题 · 原文提取与最终方向 v3',
  filter_column: '第 9 题 · 筛选列核验',
  filter_column_v2: '第 9 题 · 初稿筛选列核验与局部修正',
  filter_count: '第 10 题 · 筛选条件与计数对象' };
const splitPositions: Partial<Record<Kind, readonly [number, number]>> = {
  split_intent: [86, 90], split_fields: [275, 90], split_decide: [464, 90],
  split_fields_v2: [275, 90],
  split_contract: [464, 245], split_generate: [275, 245], split_execute: [86, 245],
};
const synonymPositions: Partial<Record<Kind, readonly [number, number]>> = {
  synonym_extract: [75, 90], synonym_exact: [255, 90], synonym_match: [255, 245],
  synonym_verify: [435, 90], synonym_generate: [615, 90], execute: [615, 245],
};
const formatPositions: Partial<Record<Kind, readonly [number, number]>> = {
  format_extract: [88, 96], format_exact: [270, 96], format_normalize: [270, 246],
  format_generate: [468, 96], execute: [663, 96],
};
const projectionPositions: Partial<Record<Kind, readonly [number, number]>> = {
  projection_match: [88, 92], projection_match_v2: [88, 92], projection_normalize: [264, 245],
  projection_recheck: [440, 245], projection_constraint: [440, 92],
  projection_generate: [616, 92], execute: [616, 245],
};
const projectionNotes: Partial<Record<Kind, string>> = {
  projection_match: '题面明确要求姓名且库中只有一个对应字段时，直接核验。',
  projection_match_v2: '明确的名称要求先与当前表列匹配，多字段或表列歧义时保留原生成。',
  projection_normalize: '直接匹配不确定时，把受支持的实体指代转为名称候选。',
  projection_recheck: '用当前 SQLite 表结构核验归一候选，只有唯一名称列才通过。',
  projection_constraint: '采用直接或复核通过的字段。均未确认时回退到原始 SQL 生成。',
  projection_generate: '使用当前题面、表结构及已核实的输出约束生成一次 SQL。',
  format_extract: '从当前题面提取一个明确的文本等值条件、原文值和表列。',
  format_exact: '只读查当前列的原值。命中就跳过归一化。',
  format_normalize: '精确查值未命中时，程序比较归一化结果，唯一同形候选交 Agent 核验。',
  format_generate: '有可信原值时传入查值证据。无匹配、多个匹配或未核验时回到原生成。',
  synonym_extract: '提取题面原文、表列和比较运算符。',
  synonym_exact: '按 SQLite 原值精确比较，命中时跳过同义 Agent。',
  synonym_match: '精确未命中时读取当前列候选。Agent 可选出同一对象，也可拒绝。',
  synonym_verify: '在原表列复核所选库值。核验通过时输出映射。',
  synonym_generate: '有映射时追加到 SQL 提示。精确命中及无法确认时使用原提示。',
  boolean_extract: '读取当侧题面和表结构，输出候选列、状态原文及肯定或否定。',
  boolean_lookup: '先查精确原值。未命中时只读核对字段语义、去重值和存储类型。',
  boolean_generate: '只在核验到编码变化时传入真实库值和类型。精确命中或无法确认时使用原提示。',
  evidence_extract: '从当前题面和表结构独立提取存值形式不确定的候选列。',
  evidence_lookup: '按列查实际去重存值和类型，记录原值命中及未取得证据的情况。',
  evidence_generate: '根据题面、表结构和观察值生成 SQL。证据为空时使用基线提示。',
  count_intent: '判断计数是返回项、筛选条件或两者，并输出表列、比较和题面证据。',
  count_policy: '用当前 SQLite 表结构核验关联。按题意分流到有明细、保留零值或回退。',
  count_policy_v2: '核对单一明细关系和数量上限。口径未明时应用 Dr.Spider 的有明细默认口径。',
  count_sql_check: '读取统计口径和生成 SQL。仅核验已确认的简单连接或全局最值形状。',
  count_generate: '有明确口径时带入已核验关联和统计约束，不确定时使用原生成提示。',
  split_intent: '从当侧题面提取姓名的输出或筛选用途、候选字段和题面原文。',
  split_fields: '核对实际表列，区分单列、同一姓名的多个组成列和回退。',
  split_fields_v2: '题面明确请求某实体的姓名时直接核对唯一表列。其他题面沿用 Agent 候选核验。',
  sql_review_draft: '用题面与当前 schema 生成独立 SQL 初稿。',
  sql_review_audit: '根据题面与 schema 核对初稿，保留或提出一处修订并引用题面依据。',
  sql_review_gate: '核验题面引文、SQL 语句形态与 SQLite 查询计划。',
  sql_review_confirm: '仅对通过核验的提案确认是否解决明确冲突、保留其他语义。',
  sql_review_execute: '执行已确定的最终 SQL，流程结束后才进行离线评分。',
  split_decide: '只在核验出多个组成列时调用。判断分列返回、组合查找、明确合并显示或回退。',
  split_contract: '将经过核验的决策转换为 SQL 生成约束。单列或不确定时沿原生成路径。',
  split_generate: '用当前题面、表结构及可用约束生成一条 SQL。',
  split_execute: '只读执行 SQL，并核对返回列是否符合已经确认的输出约束。',
  sort_intent: '读取当侧题面与 schema，提取排序字段、原方向和匹配类型。',
  sort_probe: '核对当前表列。仅在相似字段分支读取实际值和存储类型。',
  sort_direction: '仅在取得相似字段证据时调用。判断方向同向、反向或回退。',
  sort_meaning_v2: '先根据字段名、表结构与真实值解释列义，再判断排序关系。证据不足时回退。',
  sort_select_v3: '保留题面的排序原文，只提取排序量和候选列。',
  sort_verify_v3: '核对当前 SQLite 字段。相似字段补充实际值。',
  sort_finalize_v3: '直接字段沿用明确的题面方向；相似字段由模型判断一次最终方向。',
  sort_generate: '按核实的列和方向生成 SQL，证据不足时使用基线提示。',
  sort_execute: '只读执行 SQL 并返回查询结果。',
  column_intent: '读取当侧题面和表结构，识别返回项、筛选逻辑与文本条件的候选列。',
  column_probe: '只读比较各候选列的精确命中和归一化命中。',
  column_generate: '结合已核验的列值、字段含义和题面的完整条件生成 SQL。',
  column_execute: '在当前 SQLite 中只读执行 SQL 并返回结果。',
  column_draft_v2: '按当侧题面和 schema 生成基线 SQL 初稿。',
  column_inspect_v2: '定位初稿 WHERE 中的文本等值条件，核验当前列和同表候选的真实库值。',
  column_revise_v2: '证据明确时只换一处列名。有语义歧义时由复核 Agent 选择候选。SQLite 检查通过后采用修订。',
  column_execute_v2: '执行最终 SQL，记录采用修订还是保留初稿。',
  filter_count_intent: '读取当前题面和表结构，输出所有筛选条件和要统计的实体。',
  filter_count_verify: '核对统计对象和筛选列，查库定位唯一赛事及左右手编码。',
  filter_count_generate: '根据当前题面、表结构和已核验的条件与统计对象生成 SQL。',
  filter_count_execute: '检查筛选条件和去重计数，再只读执行查询。',
  top_n_intent: '提取数量、排序列、返回字段、候选结果单位和题面原文。',
  top_n_inspect: '只读核对 SQLite 表列和输出组合重复。',
  top_n_policy: '口径明确时采用组合或选手粒度。口径不明时按预设回退或追问。',
  top_n_generate: '把已确认的结果单位交给 SQL 生成。澄清分支跳过模型调用。',
  top_n_execute: '只读执行，记录结果形状及重复检查。澄清时返回问题。',
  top_n_intent_v3: '分别提取去重键、显示列、排序列、条数、原文证据。',
  top_n_inspect_v3: '确认表列和题面证据，核对结果单位与显示列。',
  top_n_policy_v3: '判定能否按确认的单位执行，并检查截取边界和代表记录并列。',
  top_n_generate_v3: '已核验的简单计划使用程序生成的 SQL，缺证据时调用基线生成。',
  top_n_execute_v3: '只读执行并记录路径，交互模式可回传澄清。',
  top_n_intent_v4: '优先采用明确的按实体、按组合或按记录口径，也可以选择跨事件组合或未知。',
  top_n_inspect_v4: '查证题面、字段和条数。跨事件规则还核对 ID、名称及事件属性是否变化。',
  top_n_policy_v4: '通过核验后检查排序边界。证据不足时自动回退。',
  top_n_generate_v4: '按核验规则生成只读模板 SQL，回退时使用原生成提示。',
  top_n_execute_v4: '执行查询并保留所选规则和执行结果。',
};
const PortContext = createContext<Ports | null>(null);

function AgentNode({ element }: VisualElementProps) {
  const op = useContext(PortContext)!;
  const { id, type } = element.state;
  const kind = type as Kind;
  return <div className={`${styles.node} ${op.active === id ? styles.selected : ''}`} style={{ borderLeftColor: nodeColors[kind] }}>
    <button type="button" className={styles.nodeTitle} onClick={() => op.pick(id)}>{labels[kind]}</button>
    <div className={styles.ports}>
      <button type="button" aria-label={`${id} 输入`} onMouseDown={e => e.stopPropagation()}
        onClick={() => op.receive(id)} onDragOver={e => e.preventDefault()} onDrop={e => {
          e.preventDefault(); e.stopPropagation();
          const source = e.dataTransfer.getData('application/x-rsi-link');
          if (source) op.receive(id, source);
        }}>输入</button>
      <code>{id}</code>
      <button type="button" aria-label={`${id} 输出`} aria-pressed={op.source === id} draggable
        onMouseDown={e => e.stopPropagation()} onClick={() => op.send(id)} onDragStart={e => {
          e.dataTransfer.setData('application/x-rsi-link', id); e.dataTransfer.effectAllowed = 'link';
        }}>输出</button>
    </div>
  </div>;
}

const config: VisualCanvasConfig = {
  elementConfig: { components: Object.fromEntries(allKinds.map(kind => [kind, {
    component: AgentNode, minSize: { width: 152, height: 62 },
  }])) },
  linkConfig: { components: { data: { hasArrow: true, showName: false } } },
  toolbarConfig: [], globalConfig: { gridSize: 24 },
};

function toLink(source: string, target: string): LinkState {
  return { id: `${source}--${target}`, type: 'data', name: '', color: '#537096',
    points: [], fromElementId: source, toElementId: target };
}

function elementKinds(elements: { type: string }[]): Kind[] {
  return elements.map(element => element.type as Kind);
}

function toCanvas(graph: Graph): ViewState {
  const projection = graph.nodes.some(node => node.kind === 'projection_match' || node.kind === 'projection_match_v2');
  const format = graph.nodes.some(node => node.kind === 'format_extract');
  const synonym = graph.nodes.some(node => node.kind === 'synonym_extract');
  const split = graph.nodes.some(node => node.kind === 'split_intent');
  return { ...initialView,
    elements: graph.nodes.map(({ id, kind }, i) => {
      const [x, y] = (split && splitPositions[kind]) || (synonym && synonymPositions[kind]) || (format && formatPositions[kind]) || (projection && projectionPositions[kind])
        || [92 + (i % 4) * 191, 105 + Math.floor(i / 4) * 130];
      return { id, type: kind, name: labels[kind], color: nodeColors[kind], x, y,
        select: false, locked: false };
    }),
    links: graph.links.map(({ source, target }) => toLink(source, target)),
  };
}

export default function Task2Canvas() {
  const diagram = useRef<VisualDiagramHandle>(null);
  const surface = useRef<HTMLDivElement>(null);
  const sequence = useRef(0);
  const [catalog, setCatalog] = useState<Catalog>();
  const [view, setView] = useState(initialView);
  const [presetKinds, setPresetKinds] = useState<Kind[]>([]);
  const [showAllKinds, setShowAllKinds] = useState(false);
  const [nodeSearch, setNodeSearch] = useState('');
  const [saved, setSaved] = useState<Saved[]>([]);
  const [options, setOptions] = useState<Record<string, Options>>({});
  const [sample, setSample] = useState('');
  const [name, setName] = useState('实验流程');
  const [active, pick] = useState('');
  const [source, send] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>();
  const onChange = useCallback((next: ViewState) => setView(next), []);

  const loadGraph = useCallback((graphName: string, graph: Graph) => {
    diagram.current?.setView(toCanvas(graph));
    setPresetKinds(graph.nodes.map(node => node.kind));
    setShowAllKinds(graph.nodes.length === 0);
    setNodeSearch('');
    setOptions(Object.fromEntries(graph.nodes.map(({ id, hint, probe }) => [id, { hint, probe }])));
    setName(graphName); pick(''); send(''); setError('');
  }, []);

  useEffect(() => {
    const cache = window.localStorage.getItem(savedKey);
    if (cache) {
      try { setSaved(JSON.parse(cache)); } catch { setNotice('已保存的浏览器流程读取失败。'); }
    }
    const abort = new AbortController();
    fetch('/api/task2-experiment/catalog', { signal: abort.signal }).then(async response => {
      if (!response.ok) throw new Error('无法获取实验节点与开发题');
      const data: Catalog = await response.json();
      const requested = new URLSearchParams(window.location.search).get('case');
      const key = requested === 'top_n_v4' && data.graphs.top_n_v4 ? 'top_n_v4'
        : requested === 'top_n_v3' && data.graphs.top_n_v3 ? 'top_n_v3'
        : requested === 'top_n_v3_interactive' && data.graphs.top_n_v3_interactive ? 'top_n_v3_interactive'
        : requested === 'top_n_original' && data.graphs.top_n_original ? 'top_n_original'
        : requested === 'top_n_interactive' && data.graphs.top_n_interactive ? 'top_n_interactive'
        : requested === 'top_n' && data.graphs.top_n ? 'top_n'
        : requested === 'filter_count' && data.graphs.filter_count ? 'filter_count'
        : requested === 'sort_direction_v3' && data.graphs.sort_direction_v3 ? 'sort_direction_v3'
        : requested === 'sort_meaning_v2' && data.graphs.sort_meaning_v2 ? 'sort_meaning_v2'
        : requested === 'filter_column_v2' && data.graphs.filter_column_v2 ? 'filter_column_v2'
        : requested === 'filter_column' && data.graphs.filter_column ? 'filter_column'
        : requested === 'sort_direction' && data.graphs.sort_direction ? 'sort_direction'
        : requested === 'split_output_v3' && data.graphs.split_output_v3 ? 'split_output_v3'
        : requested === 'split_output_v2' && data.graphs.split_output_v2 ? 'split_output_v2'
        : requested === 'split_output' && data.graphs.split_output ? 'split_output'
        : requested === 'count_scope_v3' && data.graphs.count_scope_v3 ? 'count_scope_v3'
        : requested === 'count_scope_v2' && data.graphs.count_scope_v2 ? 'count_scope_v2'
        : requested === 'count_scope' && data.graphs.count_scope ? 'count_scope'
        : requested === 'filter_boolean_evidence' && data.graphs.filter_boolean_evidence ? 'filter_boolean_evidence'
        : requested === 'filter_boolean' && data.graphs.filter_boolean ? 'filter_boolean'
        : requested === 'filter_synonym' && data.graphs.filter_synonym ? 'filter_synonym'
        : requested === 'filter_format' && data.graphs.filter_format ? 'filter_format'
        : requested === 'projection_v2' && data.graphs.projection_v2 ? 'projection_v2'
        : requested === 'projection' && data.graphs.projection ? 'projection' : 'value';
      setCatalog(data);
      setSample(key.startsWith('top_n') ? 'SQL_NonDB_number-00054-post'
        : key === 'filter_count' ? 'NLQ_keyword_carrier-00248-post'
        : (key === 'filter_column' || key === 'filter_column_v2') ? 'SQL_DB_text-00048-post'
        : (key === 'sort_direction' || key === 'sort_meaning_v2' || key === 'sort_direction_v3') ? 'DB_DBcontent_equivalence-00304-post'
        : key === 'split_output' || key === 'split_output_v2' || key === 'split_output_v3' ? 'DB_DBcontent_equivalence-00125-post'
        : key === 'count_scope' || key === 'count_scope_v2' || key === 'count_scope_v3' ? 'SQL_comparison-00133-post'
        : (key === 'filter_boolean' || key === 'filter_boolean_evidence') ? 'DB_DBcontent_equivalence-00143-post'
        : key === 'filter_synonym' ? 'NLQ_value_synonym-00162-post'
        : key === 'filter_format' ? 'NLQ_column_value-00205-post'
        : key !== 'value' ? 'NLQ_column_carrier-00499-post' : data.examples[1].id);
      loadGraph(graphLabels[key], data.graphs[key]);
    }).catch(failure => { if (!abort.signal.aborted) setError(String(failure.message)); });
    return () => abort.abort();
  }, [loadGraph]);

  function addNode(kind: Kind, position?: { x: number; y: number }) {
    if (busy || !diagram.current) return;
    const current = diagram.current.getView();
    if (current.elements.length >= 10) { setError('每个流程最多有 10 个节点。'); return; }
    let id: string;
    do { id = `${kind}_${++sequence.current}`; } while (current.elements.some(element => element.id === id));
    const x = 92 + (current.elements.length % 4) * 185;
    const y = 100 + Math.floor(current.elements.length / 4) * 112;
    diagram.current.setView({ ...current, elements: [...current.elements,
      { id, type: kind, name: labels[kind], color: nodeColors[kind],
        x: position?.x ?? x, y: position?.y ?? y, select: false, locked: false }],
    });
    pick(id); setError('');
  }

  function connect(target: string, explicit?: string) {
    const start = explicit ?? source;
    const current = diagram.current?.getView();
    if (busy || !start || start === target || !current) return;
    if (current.links.some(link => link.fromElementId === start && link.toElementId === target)) return;
    diagram.current?.setView({ ...current, links: [...current.links, toLink(start, target)] });
    send(''); setError('');
  }

  function removeNode(id: string) {
    const current = diagram.current?.getView();
    if (!current || busy) return;
    diagram.current?.setView({ ...current, elements: current.elements.filter(node => node.id !== id),
      links: current.links.filter(link => link.fromElementId !== id && link.toElementId !== id) });
    pick(''); send('');
  }

  function saveGraph() {
    const current = diagram.current?.getView();
    if (!current || !name.trim()) return;
    const snapshot: Saved = { name: name.trim(), view: current, options };
    const next = [...saved.filter(item => item.name !== snapshot.name), snapshot];
    window.localStorage.setItem(savedKey, JSON.stringify(next));
    setSaved(next); setNotice(`已保存「${snapshot.name}」`);
  }

  async function run() {
    const current = diagram.current?.getView();
    if (!current || !sample) return;
    const graph: Graph = { nodes: current.elements.map(node => ({ id: node.id,
      kind: node.type as Kind, ...options[node.id] })), links: current.links.map(link => ({
      source: link.fromElementId, target: link.toElementId,
    })) };
    setBusy(true); setError(''); setNotice(''); setResult(undefined);
    try {
      const response = await fetch('/api/task2-experiment/run', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sample_id: sample, graph }),
      });
      const data = await response.json();
      if (!response.ok || !data.run_id) throw new Error(data.message ?? data.error ?? `HTTP ${response.status}`);
      setResult(data); setNotice('课程引擎已完成运行');
    } catch (failure) { setError(failure instanceof Error ? failure.message : '运行失败'); }
    finally { setBusy(false); }
  }

  const selected = view.elements.find(element => element.id === active);
  const example = catalog?.examples.find(item => item.id === sample);
  const currentKinds = [...new Set([...presetKinds, ...elementKinds(view.elements)])];
  const search = nodeSearch.trim().toLowerCase();
  const visibleKinds = showAllKinds
    ? allKinds.filter(kind => labels[kind].toLowerCase().includes(search) || kind.includes(search))
    : currentKinds;

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><a href="/">RSI Data</a><h1>Agent 编排实验</h1></div>
      <button className={styles.primary} onClick={run} disabled={busy || !sample}>
        {busy ? '课程引擎运行中…' : '运行当前流程'}
      </button>
    </header>
    <section className={styles.controls}>
      <label>开发样本<select value={sample} disabled={busy} onChange={e => setSample(e.target.value)}>
        {catalog?.examples.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
      </select></label>
      <label>预设流程<select aria-label="加载预设流程" defaultValue="" disabled={busy} onChange={e => {
        const key = e.target.value; if (key && catalog) loadGraph(graphLabels[key], catalog.graphs[key]);
        e.target.value = '';
      }}><option value="">加载预设…</option>{Object.keys(catalog?.graphs ?? {}).map(key =>
        <option key={key} value={key}>{graphLabels[key]}</option>)}
      </select></label>
      <label>已保存流程<select aria-label="加载已保存流程" defaultValue="" disabled={busy} onChange={e => {
        const item = saved.find(graph => graph.name === e.target.value);
        if (item) {
          diagram.current?.setView(item.view);
          setPresetKinds(elementKinds(item.view.elements));
          setShowAllKinds(item.view.elements.length === 0);
          setNodeSearch('');
          setOptions(item.options); setName(item.name); pick(''); send('');
        }
        e.target.value = '';
      }}><option value="">加载已保存流程…</option>{saved.map(item => <option key={item.name}>{item.name}</option>)}
      </select></label>
      <label>流程名<input value={name} onChange={e => setName(e.target.value)} maxLength={64} /></label>
      <button onClick={saveGraph} disabled={busy || !name.trim()}>保存流程</button>
    </section>
    <p className={styles.question}>{example?.question}</p>
    <div className={styles.workspace}>
      <aside className={styles.palette} aria-label="可用节点">
        <h2>{showAllKinds ? '节点库' : '当前流程节点'}</h2>
        <button type="button" className={styles.paletteToggle} aria-expanded={showAllKinds}
          onClick={() => setShowAllKinds(!showAllKinds)}>
          {showAllKinds ? '返回当前流程' : '查看全部节点'}
        </button>
        {showAllKinds && <input type="search" aria-label="搜索节点" placeholder="搜索节点"
          value={nodeSearch} onChange={e => setNodeSearch(e.target.value)} />}
        <div className={styles.nodeList} aria-label="节点列表">
          {visibleKinds.map(kind => <button key={kind} type="button" draggable
            disabled={busy} onClick={() => addNode(kind)} onDragStart={e => {
              e.dataTransfer.setData('application/x-rsi-kind', kind); e.dataTransfer.effectAllowed = 'copy';
            }}><i aria-hidden="true" style={{ background: nodeColors[kind] }} />{labels[kind]}</button>)}
          {visibleKinds.length === 0 && <p>{showAllKinds ? '未找到匹配节点' : '当前流程暂无节点'}</p>}
        </div>
        <button className={styles.paletteClear} disabled={busy}
          onClick={() => loadGraph('新流程', { nodes: [], links: [] })}>清空画布</button>
      </aside>
      <div className={styles.canvas} ref={surface} aria-label="RSI Visual 画布"
        onDragOver={e => e.preventDefault()} onDrop={e => {
          e.preventDefault(); const kind = e.dataTransfer.getData('application/x-rsi-kind') as Kind;
          const rect = surface.current?.getBoundingClientRect();
          if (!rect || !Object.hasOwn(labels, kind)) return;
          const offset = diagram.current?.getOffset() ?? { x: 0, y: 0 };
          addNode(kind, { x: Math.max(0, e.clientX - rect.left + offset.x - 55),
            y: Math.max(0, e.clientY - rect.top + offset.y - 20) });
        }}>
        <PortContext.Provider value={{ pick, send, receive: connect, source, active }}>
          <VisualDiagram ref={diagram} canvasConfig={config} onChange={onChange} />
        </PortContext.Provider>
      </div>
      <aside className={styles.inspector} aria-label="节点属性与连线">
        <h2>属性和连线</h2>
        {selected ? <>
          <strong>{labels[selected.type as Kind]}</strong>
          {selected.type === 'execute' ? <label className={styles.check}><input type="checkbox"
            checked={options[active]?.probe ?? false} disabled={busy} onChange={e => setOptions({ ...options,
              [active]: { ...options[active], probe: e.target.checked } })} />采集字段类型和值</label>
            : selected.type === 'literal' || selected.type === 'year'
              ? <p>连接执行节点，使用 SQLite 核对已有 SQL。此节点没有模型调用。</p>
              : projectionNotes[selected.type as Kind]
                ? <p>{projectionNotes[selected.type as Kind]}</p>
              : selected.type === 'scope_compact' || selected.type === 'scope_full'
                ? <p>使用固定语义约束和数据库结构，一次生成 SQL。</p>
                : selected.type !== 'lookup' &&
                  <label>节点提示<textarea value={options[active]?.hint ?? ''} maxLength={500} rows={3} disabled={busy}
                    onChange={e => setOptions({ ...options, [active]: { ...options[active], hint: e.target.value } })} /></label>}
          <button disabled={busy} onClick={() => removeNode(active)}>删除节点</button>
        </> : <p>点击节点名称查看属性。</p>}
        <p>{source ? `从 ${source} 连出，选择目标输入端。` : '拖动输出端连接输入端，也可依次点击。'}</p>
        <ul>{view.links.map(link => <li key={link.id}><code>{link.fromElementId} → {link.toElementId}</code>
          <button aria-label={`删除连线 ${link.fromElementId} 到 ${link.toElementId}`} disabled={busy}
            onClick={() => {
              const current = diagram.current?.getView();
              if (current) diagram.current?.setView({ ...current, links: current.links.filter(item => item.id !== link.id) });
            }}>×</button></li>)}</ul>
      </aside>
    </div>
    <div className={styles.status} aria-live="polite" role={error ? 'alert' : 'status'}>{error || notice}</div>
    {result && <section className={styles.results}>
      <h2>运行记录</h2>
      <p>{result.score.correct ? '与参考结果一致' : result.score.status} · {result.run_id}</p>
      {result.cost && <p>模型调用 {result.cost.model_calls} 次 · {result.cost.total_tokens === null
        ? 'API 未返回 token 用量' : `${result.cost.total_tokens.toLocaleString()} token`}</p>}
      <code>{result.course_flow_id}</code>
      {result.steps.map(step => <details key={step.id} open={step.kind === 'execute'}>
        <summary>{labels[step.kind]} · {step.id} · {step.elapsed_s.toFixed(2)} 秒</summary>
        <div>上游节点 {step.from.join('、') || '题面和数据库结构'}</div>
        <pre>{JSON.stringify(step.output, null, 2)}</pre>
      </details>)}
    </section>}
  </main>;
}
