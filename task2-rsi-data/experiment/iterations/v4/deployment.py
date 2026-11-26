"""One-call prompt candidates, with the original system message intact."""

from cost_probe import payload_for
from variants import execute_sql, prediction_sql, check_literal, RULES


def generate_scoped(mode, case, model, complete):
    response = complete(payload_for(mode, case, model))
    try:
        return {'sql': prediction_sql(response)}
    except (ValueError, TypeError, KeyError, IndexError) as error:
        return {'status': 'generation_error', 'reason': str(error)}


def run_scoped(mode, case, model, complete):
    generated = generate_scoped(mode, case, model, complete)
    if not generated.get('sql'):
        return generated
    result = execute_sql(case.database, generated['sql'])
    for kind in ('literal', 'year'):
        result, _ = check_literal(case, result, RULES[kind])
    return result
