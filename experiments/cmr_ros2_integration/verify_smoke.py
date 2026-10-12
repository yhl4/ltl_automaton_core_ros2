"""One bounded synthetic qualification of refinement, deadlines and actual DDS."""

import argparse
import json
from fractions import Fraction
from pathlib import Path
import traceback

import runtime


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def request(name, variant, method, **extra):
    return dict(request_id=name, variant=variant, method=method,
                planner_budget_seconds=10, outer_watchdog_seconds=12, **extra)


def check_result(value, context):
    """Use exact arithmetic and authoritative full transitions to check a witness."""
    require(value['schema'] == runtime.SCHEMA, 'wrong result schema')
    require(value['population'] == 'SYNTHETIC_SMOKE', 'wrong population')
    require(value['T_total'] == (value['terminal_completion_ns'] - value['method_start_ns']) / 1e9,
            'elapsed time is not tied to observed completion')
    if value['terminal_status'] == 'TIMEOUT':
        require(value['right_censored'] and value['timing_status'] == 'RIGHT_CENSORED',
                'timeout must be right censored')
        require(value['objective'] is None and value['infeasibility_proof'] is None
                and value['concrete_lasso'] is None and not value['certificate_valid_for_terminal'],
                'timeout retained a scientific/execution claim')
        require(all(not row['terminal_claim_valid'] for row in value['rounds']),
                'late round claim not invalidated')
        return
    require(not value['right_censored'], 'completed result censored')
    if value['terminal_status'] == 'INFEASIBLE_CERTIFIED':
        require(value['objective'] is None and value['concrete_lasso'] is None,
                'infeasible result has a lasso/objective')
        require(value['infeasibility_proof']['type'] == 'REDUCED_PRODUCT_EXACT_EMPTY',
                'missing exact emptiness proof')
        return
    require(value['terminal_status'] == 'OPTIMALITY_CERTIFIED', value.get('error'))
    lasso = value['concrete_lasso']
    prefix, suffix = lasso['prefix'], lasso['suffix']
    require(prefix[-1] == suffix[0] == suffix[-1] and lasso['suffix_edges'], 'invalid closed lasso')
    model = runtime.fixture(context, value['variant'])
    require((tuple(prefix[0][0]), prefix[0][1]) in model.initial_product_states(),
            'initial label mismatch')
    require(any(q in model.buchi.accepting for _, q in suffix[:-1]), 'nonaccepting suffix')
    for states, edges in ((prefix, lasso['prefix_edges']), (suffix, lasso['suffix_edges'])):
        require(len(states) == len(edges) + 1, 'path length mismatch')
        for source, edge, target in zip(states, edges, states[1:]):
            require(edge['source'] == source and edge['target'] == target, 'edge alignment mismatch')
            s, t = (tuple(source[0]), source[1]), (tuple(target[0]), target[1])
            require(any(e.target == t and e.action == edge['action'] and e.cost == Fraction(edge['cost'])
                        for e in model.transitions_from(s)), 'witness is not a formal transition')
    p = sum((Fraction(e['cost']) for e in lasso['prefix_edges']), Fraction(0))
    s = sum((Fraction(e['cost']) for e in lasso['suffix_edges']), Fraction(0))
    require(p == Fraction(lasso['prefix_cost']) and s == Fraction(lasso['suffix_cost']),
            'component sum mismatch')
    require(p + 10 * s == Fraction(value['objective']) == Fraction(lasso['upper_bound']),
            'objective mismatch')


