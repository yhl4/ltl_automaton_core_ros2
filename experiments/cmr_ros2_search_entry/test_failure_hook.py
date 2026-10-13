"""Regression for the recursive DDS-to-lifecycle test hook."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.cmr_ros2_search_entry import runner, dds, lifecycle, failure_dds


class FailureHookTests(unittest.TestCase):
    def test_lifecycle_calls_original_candidate_and_restores_hook(self):
        original = runner.candidate_isolated
        args = SimpleNamespace(binding='unused', kernel_root='unused', output=Path('/tmp/test'))
        plan = dict(qualification_id='q', scope=runner.DDS_FAILURE_SCOPE,
                    execution_identity='e', version_binding_path='/tmp/binding.json')
        cell = dict(instance_id='A-T1-M0-A-S-BRANCH', method='FULL')
        entry = SimpleNamespace(describe=lambda _: {'backend':'ros2-v7'})
        def fault(*args, **kwargs):
            self.assertIs(runner.candidate_isolated, original)
            return {'test':'passed'}
        def server(argv):
            return runner.candidate_isolated(args, plan, cell, Path('/tmp/test/attempt'))
        with patch.object(runner,'VerifiedEntry',return_value=entry), \
             patch.object(lifecycle,'run_fault',side_effect=fault), \
             patch.object(dds,'main',side_effect=server):
            self.assertEqual(failure_dds.child('late_delivery',[]), {'test':'passed'})
        self.assertIs(runner.candidate_isolated, original)


if __name__=='__main__':
    unittest.main()
