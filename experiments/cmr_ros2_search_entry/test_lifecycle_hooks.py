"""Offline checks for the V7 lifecycle hook boundary.

These tests do not construct a plan, start a worker, import ROS, or call a
solver.  They only verify the parent process hook mechanics.
"""

import types
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from experiments.cmr_ros2_real.bound_runner import _clone_function
from experiments.cmr_ros2_search_entry import lifecycle


class _Process:
    def __init__(self):
        self.wait_calls = 0

    def wait(self, *args, **kwargs):
        self.wait_calls += 1
        return 0


class LifecycleHookTests(unittest.TestCase):
    def _fake_runner(self):
        old_runner = types.SimpleNamespace(
            time=object(), subprocess=types.SimpleNamespace(Popen=object()))
        return types.SimpleNamespace(
            HERE=Path("C:/v7/search_entry"), old_runner=old_runner)

    def test_v7_path_is_intercepted_and_v6_path_is_not(self):
        fake_runner = self._fake_runner()
        calls = []

        def real_popen(command, **kwargs):
            calls.append((list(command), kwargs))
            return _Process()

        clock = object()
        old_time = fake_runner.old_runner.time
        old_popen = fake_runner.old_runner.subprocess.Popen
        with patch.object(lifecycle, "_v7_runner", return_value=fake_runner), \
                patch.object(lifecycle, "REAL_POPEN", side_effect=real_popen):
            with lifecycle._parent_hooks("crash", clock):
                v7_path = str((fake_runner.HERE / "runner.py").resolve())
                hook = fake_runner.old_runner.subprocess.Popen
                hook([v7_path, "--worker"])
                self.assertEqual(calls[-1][0][0],
                                 str((lifecycle.HERE / "lifecycle.py").resolve()))
                self.assertTrue(Path(calls[-1][0][0]).is_file())
                self.assertEqual(calls[-1][0][-2:], ["--fault-child", "crash"])
                v6_path = str(Path("C:/v6/runner.py").resolve())
                hook([v6_path, "--worker"])
                self.assertEqual(calls[-1][0][0], v6_path)
            self.assertIs(fake_runner.old_runner.time, old_time)
            self.assertIs(fake_runner.old_runner.subprocess.Popen, old_popen)

    def test_clock_is_available_to_clone_before_candidate_construction(self):
        fake_runner = self._fake_runner()
        clock = object()

        def probe():
            return time

        with patch.object(lifecycle, "_v7_runner", return_value=fake_runner), \
                patch.object(lifecycle, "REAL_POPEN", return_value=_Process()):
            with lifecycle._parent_hooks("late_delivery", clock):
                cloned = _clone_function(probe, {"time": fake_runner.old_runner.time})
                self.assertIs(cloned(), clock)

    def test_child_fault_clock_is_read_back_before_late_delivery_override(self):
        fake_runner = self._fake_runner()
        clock = types.SimpleNamespace(offset_ns=0)
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(lifecycle, "_v7_runner", return_value=fake_runner), \
                patch.object(lifecycle, "REAL_POPEN", return_value=_Process()):
            output = Path(temporary)
            with lifecycle._parent_hooks("late_solver", clock, output):
                v7_path = str((fake_runner.HERE / "runner.py").resolve())
                process = fake_runner.old_runner.subprocess.Popen([v7_path, "--worker"])
                (output / "fault_clock.json").write_text(
                    '{"offset_ns": 180000000000}\n', encoding="utf-8")
                process.wait()
                self.assertEqual(clock.offset_ns, 180000000000)
            self.assertEqual(clock.offset_ns, 180000000000)

    def test_finally_restores_v6_clone_source_globals(self):
        fake_runner = self._fake_runner()
        old_time = fake_runner.old_runner.time
        old_popen = fake_runner.old_runner.subprocess.Popen
        with patch.object(lifecycle, "_v7_runner", return_value=fake_runner), \
                patch.object(lifecycle, "REAL_POPEN", return_value=_Process()):
            with self.assertRaisesRegex(RuntimeError, "sentinel"):
                with lifecycle._parent_hooks("late_logging", object()):
                    raise RuntimeError("sentinel")
        self.assertIs(fake_runner.old_runner.time, old_time)
        self.assertIs(fake_runner.old_runner.subprocess.Popen, old_popen)


if __name__ == "__main__":
    unittest.main()