def run(args, artifact):
    context = runtime.prepare_context(args.binding, args.kernel_root)
    artifact['preflight'] = context['manifest']
    for variant in ('cost_gap', 'spurious'):
        for method in ('FULL', 'AP-D', 'DEP-D'):
            name = f'{variant}_{method}'
            req = request(name, variant, method)
            reference_dir = args.output / ('reference_' + name)
            reference_dir.mkdir()
            runtime.run_local(req, context, reference_dir, reference=True)
            reference = json.loads((reference_dir / 'worker_result.json').read_text())
            adapted = runtime.run_isolated(req, args.binding, args.kernel_root,
                                           args.output / ('adapted_' + name))
            row = dict(request=req, reference=reference, adapted=adapted)
            artifact['matrix'].append(row)
            for value in (reference, adapted):
                check_result(value, context)
                expected = 'OPTIMALITY_CERTIFIED' if variant == 'cost_gap' else 'INFEASIBLE_CERTIFIED'
                require(value['terminal_status'] == expected, name + ': unexpected status')
                require(value['final_precision'] == [0, 1], name + ': did not reach full precision')
                require(value['refinement_rounds'] == (1 if method == 'AP-D' else 0),
                        name + ': wrong refinement count')
                require(len(value['rounds']) == (2 if method == 'AP-D' else 1), name + ': wrong rounds')
                if variant == 'cost_gap':
                    require(Fraction(value['objective']) == 30, name + ': hand-computed cost is 30')
                if method == 'AP-D':
                    first = value['rounds'][0]
                    require(first['precision'] == [0] and first['refinement']['new_precision'] == [0, 1],
                            name + ': wrong precision transition')
                    expected_cert = ('CONCRETIZABLE_NOT_OPTIMALITY_CERTIFIED' if variant == 'cost_gap'
                                     else 'NOT_CONCRETIZABLE_AT_CURRENT_PRECISION')
                    require(first['certificate_status'] == expected_cert, name + ': wrong gap reason')
                    require(Fraction(first['lower_bound']) == 10, name + ': wrong abstract LB')
                    require(first['upper_bound'] == ('30' if variant == 'cost_gap' else None),
                            name + ': wrong abstract UB')
            require(not adapted['worker_alive_after_cleanup'], name + ': leaked worker')
            require(reference['objective'] == adapted['objective'], name + ': reference mismatch')
            require(adapted['cumulative_graph_work']['observed_rounds'] == len(adapted['rounds']),
                    name + ': missing graph accounting')

    for stage, variant in (('search', 'cost_gap'), ('certification', 'cost_gap'),
                           ('logging', 'cost_gap'), ('logging', 'spurious')):
        name = f'late_{stage}_{variant}'
        req = request(name, variant, 'FULL')
        req.update(planner_budget_seconds=0.1, fault_stage=stage, fault_delay_seconds=0.15)
        directory = args.output / name
        directory.mkdir()
        runtime.run_local(req, context, directory)
        value = json.loads((directory / 'worker_result.json').read_text())
        artifact['deadline_cases'].append(dict(request=req, result=value))
        require(value['terminal_status'] == 'TIMEOUT', name + ': late result accepted')
        check_result(value, context)
        require(value['T_total'] >= 0.1, name + ': replaced observed duration with budget')
        if stage == 'certification':
            persisted = json.loads((directory / 'certificate_attempt_0.json').read_text())
            require(persisted['status'] == 'OPTIMALITY_CERTIFIED', 'missing late certificate evidence')
        if stage == 'logging':
            persisted = json.loads((directory / 'attempt.json').read_text())
            require(persisted['terminal_status'] in ('OPTIMALITY_CERTIFIED', 'INFEASIBLE_CERTIFIED'),
                    'missing pre-deadline logging evidence')

    # Exact boundary test uses a deterministic timestamp, not measured experiment data.
    boundary = runtime.new_result(request('boundary', 'base', 'FULL'), 100, 110)
    boundary.update(terminal_status='OPTIMALITY_CERTIFIED', objective='10', concrete_lasso={})
    runtime.normalize_terminal(boundary, 110)
    require(boundary['terminal_status'] == 'TIMEOUT' and boundary['objective'] is None,
            'equality at deadline must expire')
    artifact['deadline_boundary_contract'] = boundary

    req = request('outer_watchdog', 'cost_gap', 'AP-D')
    # Bound-source preflight takes about 4.5 seconds in this WSL checkout.
    # Leave time to enter the injected phase; keep the normal method budget.
    req.update(outer_watchdog_seconds=7, fault_stage='search', fault_delay_seconds=5)
    value = runtime.run_isolated(req, args.binding, args.kernel_root, args.output / 'outer_watchdog')
    artifact['watchdog'] = dict(request=req, result=value)
    check_result(value, context)
    require(value['terminal_status'] == 'TIMEOUT' and value['timeout_stage'] == 'outer_watchdog',
            'outer watchdog not enforced')
    require(value.get('interrupted_phase') == 'search' and not value['worker_alive_after_cleanup'],
            'watchdog did not interrupt/clean the injected blocking search')
    require(value['T_total'] >= 7, 'watchdog did not preserve measured duration')

    from dds_smoke import run_dds_smoke
    artifact['dds'] = run_dds_smoke(args.binding, args.kernel_root, args.output / 'dds')
    require(artifact['dds']['status'] == 'PASSED', 'DDS qualification failed')
    artifact['status'] = 'PASSED'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not str(args.output).startswith('/tmp/'):
        raise SystemExit('output must be a fresh directory under /tmp')
    args.output.mkdir(parents=True, exist_ok=False)
    artifact = dict(schema='cmr-ros2-refinement-dds-smoke-v1', population='SYNTHETIC_SMOKE',
                    status='RUNNING', matrix=[], deadline_cases=[], preflight=None)
    try:
        run(args, artifact)
        code = 0
    except Exception as exc:
        artifact.update(status='FAILED', error=repr(exc), traceback=traceback.format_exc())
        traceback.print_exc()
        code = 1
    runtime.write_json(args.output / 'qualification.json', artifact)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
