import pytest


@pytest.mark.smoke
def test_essential_imports() -> None:
    import polmon.backend  # noqa: F401
    import polmon.client.app  # noqa: F401

