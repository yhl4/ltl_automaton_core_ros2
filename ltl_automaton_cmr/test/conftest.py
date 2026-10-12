"""Import the source packages for isolated local tests without a ROS build."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
for package in ("ltl_automaton_cmr", "ltl_automaton_execution"):
    sys.path.insert(0, str(ROOT / package))
