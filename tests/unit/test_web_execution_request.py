import pytest
from pydantic import ValidationError

from amor.web.jobs import ExecutionRequest


def _payload() -> dict[str, object]:
    return {
        "contract_sha256": "a" * 64,
        "provider": "openai-responses",
        "model": "implementation-model",
        "sandbox": {
            "mode": "docker",
            "dependency_bootstrap": "auto",
        },
        "confirm_send_code": True,
    }


def test_dependency_bootstrap_requires_separate_consent() -> None:
    with pytest.raises(ValidationError, match="explicit confirmation"):
        ExecutionRequest.model_validate(_payload())


def test_dependency_bootstrap_accepts_explicit_consent() -> None:
    request = ExecutionRequest.model_validate(
        {**_payload(), "confirm_dependency_install": True}
    )

    assert request.sandbox.dependency_bootstrap.value == "auto"
