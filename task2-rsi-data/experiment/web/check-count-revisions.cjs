const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

const { chromium } = require(path.resolve(process.argv[2]));
const root = path.resolve(__dirname, '../../..');
const origin = 'http://127.0.0.1:3000';
const sample = 'SQL_comparison-00133';

function shape(graph) {
  return {
    nodes: graph.nodes.map(({ id, kind }) => ({ id, kind })).sort((a, b) => a.id.localeCompare(b.id)),
    links: [...graph.links].sort((a, b) => (a.source + a.target).localeCompare(b.source + b.target)),
  };
}

async function verify(browser, version) {
  const dir = path.join(root, 'runs', 'task2-count-scope-' + version);
  const config = JSON.parse(await fs.readFile(path.join(dir, 'config.json'), 'utf8'));
  const page = await browser.newPage({ viewport: { width: 1440, height: 1040 } });
  try {
    await page.route('**/*', route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort());
    await page.goto(origin + '/task2-experiment?case=count_scope_' + version);
    const canvas = page.getByLabel('RSI Visual 画布');
    await canvas.getByRole('button', { name: '缺失与零值分支 v2', exact: true }).waitFor({ timeout: 30000 });
    const file = path.join(dir, 'visual-results.json');
    let entries = [];
    try {
      entries = JSON.parse(await fs.readFile(file, 'utf8'));
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    if (version === 'v3') {
      await canvas.getByRole('button', { name: 'SQL 统计口径核验', exact: true }).waitFor({ timeout: 30000 });
    }
    await page.screenshot({ path: path.join(dir, 'canvas.png') });
    for (const side of ['post', 'pre']) {
      if (entries.some(entry => entry.side === side)) continue;
      await page.getByRole('combobox', { name: '开发样本' }).selectOption(sample + '-' + side);
      const pending = page.waitForResponse(response => response.url().endsWith('/api/task2-experiment/run')
        && response.request().method() === 'POST', { timeout: 310000 });
      await page.getByRole('button', { name: '运行当前流程' }).click();
      const response = await pending;
      const data = await response.json();
      assert(response.ok() && data.run_id && data.course_flow_id, JSON.stringify(data));
      const request = response.request().postDataJSON();
      assert.deepEqual(shape(request.graph), shape(config.graph));
      assert.equal(data.sample_id, sample + '-' + side);
      await page.getByRole('heading', { name: '运行记录' }).waitFor();
      await page.screenshot({ path: path.join(dir, side + '-visual.png'), fullPage: true });
      entries.push({ version, side, request, ...data });
      await fs.writeFile(file, JSON.stringify(entries, null, 2), 'utf8');
      console.log(version, side, data.run_id, data.score.status);
    }
    assert.equal(entries.length, 2);
  } finally {
    await page.close();
  }
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    await verify(browser, 'v2');
    await verify(browser, 'v3');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
