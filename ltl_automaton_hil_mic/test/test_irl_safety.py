"""Keep the optional IRL plugin out of the default trap-only setup."""

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_optional_irl_runtime_module_is_available():
    assert (
        PACKAGE_ROOT
        / "ltl_automaton_hil_mic"
        / "inverse_reinforcement_learning.py"
    ).exists()


def test_irl_plugin_requires_explicit_configuration():
    plugin_config = (
        PACKAGE_ROOT / "config" / "trap_detection_plugin.yaml"
    ).read_text(encoding="utf-8")
    setup_py = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert "IRLPlugin" not in plugin_config
    assert "inverse_reinforcement_learning" not in plugin_config
    assert "inverse_reinforcement_learning" not in setup_py
    optional_config = (
        PACKAGE_ROOT / "config" / "irl_plugin.yaml"
    ).read_text(encoding="utf-8")
    assert "IRLPlugin" in optional_config
    assert "inverse_reinforcement_learning" in optional_config
