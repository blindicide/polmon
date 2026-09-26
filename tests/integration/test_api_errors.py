import pytest
from fastapi.testclient import TestClient

from polmon.backend import app
from polmon.core.errors import ConfigurationError


@app.get("/_test/error")
def raise_configuration_error() -> None:
    raise ConfigurationError("invalid test input", details={"field": "example"})


@pytest.mark.integration
def test_application_error_contract() -> None:
    response = TestClient(app).get("/_test/error")
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "configuration_error",
            "message": "invalid test input",
            "details": {"field": "example"},
        }
    }

