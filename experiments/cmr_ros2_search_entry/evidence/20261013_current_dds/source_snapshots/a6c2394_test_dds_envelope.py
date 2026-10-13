"""Offline envelope checks for the V7 DDS adapter.

These tests do not import ROS, the V7 runner, a provider, or a solver.
"""

import unittest

from experiments.cmr_ros2_search_entry import dds


class V7EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.cell = {"instance_id": "A-T1-M0-A-S-BRANCH", "method": "FULL",
                     "expected_initial_S0": [["s0"]]}
        self.descriptor = {
            "backend": "ros2-v7", "backend_id": "V7",
            "backend_sha256": "a" * 64,
            "version_binding_id": "CMR_SEARCH_ENTRY_V1-test",
            "version_binding_sha256": "b" * 64,
        }

    def test_exact_envelope_and_budget(self):
        request = dds._request_envelope(
            self.cell, self.descriptor, "qualification", "population", "execution", "req",
            instance_sha256="c" * 64)
        dds._require_exact_envelope(request, request)
        altered = dict(request, outer_watchdog_seconds=196)
        with self.assertRaises(ValueError):
            dds._require_exact_envelope(altered, request)

    def test_model_hash_is_present_and_missing_or_wrong_hash_is_rejected(self):
        self.assertNotIn("instance_sha256", self.cell)
        request = dds._request_envelope(
            self.cell, self.descriptor, "qualification", "population", "execution", "req",
            instance_sha256="c" * 64)
        self.assertEqual(request["instance_sha256"], "c" * 64)
        with self.assertRaises(ValueError):
            dds._require_exact_envelope(
                {key: value for key, value in request.items() if key != "instance_sha256"}, request)
        with self.assertRaises(ValueError):
            dds._require_exact_envelope(dict(request, instance_sha256="d" * 64), request)

    def test_worker_result_must_match_input_and_execution_identity(self):
        request = dict(instance_sha256="c" * 64, execution_identity="execution")
        result = dict(worker_pid=42, instance_sha256="c" * 64,
                      benchmark_payload_sha256="c" * 64, execution_commit="execution")
        dds._require_result_identity(request, result)
        for key in ("instance_sha256", "benchmark_payload_sha256", "execution_commit"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                dds._require_result_identity(request, dict(result, **{key: "wrong"}))
        dds._require_result_identity(request, dict(terminal_status="ERROR", worker_pid=None))

    def test_fixed_scope_rejects_out_of_scope_cell(self):
        plan = {"cells": [dict(self.cell),
                           {"instance_id": "B-D-BRANCH-S2", "method": "FULL"},
                           {"instance_id": "C3-T4", "method": "AP-D"}],
                "formal_campaign": False, "planner_budget_seconds": 180,
                "outer_watchdog_seconds": 195}
        self.assertEqual(len(dds._fixed_cells(plan)), 3)
        with self.assertRaises(ValueError):
            dds._request_cell(plan, {"instance_id": "D1-1", "method": "FULL"})

    def test_failure_profile_admits_only_its_two_fixed_cells(self):
        plan = dict(scope=dds.FAILURE_SCOPE,
                    cells=[dict(instance_id=name, method=method)
                           for name, method in dds.FAILURE_TARGETS],
                    formal_campaign=False, planner_budget_seconds=180,
                    outer_watchdog_seconds=195)
        self.assertEqual(dds._request_cell(plan, dict(instance_id='D1-1',method='FULL')),
                         plan['cells'][1])
        with self.assertRaises(ValueError):
            dds._request_cell(plan, dict(instance_id='B-D-BRANCH-S2',method='FULL'))
        with self.assertRaises(ValueError):
            dds._fixed_cells(dict(plan, outer_watchdog_seconds=194))


if __name__ == "__main__":
    unittest.main()
