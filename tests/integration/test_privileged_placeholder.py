import pytest


@pytest.mark.integration
@pytest.mark.privileged
def test_privileged_suite_is_explicitly_selectable() -> None:
    """Marker sentinel; real namespace coverage arrives with the L1 milestone."""
    pytest.skip("NOT RUN — L1 namespace backend is not implemented in v0.0.2")

