"""Directed exact-arithmetic and unchanged-witness checks for V7."""

import json
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

from experiments.cmr_ros2_bfull_target import backend as baseline
from experiments.cmr_ros2_bfull_target import fixtures as previous
from experiments.cmr_ros2_search_entry import backend


def run():
    cases = dict(previous.v4_fixtures.v3_fixtures.v2_fixtures._cases())
    cases.update(previous.v4_fixtures.v3_fixtures._extra_cases())
    base = cases['parallel_witness']
    cases['large_exact_integers'] = SimpleNamespace(**dict(vars(base), transitions=tuple(
        replace(edge, cost=Fraction(2**80 + index), witnesses=tuple(
            replace(witness, cost=Fraction(2**80 + index)) for witness in edge.witnesses))
        for index, edge in enumerate(base.transitions))))
    failures = {'none_cost': TypeError, 'float_cost': TypeError,
                'negative_cost': ValueError}
    report = {}
    for name, abstract in cases.items():
        before = previous.v4_fixtures._input_fingerprint(abstract)
        if name in failures:
            try:
                backend.solve_cmr_lasso(abstract)
            except failures[name]:
                report[name] = {'status': 'REJECTED'}
                continue
            raise AssertionError('invalid weight accepted: ' + name)
        left_work, right_work = {}, {}
        left = baseline.solve_cmr_lasso(abstract, work=left_work)
        right = backend.solve_cmr_lasso(abstract, work=right_work)
        if left != right:
            raise AssertionError('exact result/witness changed: ' + name)
        if before != previous.v4_fixtures._input_fingerprint(abstract):
            raise AssertionError('input changed: ' + name)
        # The new numeric representation must not change pruning or settlement.
        if any(right_work[key] != value for key, value in left_work.items()):
            raise AssertionError('search trace changed: ' + name)
        if right is not None:
            previous._hand_checks(right, abstract)
        report[name] = dict(status='PASSED',
            integer_edges=right_work['integer_weight_edges'],
            fraction_edges=right_work['fractional_weight_edges'])
    if report['parallel_witness']['fraction_edges'] == 0:
        raise AssertionError('nonintegral path not exercised')
    if report['large_exact_integers']['integer_edges'] == 0:
        raise AssertionError('large exact integer path not exercised')
    return dict(status='PASSED', cases=report, planner_calls=len(cases),
                formal_campaign_workers=0)
