# Copyright 2026 yuhling

from ament_flake8.main import main_with_errors
import pytest


@pytest.mark.linter
@pytest.mark.flake8
def test_flake8():
    """Check code style with flake8."""
    return_code, errors = main_with_errors(argv=[])
    assert return_code == 0, "Found %d code style errors:\n" % len(errors) + "\n".join(
        errors
    )
