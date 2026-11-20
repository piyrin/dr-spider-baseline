"""Loopback HTTP entry point for the RSI Data demo."""

from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import urllib.error
from uuid import uuid4

from flow import CASES, DATABASE, ROOT, evaluate_steps, run_agent_step, run_flow

sys.path.insert(0, str(ROOT / 'scripts'))
from run_api_sample import api_json, git_output, read_settings, resolve_model
from baseline import load, save


RUNS = ROOT / 'runs/task2-rsi-data'
ENDPOINT = '/api/engine/flow'
STEP_ENDPOINT = '/api/task2/step'


def model_client():
    settings = read_settings()
    key = settings.get('THINGO_API_KEY', '').strip()
    if not key:
        raise ValueError('请在仓库的本地 .env 中配置 THINGO_API_KEY')
    url = settings.get('THINGO_BASE_URL', 'https://intlapi.thingo.com.cn/v1').rstrip('/')
    model = resolve_model(settings.get('THINGO_MODEL', 'gpt6sol'), api_json(url + '/models', key))

    def complete(system, content):
        response = api_json(url + '/chat/completions', key, {
            'model': model, 'stream': False,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
        })
        choice = response['choices'][0]
        output = choice['message'].get('content')
        if choice.get('finish_reason') != 'stop' or not isinstance(output, str) or not output.strip():
            raise RuntimeError('模型生成未正常完成')
        return output.strip(), {'requested': model, 'returned': response.get('model'),
                                'fingerprint': response.get('system_fingerprint'),
                                'digest': None, 'response_id': response.get('id')}

    return complete


def save_run(result, started, runtime):
    run_id = started.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
    result.update({'run_id': run_id, 'started_at': started.isoformat(), 'runtime': runtime,
                   'parameters': {'stream': False, 'other': 'provider defaults'},
                   'code_commit': git_output('rev-parse', 'HEAD'),
                   'source_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in (Path(__file__), Path(__file__).with_name('flow.py'))},
                   'database_sha256': hashlib.sha256(DATABASE.read_bytes()).hexdigest(),
                   'data_version': load(ROOT / 'manifests/data_source.json'),
                   'verification': '同一 SQLite 数据库中比较行多重集合，保留重复次数'})
    save(RUNS / f'{run_id}.json', result)
    return result


class FlowHandler(BaseHTTPRequestHandler):
    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != ENDPOINT:
            self.reply(404, {'error': '接口不存在'})
            return
        latest = {}
        for path in sorted(RUNS.glob('*.json'), reverse=True):
            result = load(path)
            latest.setdefault(result['flowId'], result)
            if len(latest) == len(CASES):
                break
        self.reply(200, {'cases': {key: {'question': value['question'], 'tables': value['tables']}
                                   for key, value in CASES.items()}, 'latest': latest})

    def do_POST(self):
        if self.path not in (ENDPOINT, STEP_ENDPOINT):
            self.reply(404, {'error': '接口不存在'})
            return
        origin = self.headers.get('Origin')
        if origin not in (None, 'http://127.0.0.1:3210', 'http://localhost:3210'):
            self.reply(403, {'error': '请从本地数据平台运行'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = 65536 if self.path == STEP_ENDPOINT else 8192
            if not 0 < length <= limit or self.headers.get_content_type() != 'application/json':
                raise ValueError('请求必须是 JSON')
            payload = json.loads(self.rfile.read(length))
            flow_id = payload['flowId']
            params = payload['params']
            question = params['question'].strip()
            if flow_id not in CASES or not 1 <= len(question) <= 500:
                raise ValueError('流程或问题不符合要求')
        except (ValueError, KeyError, TypeError, AttributeError):
            self.reply(400, {'error': '请传入有效的 flowId 和 1 至 500 字的问题'})
            return

        started = datetime.now(timezone.utc)
        try:
            if self.path == STEP_ENDPOINT:
                agent = params['agent']
                previous = params.get('steps', [])
                if agent == 'execute':
                    result = save_run(evaluate_steps(flow_id, question, previous), started, 'spring-boot')
                else:
                    result = run_agent_step(flow_id, agent, question, model_client(), previous)
            else:
                result = save_run(run_flow(flow_id, question, model_client()), started, 'python')
        except (RuntimeError, urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError) as error:
            print(f'[{started.isoformat()}] {flow_id}: {type(error).__name__}', flush=True)
            self.reply(502, {'error': '模型请求失败，请检查本地 API 配置或服务状态'})
            return
        self.reply(200, {'data': result})


if __name__ == '__main__':
    with ThreadingHTTPServer(('127.0.0.1', 3211), FlowHandler) as server:
        print('任务二后端 http://127.0.0.1:3211/api/engine/flow', flush=True)
        server.serve_forever()
