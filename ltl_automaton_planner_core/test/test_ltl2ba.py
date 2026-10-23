"""Exercise the translator process boundary without an external binary."""

import subprocess

import pytest

from ltl_automaton_planner_core.ltl_tools import ltl2ba


@pytest.fixture
def executable(monkeypatch):
    monkeypatch.setattr(ltl2ba.shutil, "which", lambda name: "/tools/ltl2ba")


def test_missing_executable_has_domain_error(monkeypatch):
    monkeypatch.setattr(ltl2ba.shutil, "which", lambda name: None)
    with pytest.raises(ltl2ba.LTL2BAError, match="Cannot find"):
        ltl2ba.run_ltl2ba("<> cargo")


@pytest.mark.parametrize("formula", [None, "", "   "])
def test_empty_formula_is_rejected(formula):
    with pytest.raises(ValueError, match="non-empty string"):
        ltl2ba.run_ltl2ba(formula)


def test_launch_failure_has_domain_error(executable, monkeypatch):
    cause = PermissionError("Permission denied")

    def fail(*args, **kwargs):
        raise cause

    monkeypatch.setattr(ltl2ba.subprocess, "run", fail)
    with pytest.raises(ltl2ba.LTL2BAError, match="Cannot execute.*ltl2ba") as error:
        ltl2ba.run_ltl2ba("<> cargo")
    assert error.value.__cause__ is cause


@pytest.mark.parametrize(
    ("cause", "message"),
    [
        (subprocess.TimeoutExpired("ltl2ba", 0.1), "timed out"),
        (subprocess.CalledProcessError(1, "ltl2ba", "", "bad formula"), "bad formula"),
        (subprocess.CalledProcessError(1, "ltl2ba", None, None), "Unknown ltl2ba error"),
    ],
)
def test_process_failure_has_domain_error(executable, monkeypatch, cause, message):
    def fail(*args, **kwargs):
        raise cause

    monkeypatch.setattr(ltl2ba.subprocess, "run", fail)
    with pytest.raises(ltl2ba.LTL2BAError, match=message) as error:
        ltl2ba.run_ltl2ba("<> cargo")
    assert error.value.__cause__ is cause


def test_translation_preserves_arguments_and_output(executable, monkeypatch):
    output = "never { /* translator output */ }\n"

    def run(args, **kwargs):
        assert args == ["/tools/ltl2ba", "-f", "<> cargo"]
        assert kwargs == dict(check=True, capture_output=True, text=True, timeout=2)
        return subprocess.CompletedProcess(args, 0, stdout=output)

    monkeypatch.setattr(ltl2ba.subprocess, "run", run)
    assert ltl2ba.run_ltl2ba("<> cargo", timeout=2) == output


def test_empty_output_is_rejected(executable, monkeypatch):
    monkeypatch.setattr(
        ltl2ba.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout="  \n"),
    )
    with pytest.raises(ltl2ba.LTL2BAError, match="empty result"):
        ltl2ba.run_ltl2ba("<> cargo")
