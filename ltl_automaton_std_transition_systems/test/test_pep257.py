# Copyright 2026 yuhling

from ament_pep257.main import main
import pytest


@pytest.mark.linter
@pytest.mark.pep257
def test_pep257():
    """Check Python docstrings with pydocstyle."""
    return_code = main(argv=["."])
    assert return_code == 0, "Found code style errors / warnings"
