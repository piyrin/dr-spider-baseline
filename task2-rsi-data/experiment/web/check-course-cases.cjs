const assert = require('node:assert/strict');
const { readFile, writeFile, mkdir } = require('node:fs/promises');
const path = require('node:path');

const { chromium } = require(path.resolve(process.argv[2]));
const base = process.env.TASK2_COURSE_URL || 'http://127.0.0.1:3000';
const deliverables = path.resolve('results/task2/submission/acceptance');
const output = path.resolve('.local/task2-experiment/course-acceptance');
const caseIds = process.argv.slice(3);
const selected = caseIds.length ? caseIds : Array.from({ length: 10 }, (_, index) => `case${index + 1}`);
const load = async file => JSON.parse(await readFile(file, 'utf8'));

async function runSide(browser, caseId, side) {
  const frontend = await load(path.join(deliverables, 'frontend', `${caseId}.json`));
  const backend = await load(path.join(deliverables, 'backend', `${caseId}.json`));
  const page = await browser.newPage({ viewport: { width: 1350, height: 1020 } });
  try {
    await page.goto(`${base}/?case=${caseId}`);
    await page.getByText(frontend.samples.post.question, { exact: false }).first().waitFor();
    await page.getByRole('combobox', { name: '题面' }).selectOption(side);
    const pending = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/dataTesting-core/api/engine/flow'
      && response.request().method() === 'POST', { timeout: 560000 });
    await page.getByRole('button', { name: '运行', exact: true }).click();
    const response = await pending;
    const payload = await response.json();
    assert(response.ok() && payload.result, JSON.stringify(payload));
    const request = response.request().postDataJSON();
    assert.equal(request.flowId, '@com.horsecoder.common.whuTalent.dataTesting.core/FLOW_RUN');
    const result = JSON.parse(payload.data.value.result);
    assert.equal(result.sample_id, frontend.samples[side].id);
    assert.deepEqual(result.course_flow, backend);
    assert.deepEqual(result.steps.map(step => step.id), backend.nodes.map(node => node.title));
    await page.getByRole('heading', { name: '运行结果' }).waitFor();
    const evidence = { case_id: caseId, side, checked_at: new Date().toISOString(),
      url: page.url(), endpoint: new URL(response.url()).pathname, http_status: response.status(), request, ...result };
    await writeFile(path.join(output, `${caseId}-${side}.json`), JSON.stringify(evidence, null, 2));
    console.log(caseId, side, result.score.status, result.run_id);
    return result.score.correct;
  } finally {
    await page.close();
  }
}

async function main() {
  assert(selected.every(id => /^case(?:[1-9]|10)$/.test(id)), 'Use case1 through case10');
  await mkdir(output, { recursive: true });
  const queue = ['post', 'pre'].flatMap(side => selected.map(id => [id, side]));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const failures = [];
  try {
    async function worker() {
      while (queue.length) {
        const [id, side] = queue.shift();
        try {
          if (!await runSide(browser, id, side)) failures.push(`${id} ${side}: SQL result mismatch`);
        } catch (error) {
          failures.push(`${id} ${side}: ${error.message}`);
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(5, queue.length) }, worker));
  } finally {
    await browser.close();
  }
  assert.deepEqual(failures, []);
}

main().catch(error => { console.error(error); process.exitCode = 1; });
