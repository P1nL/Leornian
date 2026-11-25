import json

import httpx

from leornian.agent_runtime.contracts import Receipt
from leornian.agent_runtime.gateway import DeliveryUnknown
from leornian.platform.model_network import (
    PinnedModelTransport,
    redact_credential,
    resolve_destination,
)

TAVILY_ORIGIN = "https://api.tavily.com"


class TavilyGateway:
    def __init__(self, secret, *, transport=None):
        self.secret, self.transport = secret, transport

    def send(self, endpoint, request):
        if endpoint not in {TAVILY_ORIGIN + "/search", TAVILY_ORIGIN + "/extract"}:
            raise ValueError("Unsupported Tavily endpoint")
        transport = self.transport or PinnedModelTransport(
            TAVILY_ORIGIN, resolve_destination(TAVILY_ORIGIN, False),
        )
        try:
            with httpx.Client(
                transport=transport, timeout=httpx.Timeout(75, connect=10),
                follow_redirects=False, trust_env=False,
            ) as client:
                response = client.post(
                    endpoint, json=request,
                    headers={"Authorization": f"Bearer {self.secret}"},
                )
                body = redact_credential(response.text, self.secret)
                try:
                    request_id = response.json().get("request_id")
                except (ValueError, AttributeError):
                    request_id = None
                return Receipt(
                    http_status=response.status_code, body=body,
                    provider_request_id=str(request_id) if request_id else None,
                )
        except httpx.HTTPError:
            raise DeliveryUnknown() from None

    @staticmethod
    def result(body):
        value = json.loads(body)
        if not isinstance(value, dict) or not isinstance(value.get("results"), list):
            raise ValueError("Invalid Tavily result")
        return value
