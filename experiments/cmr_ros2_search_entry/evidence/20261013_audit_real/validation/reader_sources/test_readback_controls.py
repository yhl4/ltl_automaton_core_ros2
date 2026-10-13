"""Readback rejects hidden reuse while admitting the supported fresh run."""

from pathlib import Path
import unittest

from experiments.cmr_ros2_search_entry import readback


class ReadbackControlTests(unittest.TestCase):
    def setUp(self):
        self.report = {"cells": [{"arms": {arm: {} for arm in readback.ARMS}}]}

    def test_fresh_run_has_nine_new_workers(self):
        self.assertEqual(readback.check_continued_controls(
            Path("."), {"continued_controls": []}, self.report), 0)

    def test_fresh_run_rejects_undeclared_continued_rows(self):
        self.report["cells"][0]["arms"]["reference"]["continuation"] = {}
        with self.assertRaisesRegex(AssertionError, "match the frozen plan"):
            readback.check_continued_controls(
                Path("."), {"continued_controls": []}, self.report)

    def test_partial_or_malformed_continuation_is_rejected(self):
        for controls in (None, {}, [{}], [{}, {}, {}]):
            with self.subTest(controls=controls), self.assertRaises(AssertionError):
                readback.check_continued_controls(
                    Path("."), {"continued_controls": controls}, self.report)


if __name__ == "__main__":
    unittest.main()
