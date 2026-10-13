"""Minimal metadata-only scope checks; no authority or method dispatch."""

import unittest
from unittest.mock import patch

from experiments.cmr_ros2_search_entry import runner


class FailureProfileTests(unittest.TestCase):
    def test_original_targets_remain_separate_from_failure_scope(self):
        self.assertEqual(runner.TARGETS, (
            ('A-T1-M0-A-S-BRANCH','FULL'), ('B-D-BRANCH-S2','FULL'), ('C3-T4','AP-D')))
        self.assertNotIn(('D1-1','FULL'), runner.TARGETS)

    def test_stale_infeasible_metadata_is_rejected(self):
        a = dict(instance_id='A-T1-M0-A-S-BRANCH')
        d = dict(instance_id='D1-1', feasibility_class='FEASIBLE')
        current = dict(authority_receipt='unused', records=[a],
                       cells=[dict(instance_id=a['instance_id'],method='FULL')])
        prior = dict(records=[d], cells=[dict(instance_id=d['instance_id'],method='FULL')])
        with patch.object(runner.qualification,'selection',return_value=prior):
            with self.assertRaisesRegex(ValueError,'infeasible control metadata'):
                runner.failure_selection(current)


if __name__=='__main__':
    unittest.main()
