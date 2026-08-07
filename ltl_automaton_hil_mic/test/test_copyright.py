# Copyright 2026 yuhling

from ament_copyright.main import main
import pytest


@pytest.mark.skip(reason="Package source headers are tracked as follow-up work.")
@pytest.mark.copyright
@pytest.mark.linter
def test_copyright():
    """Check source files for copyright notices."""
    return_code = main(argv=[".", "test"])
    assert return_code == 0, "Found errors"
