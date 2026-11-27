const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require(path.resolve(process.argv[2]));

const out = path.resolve('runs/task2-top-n-v4');
const samples = ['SQL_NonDB_number-00054-pre', 'SQL_NonDB_number-00054-post',
  'lap-entity-post', 'lap-ambiguity-post'];

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const file = path.join(out, 'browser-results.json');
  let runs = [];
  try {
    try { runs = JSON.parse(await fs.readFile(file, 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    const page = await browser.newPage({ viewport: { width: 1440, height: 1040 } });
    await page.goto('http://127.0.0.1:3000/task2-experiment?case=top_n_v4');
    const presets = page.getByRole('combobox', { name: '加载预设流程' });
    await presets.locator('option[value=top_n_v4]').waitFor({ state: 'attached' });
    await page.getByLabel('RSI Visual 画布').getByRole('button', { name: 'Top N 候选规则 Agent' }).waitFor();
    await page.screenshot({ path: path.join(out, 'canvas.png') });
    for (const sample of samples) {
      if (runs.some(run => run.sample_id === sample)) continue;
      await page.getByRole('combobox', { name: '开发样本' }).selectOption(sample);
      const pending = page.waitForResponse(response => response.url().endsWith('/api/task2-experiment/run')
        && response.request().method() === 'POST', { timeout: 360000 });
      await page.getByRole('button', { name: '运行当前流程' }).click();
      const response = await pending;
      const result = await response.json();
      assert(response.ok() && result.course_flow_id && result.run_id, JSON.stringify(result));
      assert.equal(result.sample_id, sample);
      assert.deepEqual(result.steps.map(node => node.id), ['intent', 'inspect', 'policy', 'generate', 'execute']);
      assert(result.course_flow.nodes.every(node => node.reference === 'TASK2_CANVAS_EXPERIMENT_STEP'));
      assert.notEqual(result.score.status, 'clarification');
      await page.getByRole('heading', { name: '运行记录' }).waitFor();
      runs.push({ request: response.request().postDataJSON(), ...result });
      await fs.writeFile(file, JSON.stringify(runs, null, 2));
      await page.locator('summary').filter({ hasText: '确定规则或回退' }).click();
      await page.screenshot({ path: path.join(out, sample + '.png'), fullPage: true });
      const policy = result.steps[2].output;
      console.log(sample, policy.route, policy.rule, result.score.status, result.run_id);
    }
    assert.equal(runs.length, samples.length);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
