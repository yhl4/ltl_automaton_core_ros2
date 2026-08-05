"""Run the standalone ltl2ba translator and parse its output."""

import shutil
import subprocess

from .promela import Parser


class LTL2BAError(RuntimeError):
    """Report an error while executing ltl2ba."""


def find_ltl2ba(executable="ltl2ba"):
    """Return the path to the ltl2ba executable."""
    executable_path = shutil.which(executable)

    if executable_path is None:
        raise LTL2BAError(
            f"Cannot find '{executable}' in PATH."
        )

    return executable_path


def run_ltl2ba(formula, executable="ltl2ba", timeout=30.0):
    """Translate an LTL formula into a Promela never claim."""
    if not isinstance(formula, str) or not formula.strip():
        raise ValueError(
            "The LTL formula must be a non-empty string."
        )

    executable_path = find_ltl2ba(executable)

    try:
        result = subprocess.run(
            [
                executable_path,
                "-f",
                formula,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise LTL2BAError(
            "ltl2ba execution timed out."
        ) from error
    except subprocess.CalledProcessError as error:
        message = (
            error.stderr.strip()
            or error.stdout.strip()
            or "Unknown ltl2ba error."
        )

        raise LTL2BAError(
            f"ltl2ba execution failed: {message}"
        ) from error

    if not result.stdout.strip():
        raise LTL2BAError(
            "ltl2ba returned an empty result."
        )

    return result.stdout


def parse_ltl(formula, executable="ltl2ba"):
    """Translate an LTL formula and parse its Büchi transitions."""
    promela_output = run_ltl2ba(
        formula,
        executable=executable,
    )

    parser = Parser(promela_output)
    return parser.parse()
