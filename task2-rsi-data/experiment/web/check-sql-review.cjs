const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

const { chromium } = require(path.resolve(process.argv[2]));
const output = path.resolve(__dirname, '../../../runs/task2-split-output-v3');
const expectedSteps = ['draft', 'audit', 'gate', 'confirm', 'execute'];
const caseId = 'DB_DBcontent_equivalence-00125';

async function main() {
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1040 } });
    await page.goto('http://localhost:3000/task2-experiment?case=split_output_v3');
    const canvas = page.getByLabel('RSI Visual 画布');
    const edge = page.getByRole('button', { name: '删除连线 audit 到 gate' });
    await edge.waitFor({ timeout: 30000 });
    await edge.click();
    await edge.waitFor({ state: 'detached' });
    await canvas.getByRole('button', { name: 'audit 输出' }).click();
    await canvas.getByRole('button', { name: 'gate 输入' }).click();
    await edge.waitFor();
    const name = '第 6 题 · SQL 生成后审查 v3';
    await page.getByRole('textbox', { name: '流程名' }).fill(name);
    await page.getByRole('button', { name: '保存流程', exact: true }).click();
    await page.getByText(`已保存「${name}」`).waitFor();
    await page.reload();
    await page.getByRole('combobox', { name: '加载已保存流程' }).selectOption({ label: name });
    await edge.waitFor();
    await page.screenshot({ path: path.join(output, 'canvas.png') });
    const evidence = path.join(output, 'browser-results.json');
    let runs = [];
    try {
      runs = JSON.parse(await fs.readFile(evidence, 'utf8'));
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    for (const side of ['post', 'pre']) {
      if (runs.some(run => run.side === side)) continue;
      await page.getByRole('combobox', { name: '开发样本' }).selectOption(`${caseId}-${side}`);
      const pending = page.waitForResponse(response => response.url().endsWith('/api/task2-experiment/run')
        && response.request().method() === 'POST', { timeout: 310000 });
      await page.getByRole('button', { name: '运行当前流程' }).click();
      const response = await pending;
      const data = await response.json();
      assert(response.ok() && data.run_id && data.course_flow_id && data.course_flow, JSON.stringify(data));
      const request = response.request().postDataJSON();
      assert.equal(data.sample_id, request.sample_id);
      assert.equal(data.course_flow.nodes.length, 5);
      assert(data.course_flow.nodes.every(node => node.reference === 'TASK2_CANVAS_EXPERIMENT_STEP'));
      assert.deepEqual(data.steps.map(step => step.id), expectedSteps);
      assert(data.draft_score && data.score);
      await page.getByRole('heading', { name: '运行记录' }).waitFor();
      await page.locator('summary').filter({ hasText: 'SQL 审查 Agent' }).click();
      await page.screenshot({ path: path.join(output, `${side}-result.png`), fullPage: true });
      await fs.writeFile(path.join(output, 'structure-v3.json'), JSON.stringify(request.graph, null, 2));
      runs.push({ side, request, ...data });
      await fs.writeFile(evidence, JSON.stringify(runs, null, 2));
      console.log(side, data.run_id, data.draft_score.status, data.score.status, data.cost);
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
