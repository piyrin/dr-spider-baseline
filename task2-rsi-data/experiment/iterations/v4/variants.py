"""Small SQL-only generation and evidence-based review candidates."""

from dataclasses import dataclass
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from experiment import as_json, content_of, execute_sql, prediction_sql
from iterations.v3.canvas_rules import RULES, check_literal
from run_full_evaluation import make_payload


@dataclass(frozen=True)
class Case:
    question: str
    database: str


CHECKS = {
    'joined_population': 'Identify the set of qualifying entities before the join. An answer about entities with matching facts should group qualifying fact rows, and an answer explicitly including entities with no facts should preserve zero counts. Check the actual join keys and any duplicated entities.',
    'group_scope': 'Decide what one output row represents. Count the named entity or relationship at its intended grain. A count of qualifying groups requires a count outside the grouped filter. Apply filters at the appropriate stage.',
    'ranked_scope': 'Rank the requested entities by the requested measure and direction. Use the quantity or number of results requested, and avoid returning the ranking measure unless requested. Use consistent treatment of ties.',
    'projection': 'Return only the fields asked for, at the requested granularity. Do not emit ids, labels, counts or ranking keys used only to compute the answer. Return named attributes as separate fields when they are individually requested.',
    'execution': 'Inspect the SQLite error or empty result. Check actual identifiers, key relationships, literal spelling and operator. A legitimate empty result is allowed.',
}


def reasons(case, draft):
    sql = draft.get('sql') or ''
    question = case.question.casefold()
    selected = []
    join = re.search(r'\bjoin\b', sql, re.I)
    grouped = re.search(r'\bgroup\s+by\b', sql, re.I)
    if draft['status'] != 'executed' or (not draft['rows'] and re.search(r'\bwhere\b', sql, re.I)):
        selected.append('execution')
    if join and (grouped or re.search(r'\b(left\s+(outer\s+)?join|count\s*\()', sql, re.I)):
        selected.append('joined_population')
    if grouped and re.search(r'\b(each|every|per|at least|at most|more|less|most|least|how many|number)\b', question):
        selected.append('group_scope')
    if (join or grouped or re.search(r'\blimit\b', sql, re.I)) and re.search(
        r'\b(most|least|top|highest|lowest|maximum|minimum|greatest|largest|smallest|youngest|oldest)\b', question
    ):
        selected.append('ranked_scope')
    if re.search(r'(?:\bselect\s+(?:distinct\s+)?|,\s*)(?:\w+\.)?\*', sql, re.I) or (
        (join or grouped) and len(draft.get('columns', [])) > 1
    ):
        selected.append('projection')
    return selected


def choose(draft, candidate):
    return candidate if candidate['status'] == 'executed' else draft


def run_variant(variant, case, draft, model, complete):
    observed = reasons(case, draft)
    if variant == 'R' and not observed:
        return draft
    payload = make_payload(model, {'database': case.database, 'question': case.question})
    checks = ' '.join(CHECKS[check] for check in dict.fromkeys([*observed, 'projection']))
    if variant == 'S':
        payload['messages'][0]['content'] += (
            ' Before writing SQL, silently resolve the answer specification. '
            + ' '.join(CHECKS[k] for k in ('joined_population', 'group_scope', 'ranked_scope', 'projection'))
        )
    elif variant == 'R':
        payload['messages'][0]['content'] = (
            'Review the candidate SQLite query against the natural-language request and real schema. '
            'Check the following points: ' + checks +
            ' Preserve the draft if it answers the question. If it has a concrete error, make the smallest '
            'necessary correction. Return only KEEP or one corrected SQLite SELECT query. No commentary.'
        )
        details = {key: draft[key] for key in ('status', 'sql', 'columns', 'reason') if key in draft}
        if 'rows' in draft:
            details['row_count'] = len(draft['rows'])
            # Record shape and null/zero counts without leaking large result rows to the model.
            details['null_counts'] = [sum(row[i] is None for row in draft['rows']) for i in range(len(draft['columns']))]
            details['columns_with_zero'] = [col for i, col in enumerate(draft['columns'])
                                            if any(row[i] == 0 for row in draft['rows'])]
        payload['messages'][1]['content'] += '\nCandidate and SQLite execution\n' + as_json(details)
    else:
        raise ValueError(f'Unexpected variant {variant}')
    response = complete(payload)
    try:
        if variant == 'R' and content_of(response).rstrip('.').upper() == 'KEEP':
            return draft
        sql = prediction_sql(response)
    except (ValueError, TypeError, KeyError, IndexError):
        return draft if variant == 'R' else {'status': 'generation_error'}
    result = execute_sql(case.database, sql)
    for kind in ('literal', 'year'):
        result, _ = check_literal(case, result, RULES[kind])
    return choose(draft, result) if variant == 'R' else result
