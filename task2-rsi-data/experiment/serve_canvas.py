"""Local worker for the courses's Spring Boot canvas runner."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
from threading import Lock
import time
from uuid import uuid4

from experiment import HERE, GRAPHS, Scenario, execute_sql, score
from iterations.v3.canvas_rules import GRAPHS_V3, canvas_digest
from run import complete_at, model_client
from run_api_sample import load, save
from boolean_canvas import EXAMPLES as BOOLEAN_EXAMPLES, GRAPH as BOOLEAN_GRAPH, boolean_step, is_boolean, validate_boolean
from boolean_evidence_canvas import GRAPH as BOOLEAN_EVIDENCE_GRAPH, evidence_step, is_evidence, validate_evidence
from count_scope_canvas import EXAMPLES as COUNT_EXAMPLES, GRAPH as COUNT_GRAPH, count_step, is_count, validate_count
from count_scope_v2 import GRAPH_V2 as COUNT_GRAPH_V2, count_step_v2, is_count_v2, validate_count_v2
from count_scope_v3 import GRAPH_V3 as COUNT_GRAPH_V3, count_step_v3, is_count_v3, validate_count_v3
from format_canvas import EXAMPLES as FORMAT_EXAMPLES, GRAPH as FORMAT_GRAPH, format_step, is_format, validate_format
from filter_column_canvas import (
    EXAMPLES as COLUMN_EXAMPLES, GRAPH as COLUMN_GRAPH, column_step, is_columns, validate_columns,
)
from filter_column_v2 import (
    GRAPH_V2 as COLUMN_GRAPH_V2, column_step_v2, is_column_v2, validate_column_v2,
)
from filter_count_canvas import (
    EXAMPLES as FILTER_COUNT_EXAMPLES, GRAPH as FILTER_COUNT_GRAPH,
    filter_count_step, is_filter_count, validate_filter_count,
)
from split_output_canvas import EXAMPLES as SPLIT_EXAMPLES, GRAPH as SPLIT_GRAPH, is_split, split_step, validate_split
from split_output_v2 import FIELD_KIND as SPLIT_V2_FIELD, GRAPH_V2 as SPLIT_GRAPH_V2, split_step_v2, validate_split_v2
from split_output_v3 import (
    GRAPH_V3 as SPLIT_REVIEW_GRAPH, ReviewInput, is_review_v3, review_step, validate_v3 as validate_review_v3,
)
from sort_direction_canvas import EXAMPLES as SORT_EXAMPLES, GRAPH as SORT_GRAPH, is_sort, sort_step, validate_sort
from sort_direction_v2 import GRAPH_V2 as SORT_GRAPH_V2, is_sort_v2, sort_step_v2, validate_sort_v2
from sort_direction_v3 import GRAPH_V3 as SORT_GRAPH_V3, is_sort_v3, sort_step_v3, validate_sort_v3
from synonym_canvas import EXAMPLES as SYNONYM_EXAMPLES, GRAPH as SYNONYM_GRAPH, is_synonym, synonym_step, validate_synonym
from projection_canvas import EXAMPLES, GRAPH, is_projection, projection_step, validate_projection
from projection_generalization import FIRST_KIND, GRAPH_V2, generalized_step, validate_v2
from top_n_canvas import (EXAMPLES as TOP_N_EXAMPLES, GRAPH as TOP_N_GRAPH,
                          INTERACTIVE_GRAPH as TOP_N_INTERACTIVE, is_top_n,
                          original_or_control, top_n_step, validate_top_n)
from top_n_original import (GRAPH as TOP_N_ORIGINAL, is_original_graph,
                            run_step as run_top_n_original, validate as validate_top_n_original)
from top_n_v3 import GRAPH_V3 as TOP_N_V3, INTERACTIVE_V3 as TOP_N_V3_INTERACTIVE, is_v3 as is_top_n_v3, run_step as run_top_n_v3, validate_v3 as validate_top_n_v3
from top_n_v3_cases import FIXTURE_IDS as TOP_N_FIXTURES, fixture_case as top_n_fixture_case

sys.path.insert(0, str(HERE / 'iterations' / 'v4'))
from canvas_v4 import SCOPED_GRAPHS, scoped_step, validate_scoped

LIVE = {}
SESSION_LOCK = Lock()
OUTPUT = HERE / 'runs' / 'canvas'


def small(step):
    output = step['output']
    if isinstance(output, dict) and 'rows' in output:
        output = {**output, 'row_count': len(output['rows']), 'rows': output['rows'][:30]}
    elif isinstance(output, dict) and 'checked' in output:
        output = {'patch': output['patch'], 'status': output['checked']['status']}
    return {k: v for k, v in step.items() if k != 'call'} | {'output': output}


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, status=200):
        raw = json.dumps(body, ensure_ascii=False, default=repr).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(raw))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != '/catalog':
            return self.reply({'error': 'Unknown route'}, 404)
        manifest = load(HERE / 'manifest.json')
        items = [{'id': key, 'question': original_or_control(key).question}
                 for key in dict.fromkeys([*manifest['pilot'], *EXAMPLES, *FORMAT_EXAMPLES,
                                           *SYNONYM_EXAMPLES, *BOOLEAN_EXAMPLES, *COUNT_EXAMPLES,
                                           *SPLIT_EXAMPLES, *SORT_EXAMPLES, *COLUMN_EXAMPLES, *FILTER_COUNT_EXAMPLES,
                                           *TOP_N_EXAMPLES])]
        items.extend({'id': key, 'question': top_n_fixture_case(key).question} for key in TOP_N_FIXTURES)
        self.reply({'graphs': {**GRAPHS, **GRAPHS_V3,
                               'scope_compact': SCOPED_GRAPHS['C'], 'scope_full': SCOPED_GRAPHS['U'],
                               'projection': GRAPH, 'projection_v2': GRAPH_V2, 'filter_format': FORMAT_GRAPH,
                               'filter_synonym': SYNONYM_GRAPH, 'filter_boolean': BOOLEAN_GRAPH,
                               'filter_boolean_evidence': BOOLEAN_EVIDENCE_GRAPH,
                               'count_scope': COUNT_GRAPH, 'count_scope_v2': COUNT_GRAPH_V2,
                               'count_scope_v3': COUNT_GRAPH_V3, 'split_output': SPLIT_GRAPH, 'split_output_v2': SPLIT_GRAPH_V2,
                               'split_output_v3': SPLIT_REVIEW_GRAPH,
                               'sort_direction': SORT_GRAPH, 'sort_meaning_v2': SORT_GRAPH_V2,
                               'sort_direction_v3': SORT_GRAPH_V3,
                               'filter_column': COLUMN_GRAPH, 'filter_column_v2': COLUMN_GRAPH_V2,
                               'filter_count': FILTER_COUNT_GRAPH, 'top_n': TOP_N_GRAPH,
                               'top_n_interactive': TOP_N_INTERACTIVE, 'top_n_original': TOP_N_ORIGINAL,
                               'top_n_v3': TOP_N_V3, 'top_n_v3_interactive': TOP_N_V3_INTERACTIVE},
                    'examples': items})

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 65536:
                raise ValueError('Request body must be between 1 and 65,536 bytes')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Expected an object')
            result = {'/begin': self.begin, '/step': self.step, '/finish': self.finish_run}.get(self.path)
            if result is None:
                return self.reply({'error': 'Unknown route'}, 404)
            self.reply(result(body))
        except (KeyError, ValueError) as error:
            self.reply({'error': str(error)}, 400)
        except Exception as error:
            self.reply({'error': f'{type(error).__name__}: {str(error)[:500]}'}, 502)

    def begin(self, body):
        graph = body['graph']
        sample_id = body['sample_id']
        case = top_n_fixture_case(sample_id) if sample_id in TOP_N_FIXTURES else original_or_control(sample_id)
        if is_top_n_v3(graph):
            ordered, runner = validate_top_n_v3(graph), run_top_n_v3
        elif is_original_graph(graph):
            ordered, runner = validate_top_n_original(graph, case), run_top_n_original
        elif is_top_n(graph):
            ordered, runner = validate_top_n(graph), top_n_step
        elif is_filter_count(graph):
            ordered, runner = validate_filter_count(graph), filter_count_step
        elif is_columns(graph):
            ordered, runner = validate_columns(graph), column_step
        elif is_column_v2(graph):
            ordered, runner = validate_column_v2(graph), column_step_v2
        elif is_sort_v3(graph):
            ordered, runner = validate_sort_v3(graph), sort_step_v3
        elif is_sort_v2(graph):
            ordered, runner = validate_sort_v2(graph), sort_step_v2
        elif is_sort(graph):
            ordered, runner = validate_sort(graph), sort_step
        elif is_review_v3(graph):
            ordered, runner = validate_review_v3(graph), review_step
        elif is_split(graph):
            if any(node.get('kind') == SPLIT_V2_FIELD for node in graph['nodes']):
                ordered, runner = validate_split_v2(graph), split_step_v2
            else:
                ordered, runner = validate_split(graph), split_step
        elif is_count_v3(graph):
            ordered, runner = validate_count_v3(graph), count_step_v3
        elif is_count_v2(graph):
            ordered, runner = validate_count_v2(graph), count_step_v2
        elif is_count(graph):
            ordered, runner = validate_count(graph), count_step
        elif is_evidence(graph):
            ordered, runner = validate_evidence(graph), evidence_step
        elif is_boolean(graph):
            ordered, runner = validate_boolean(graph), boolean_step
        elif is_synonym(graph):
            ordered, runner = validate_synonym(graph), synonym_step
        elif is_format(graph):
            ordered, runner = validate_format(graph), format_step
        elif is_projection(graph):
            version_2 = any(isinstance(node, dict) and node.get('kind') == FIRST_KIND for node in graph['nodes'])
            ordered = validate_v2(graph) if version_2 else validate_projection(graph)
            runner = generalized_step if version_2 else projection_step
        else:
            ordered, runner = validate_scoped(graph), scoped_step
        run_id = uuid4().hex
        state = {'created': time.time(), 'case': case, 'ordered': ordered, 'steps': {},
                 'runner': runner,
                 'graph_sha256': canvas_digest(ordered), 'graph': body['graph'], 'lock': Lock()}
        with SESSION_LOCK:
            for key in list(LIVE):
                if state['created'] - LIVE[key]['created'] > 900:
                    del LIVE[key]
            if len(LIVE) >= 40:
                raise ValueError('Too many active canvas runs')
            LIVE[run_id] = state
        return {'run_id': run_id, 'graph_sha256': state['graph_sha256'],
                'sequence': [n['id'] for n in ordered]}

    def step(self, body):
        run_id = body['run_id']
        with SESSION_LOCK:
            state = LIVE[run_id]
        with state['lock']:
            index = len(state['steps'])
            if index >= len(state['ordered']):
                raise ValueError('Canvas flow has no remaining steps')
            node = state['ordered'][index]
            started = time.monotonic()
            model, endpoint, key = self.server.client
            case = state['case']
            inputs = ReviewInput(case.question, case.database) if state['runner'] is review_step else case
            output, call = state['runner'](node, inputs, model,
                                           [state['steps'][parent] for parent in node['from']],
                                           lambda _, payload: complete_at(endpoint, key, payload))
            state['steps'][node['id']] = {**node, 'output': output, 'call': call,
                                         'elapsed_s': time.monotonic() - started}
            return {'node': node['id'], 'position': index}

    def finish_run(self, body):
        run_id = body['run_id']
        with SESSION_LOCK:
            state = LIVE.pop(run_id)
        with state['lock']:
            if len(state['steps']) != len(state['ordered']):
                raise ValueError('Course engine did not execute all planned nodes')
            steps = list(state['steps'].values())
            calls = [step['call'] for step in steps if step['call'] is not None]
            usages = [(call.get('usage') or {}).get('total_tokens') for call in calls]
            cost = {'model_calls': len(calls), 'total_tokens': sum(usages) if all(type(n) is int for n in usages) else None}
            record = {'sample_id': state['case'].id, 'graph': state['graph'],
                      'run_id': run_id, 'graph_sha256': state['graph_sha256'],
                      'steps': steps, 'score': score(state['case'], steps[-1]['output']), 'cost': cost}
            if state['runner'] is review_step:
                draft = steps[0]['output']
                initial = execute_sql(state['case'].database, draft['sql']) if draft.get('sql') else {
                    'status': draft.get('status', 'generation_error'), 'reason': draft.get('reason')}
                record['draft_score'] = score(state['case'], initial)
            save(OUTPUT / (run_id + '.json'), record)
            return {**record, 'steps': [small(step) for step in steps]}


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 3213), Handler)
    server.client = model_client()
    print('Canvas model worker listening on 127.0.0.1:3213', flush=True)
    server.serve_forever()
