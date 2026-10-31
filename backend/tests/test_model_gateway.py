import json

import httpx
import pytest

from leornian.agent_runtime.gateway import (
    ChatCompletionsGateway,
    DeliveryUnknown,
    ModelProtocolError,
    parse_decision,
)
from leornian.platform.config import Settings


@pytest.mark.parametrize("body", ["null", "[]", "{}", '{"choices":[null]}', "invalid"])
def test_malformed_model_bodies_are_known_validation_failures(body):
    with pytest.raises(ModelProtocolError):
        parse_decision(body)


def test_gateway_does_not_follow_redirects_or_retry_transport_errors():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://provider.invalid/v1",
        model_name="owned-test",
        model_api_key="owned-secret",
    )
    seen = []

    def redirect(request):
        seen.append(request)
        return httpx.Response(307, headers={"location": "https://elsewhere.invalid"})

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(redirect))
    request = gateway.request([{"role": "user", "content": "Hello"}], require_tool=True)
    assert gateway.send(gateway.endpoint, request).http_status == 307
    assert len(seen) == 1

    def timeout(request):
        seen.append(request)
        raise httpx.ConnectTimeout("owned test")

    seen.clear()
    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(timeout))
    with pytest.raises(DeliveryUnknown):
        gateway.send(gateway.endpoint, request)
    assert len(seen) == 1
    assert "owned-secret" not in json.dumps(request)


def test_configuration_needs_explicit_enablement_and_secure_endpoint():
    assert not ChatCompletionsGateway(Settings()).availability().ready
    assert (
        not ChatCompletionsGateway(
            Settings(
                model_enabled=True,
                model_base_url="http://remote.invalid/v1",
                model_name="test",
                model_api_key="owned-secret",
            )
        )
        .availability()
        .ready
    )
