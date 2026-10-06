"""Focused translator process-boundary checks without an installed binary."""

import errno

import pytest

from ltl_automaton_planner_core.ltl_tools import ltl2ba


def test_startup_error_preserves_public_exception_and_native_cause(monkeypatch):
    """Wrap a failed process launch without changing its arguments or deadline."""
    native_error = OSError(errno.ENOEXEC, "Exec format error")
    calls = []
    monkeypatch.setattr(ltl2ba, "find_ltl2ba", lambda _executable: "/tool/ltl2ba")

    def failed_run(arguments, **options):
        calls.append((arguments, options))
        raise native_error

    monkeypatch.setattr(ltl2ba.subprocess, "run", failed_run)
    with pytest.raises(ltl2ba.LTL2BAError) as error:
        ltl2ba.run_ltl2ba("<> cargo", timeout=0.75)

    assert error.value.__cause__ is native_error
    assert str(native_error) in str(error.value)
    assert calls == [(
        ["/tool/ltl2ba", "-f", "<> cargo"],
        {"check": True, "capture_output": True, "text": True, "timeout": 0.75},
    )]
