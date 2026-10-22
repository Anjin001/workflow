from dataclasses import replace

import httpx
import pytest

from workflow.config import Settings
from workflow.errors import ModelError
from workflow.llm import ChatModel


def successful(content="{}", reason="stop"):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": reason}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        },
    )


def test_rate_limit_retries_then_succeeds():
    responses = iter([httpx.Response(429), successful()])
    delays = []
    model = ChatModel(
        Settings(api_key="test-only"),
        transport=httpx.MockTransport(lambda request: next(responses)),
        sleeper=delays.append,
    )
    try:
        assert model.complete("coder", []) == "{}"
        assert model.usage.requests == 2
        assert model.usage.retries == 1
        assert delays == [1]
    finally:
        model.close()


def test_auth_failure_never_retries_or_exposes_response_body():
    model = ChatModel(
        Settings(api_key="test-private-value"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="test-private-value")
        ),
    )
    try:
        with pytest.raises(ModelError) as error:
            model.complete("coder", [])
        assert "401" in str(error.value)
        assert "test-private-value" not in str(error.value)
        assert model.usage.requests == 1
    finally:
        model.close()


@pytest.mark.parametrize("failure", ["timeout", "server"])
def test_transient_failure_stops_after_retry_limit(failure):
    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private diagnostic must not be logged", request=request)
        return httpx.Response(503)

    model = ChatModel(
        replace(Settings(api_key="test-only"), request_retries=1),
        transport=httpx.MockTransport(respond),
        sleeper=lambda delay: None,
    )
    try:
        with pytest.raises(ModelError):
            model.complete("coder", [])
        assert model.usage.requests == 2
        assert model.usage.retries == 1
    finally:
        model.close()


@pytest.mark.parametrize(
    "response",
    [
        successful("{}", "length"),
        httpx.Response(200, json={}),
        httpx.Response(200, text="not json"),
        successful(None),
    ],
)
def test_incomplete_or_invalid_envelope_is_rejected(response):
    model = ChatModel(
        Settings(api_key="test-only"), transport=httpx.MockTransport(lambda request: response)
    )
    try:
        with pytest.raises(ModelError):
            model.complete("coder", [])
    finally:
        model.close()


def test_missing_key_has_clear_configuration_error():
    with pytest.raises(ModelError, match="LLM_API_KEY"):
        ChatModel(Settings())
