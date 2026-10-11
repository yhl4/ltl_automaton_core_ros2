"""Isolated CMR refinement/deadline adapter; no campaign or default planner edits."""

from __future__ import annotations

import importlib
import json
import multiprocessing as mp
import time
import traceback
from dataclasses import asdict, replace
from fractions import Fraction
from pathlib import Path
import sys

PHASE1 = Path(__file__).resolve().parents[1] / 'cmr_ros2_smoke'
sys.path.insert(0, str(PHASE1))
core_smoke = importlib.import_module('smoke')
core_backend = importlib.import_module('backend')

SCHEMA = 'cmr-ros2-integration-result-v1'


def json_default(value):
    """Serialize exact costs and precision sets without hiding unknown objects."""
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f'unsupported JSON value: {type(value).__name__}')


class BudgetExpired(TimeoutError):
    """A measured method deadline was reached."""


def write_json(path, value):
    """Persist a complete JSON record atomically inside the attempt directory."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, default=json_default) + '\n', encoding='utf-8')
    temporary.replace(path)


def prepare_context(binding, kernel_root):
    """Reuse the bound smoke preflight and additionally bind refinement."""
    for module, name in ((core_smoke, 'smoke.py'), (core_backend, 'backend.py')):
        if Path(module.__file__).resolve() != (PHASE1 / name).resolve():
            raise RuntimeError('phase-one adapter import mismatch')
    manifest, bound, model, solver, grouped, concretization, certificate = (
        core_smoke.preflight(kernel_root, binding))
    refinement = importlib.import_module('ecc_p1.refinement')
    expected_path, expected_sha = core_smoke._binding_source(bound, 'refinement')
    actual_path = Path(refinement.__file__).resolve()
    actual_sha = core_smoke.sha256_file(actual_path)
    if actual_path != expected_path or actual_sha != expected_sha:
        raise RuntimeError('qualified refinement import mismatch')
    manifest['imports']['refinement'] = {
        '__file__': str(actual_path), 'sha256': actual_sha,
        'expected_path': str(expected_path), 'expected_sha256': expected_sha,
        'size': actual_path.stat().st_size,
    }
    return dict(manifest=manifest, model=model, solver=solver, grouped=grouped,
                concretization=concretization, certificate=certificate, refinement=refinement)


def fixture(context, variant):
    """Fixed two-factor fixtures: cost gap, spurious cycle, and the prior base."""
    model = core_smoke._fixture_model(context['model'], 'base')
    if variant == 'base':
        return model
    if variant not in ('cost_gap', 'spurious'):
        raise ValueError('unknown synthetic fixture')
    spurious = variant == 'spurious'

    def guard(state):
        return state[0] == 0 and (not spurious or state[1] == 0)

    def effect(state):
        return (1, 1 if spurious else 1 - state[1])

    def cost(source, target):
        return Fraction(1 + 3 * source[1], 3)

    go = replace(model.actions[0], guard=guard, effect=effect, cost=cost,
                 read=frozenset({0, 1}) if spurious else frozenset({0}),
                 write=frozenset({0, 1}))
    alternate = replace(go, name='b_go', cost=lambda s, t: cost(s, t) + Fraction(1, 3))
    actions = (go, alternate, model.actions[2])
    if not spurious:
        actions += (model.actions[3],)
    return replace(model, actions=actions)


def validate_request(request):
    """Accept only the explicitly bounded prototype contract."""
    if not isinstance(request.get('request_id'), str) or not request['request_id']:
        raise ValueError('request_id must be nonempty')
    if request.get('method') not in core_smoke.EXPECTED_METHODS:
        raise ValueError('unknown method')
    if request.get('variant') not in ('base', 'cost_gap', 'spurious'):
        raise ValueError('unknown fixture')
    for name, default in (('planner_budget_seconds', 10), ('outer_watchdog_seconds', 12)):
        value = request.get(name, default)
        if type(value) not in (int, float) or not 0 <= value <= 60:
            raise ValueError(f'invalid {name}')
    if request.get('outer_watchdog_seconds', 12) <= 0:
        raise ValueError('outer watchdog must be positive')
    if request.get('fault_stage') not in (None, 'search', 'certification', 'logging'):
        raise ValueError('unknown synthetic fault stage')
    delay = request.get('fault_delay_seconds', 0)
    if type(delay) not in (int, float) or not 0 <= delay <= 5:
        raise ValueError('invalid synthetic fault delay')


def new_result(request, start, deadline):
    """Initialize unknowns explicitly; do not impute unobserved search work."""
    return dict(schema=SCHEMA, population='SYNTHETIC_SMOKE',
                request_id=request['request_id'], method=request['method'],
                variant=request['variant'], terminal_status='RUNNING', objective=None,
                concrete_lasso=None, infeasibility_proof=None, accepting_buchi_states=[], initial_precision=None,
                final_precision=None, refinement_rounds=0, rounds=[], phase_intervals_ns={},
                method_start_ns=start, deadline_ns=deadline, clock='perf_counter_ns_same_host',
                planner_budget_seconds=request.get('planner_budget_seconds', 10),
                outer_watchdog_seconds=request.get('outer_watchdog_seconds', 12),
                fault_injection={k: request[k] for k in ('fault_stage', 'fault_delay_seconds')
                                 if k in request}, manifest_preflight=None,
                right_censored=False, timing_status='UNFINISHED',
                certificate_valid_for_terminal=False, error=None)


def normalize_terminal(result, completion, timeout_stage=None):
    """Bind terminal claims to observed completion, including late logging."""
    result['terminal_completion_ns'] = completion
    result['T_total'] = (completion - result['method_start_ns']) / 1_000_000_000
    expired = completion >= result['deadline_ns'] or timeout_stage is not None
    if expired:
        result.update(terminal_status='TIMEOUT', objective=None, concrete_lasso=None,
                      infeasibility_proof=None, right_censored=True,
                      timing_status='RIGHT_CENSORED', timeout_stage=timeout_stage or 'planner',
                      certificate_valid_for_terminal=False)
    else:
        result.update(right_censored=False, timing_status='UNCENSORED', timeout_stage=None,
                      certificate_valid_for_terminal=(
                          result['terminal_status'] == 'OPTIMALITY_CERTIFIED'))
        if result['terminal_status'] != 'OPTIMALITY_CERTIFIED':
            result.update(objective=None, concrete_lasso=None)
        if result['terminal_status'] != 'INFEASIBLE_CERTIFIED':
            result['infeasibility_proof'] = None
    for row in result['rounds']:
        row['terminal_claim_valid'] = (not expired and result['terminal_status'] in (
            'OPTIMALITY_CERTIFIED', 'INFEASIBLE_CERTIFIED'))
    observed = [row['graph_size'] for row in result['rounds'] if row['graph_size'] is not None]
    result['cumulative_graph_work'] = {
        'observed_rounds': len(observed), 'eligible_rounds': len(result['rounds']),
        'totals': {name: sum(row[name] for row in observed) if observed else None
                   for name in ('reduced_ts_states', 'reduced_ts_edges',
                                'product_states', 'product_edges')},
        'basis': 'sum of observed round builds; unknown interrupted builds excluded',
    }
    return result


def lasso_payload(lasso):
    """Keep exact costs and the explicit closed suffix for execution validation."""
    def edge_payload(edge):
        return dict(source=edge.source, action=edge.action, target=edge.target, cost=str(edge.cost))
    return dict(prefix=lasso.prefix, suffix=lasso.suffix,
                prefix_edges=[edge_payload(e) for e in lasso.prefix_edges],
                suffix_edges=[edge_payload(e) for e in lasso.suffix_edges],
                prefix_cost=str(lasso.prefix_cost), suffix_cost=str(lasso.suffix_cost),
                upper_bound=str(lasso.upper_bound), ell=lasso.ell, m=lasso.m)


def solve_observed(abstract, context, work, check, reference=False):
    """Measure actual searches; auxiliary graph counts are not CMR SCC counters."""
    if reference:
        stats = context['solver'].SearchStats()
        answer = context['solver'].solve_exact_abstract_lasso(abstract, stats)
        work.update(basis='qualified_reference_SearchStats', counters=asdict(stats))
        return answer
    dp = importlib.import_module('ltl_automaton_planner_core.ltl_tools.discrete_plan')
    names = ('_prefix_distances', '_component_distances', '_restore_tight_path')
    originals = {name: getattr(dp, name) for name in names}
    work.update(basis='ROS2 auxiliary edge-node/seen_accept graph', calls=[],
                settled_events=0, queue_pushes=None, queue_pops=None,
                unavailable_reason='heap operations are not instrumented')

    def observed(name):
        def call(*args, **kwargs):
            check()
            entry = dict(helper=name, graph_nodes=len(args[0]),
                         graph_edges=args[0].number_of_edges(), completed=False,
                         settled_nodes=None)
            work['calls'].append(entry)
            value = originals[name](*args, **kwargs)
            entry['completed'] = True
            if name != '_restore_tight_path':
                entry['settled_nodes'] = len(value)
                work['settled_events'] += len(value)
            check()
            return value
        return call

    try:
        for name in names:
            setattr(dp, name, observed(name))
        return core_backend.solve_cmr_lasso(abstract)
    finally:
        for name, original in originals.items():
            setattr(dp, name, original)


def run_local(request, context, work_dir, *, start_ns=None, reference=False):
    """Run the complete finite strict-refinement loop with cooperative checkpoints."""
    validate_request(request)
    work_dir = Path(work_dir)
    start = time.perf_counter_ns() if start_ns is None else start_ns
    deadline = start + int(request.get('planner_budget_seconds', 10) * 1_000_000_000)
    result = new_result(request, start, deadline)
    result['manifest_preflight'] = context['manifest']

    def check():
        if time.perf_counter_ns() >= deadline:
            raise BudgetExpired('planner deadline reached')

    def phase(name, operation, intervals):
        check()
        begin = time.perf_counter_ns()
        write_json(work_dir / 'progress.json', dict(result=result, active_phase=name,
                                                   active_phase_start_ns=begin))
        value = operation()
        write_json(work_dir / 'progress.json', dict(result=result, active_phase=name,
                                                   active_phase_start_ns=begin,
                                                   operation_completed_ns=time.perf_counter_ns()))
        if request.get('fault_stage') == name:
            time.sleep(request.get('fault_delay_seconds', 0))
        intervals[name] = [begin, time.perf_counter_ns()]
        check()
        return value

    try:
        model = phase('initialization', lambda: fixture(context, request['variant']),
                      result['phase_intervals_ns'])
        result['accepting_buchi_states'] = sorted(model.buchi.accepting)
        all_factors = frozenset(model.dimensions)
        s_phi = core_smoke._task_precision(model)
        precision = (all_factors if request['method'] == 'FULL' else s_phi
                     if request['method'] == 'AP-D'
                     else core_smoke._dependency_precision(model, s_phi))
        result['initial_precision'] = sorted(precision)
        result['final_precision'] = sorted(precision)
        while True:
            row = dict(index=len(result['rounds']), precision=sorted(precision),
                       phase_intervals_ns={}, lower_bound=None, upper_bound=None,
                       certificate_status='NOT_REACHED', refinement=None, search_work={},
                       graph_size=None, round_completed=False)
            result['rounds'].append(row)
            timing = {}
            abstract = phase('abstraction', lambda: context['grouped'].build_optimistic_abstraction(
                model, precision, timing=timing), row['phase_intervals_ns'])
            row['build_intervals_ns'] = timing['intervals_ns']
            row['graph_size'] = dict(reduced_ts_states=len(abstract.reachable_ts_states),
                                     reduced_ts_edges=abstract.reduced_ts_edge_count,
                                     product_states=len(abstract.states),
                                     product_edges=len(abstract.transitions))
            def search():
                value = solve_observed(abstract, context, row['search_work'], check, reference)
                if value is not None:
                    row['lower_bound'] = str(value.lower_bound)
                    row['candidate'] = core_smoke._result_payload(value)
                return value
            candidate = phase('search', search, row['phase_intervals_ns'])
            if candidate is None:
                result['terminal_status'] = 'INFEASIBLE_CERTIFIED'
                result['infeasibility_proof'] = dict(type='REDUCED_PRODUCT_EXACT_EMPTY',
                                                    precision=sorted(precision))
                row.update(certificate_status='REDUCED_PRODUCT_EXACT_EMPTY',
                           round_completed=True)
                break
            concrete = phase('concretization', lambda: (
                context['concretization'].validate_identity_lift(model, candidate)
                if precision == all_factors else
                context['concretization'].periodically_concretize(model, abstract, candidate)),
                row['phase_intervals_ns'])
            def certify():
                value = context['certificate'].evaluate_certificate(candidate.lower_bound, concrete)
                row.update(certificate_status=value.status, upper_bound=(
                    None if value.upper_bound is None else str(value.upper_bound)),
                           concretization_status=concrete.status)
                write_json(work_dir / f'certificate_attempt_{row["index"]}.json', asdict(value))
                return value
            cert = phase('certification', certify, row['phase_intervals_ns'])
            if cert.status == 'OPTIMALITY_CERTIFIED':
                result.update(terminal_status=cert.status, objective=str(cert.lower_bound),
                              concrete_lasso=lasso_payload(concrete.concrete_lasso))
                row['round_completed'] = True
                break
            if precision == all_factors:
                result['terminal_status'] = 'CERTIFICATE_GAP'
                row['round_completed'] = True
                break
            reason = phase('refinement', lambda: context['refinement'].deterministic_refinement(
                model, abstract, candidate, cert.status), row['phase_intervals_ns'])
            if not precision < reason.new_precision <= all_factors:
                raise AssertionError('refinement must strictly increase admissible precision')
            row['refinement'] = asdict(reason)
            row['round_completed'] = True
            precision = reason.new_precision
            result['final_precision'] = sorted(precision)
            result['refinement_rounds'] += 1
        # The persisted candidate is attempt evidence, not terminal delivery authorization.
        phase('logging', lambda: write_json(work_dir / 'attempt.json', result),
              result['phase_intervals_ns'])
    except BudgetExpired:
        result['terminal_status'] = 'TIMEOUT'
    except Exception as exc:
        result.update(terminal_status='ERROR', error=repr(exc))
        (work_dir / 'traceback.txt').write_text(traceback.format_exc(), encoding='utf-8')
        traceback.print_exc()
    completion = time.perf_counter_ns()
    normalize_terminal(result, completion,
                       'planner' if result['terminal_status'] == 'TIMEOUT' else None)
    write_json(work_dir / 'worker_result.json', result)
    return result


def _worker_entry(send, request, binding, kernel_root, work_dir, start):
    deadline = start + int(request.get('planner_budget_seconds', 10) * 1_000_000_000)
    try:
        if time.perf_counter_ns() >= deadline:
            answer = normalize_terminal(new_result(request, start, deadline),
                                        time.perf_counter_ns(), 'planner')
        else:
            context = prepare_context(binding, kernel_root)
            prepared_ns = time.perf_counter_ns()
            answer = run_local(request, context, work_dir, start_ns=start)
            answer['phase_intervals_ns']['preflight_and_worker_startup'] = [start, prepared_ns]
        send.send(answer)
    except Exception as exc:
        answer = new_result(request, start, deadline)
        answer.update(terminal_status='ERROR', error=repr(exc))
        (Path(work_dir) / 'traceback.txt').write_text(traceback.format_exc(), encoding='utf-8')
        traceback.print_exc()
        send.send(normalize_terminal(answer, time.perf_counter_ns()))
    finally:
        send.close()


def run_isolated(request, binding, kernel_root, work_dir):
    """Own one fresh worker, watchdog, measured delivery, and immutable attempt directory."""
    validate_request(request)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=False)
    write_json(work_dir / 'request.json', request)
    start = time.perf_counter_ns()
    deadline = start + int(request.get('planner_budget_seconds', 10) * 1_000_000_000)
    outer = start + int(request.get('outer_watchdog_seconds', 12) * 1_000_000_000)
    context = mp.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_worker_entry,
                              args=(send, request, binding, kernel_root, str(work_dir), start))
    process.start()
    send.close()
    answer = None
    try:
        while time.perf_counter_ns() < outer:
            remaining = (outer - time.perf_counter_ns()) / 1_000_000_000
            if receive.poll(max(0, min(0.02, remaining))):
                try:
                    answer = receive.recv()
                except EOFError:
                    pass
                break
            if not process.is_alive():
                break
        if answer is None:
            progress_path = work_dir / 'progress.json'
            progress = json.loads(progress_path.read_text()) if progress_path.exists() else None
            answer = progress['result'] if progress else new_result(request, start, deadline)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
                answer['interrupted_phase'] = None if progress is None else progress['active_phase']
                normalize_terminal(answer, time.perf_counter_ns(), 'outer_watchdog')
            else:
                answer.update(terminal_status='INFRASTRUCTURE_FAILURE',
                              error='worker exited without a delivered result')
        else:
            process.join(timeout=max(0, (outer - time.perf_counter_ns()) / 1_000_000_000))
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
                normalize_terminal(answer, time.perf_counter_ns(), 'outer_watchdog')
        answer['worker_exitcode'] = process.exitcode
        answer['worker_pid'] = process.pid
        answer['worker_alive_after_cleanup'] = process.is_alive()
        # Count actual result serialization/delivery work before final authorization.
        write_json(work_dir / 'delivered_attempt.json', answer)
        timeout_stage = answer.get('timeout_stage')
        normalize_terminal(answer, time.perf_counter_ns(), timeout_stage)
        write_json(work_dir / 'result.json', answer)
        post_write = time.perf_counter_ns()
        if post_write >= deadline and answer['terminal_status'] != 'TIMEOUT':
            normalize_terminal(answer, post_write, 'planner')
            write_json(work_dir / 'result.json', answer)
        return json.loads((work_dir / 'result.json').read_text())
    finally:
        receive.close()
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
