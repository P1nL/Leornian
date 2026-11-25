import asyncio
import base64
import json
import math
from pathlib import Path

import httpx

from leornian.agent_runtime.contracts import Receipt
from leornian.agent_runtime.gateway import DeliveryUnknown, ModelProtocolError
from leornian.platform.model_network import (
    AsyncPinnedModelTransport,
    redact_credential,
    resolve_destination,
)

PROBE_TEXTS = ["Leornian is a learning application.", "A fixed unrelated connection probe."]


class MaterialProbeGateway:
    """Dedicated, harmless connection probes; no chat policy, tools, or learner material."""

    def __init__(self, configuration, transport=None):
        self.configuration, self.transport = configuration, transport
        self.destination = None

    @property
    def endpoint(self):
        config = self.configuration
        if config.operation == "rerank":
            return config.base_url + "/api/v1/services/rerank/text-rerank/text-rerank"
        if config.operation == "embedding" and config.protocol == "dashscope":
            return config.base_url + "/api/v1/services/embeddings/text-embedding/text-embedding"
        suffix = "/embeddings" if config.operation == "embedding" else "/chat/completions"
        base = config.base_url
        if config.protocol == "dashscope":
            base += "/compatible-mode/v1"
        return base + suffix

    def probe(self):
        config = self.configuration
        policy = {
            "protocol": "material-" + config.operation + "-probe.v1",
            "timeout_seconds": config.timeout,
            "connect_timeout_seconds": 10,
            "response_bytes": 1_000_000,
        }
        if config.operation == "embedding":
            if config.protocol == "dashscope":
                request = {
                    "model": config.model,
                    "input": {"texts": PROBE_TEXTS},
                    "parameters": {"dimension": config.dimensions, "text_type": "document"},
                }
            else:
                request = {
                    "model": config.model,
                    "input": PROBE_TEXTS,
                    "dimensions": config.dimensions,
                    "encoding_format": "float",
                }
        elif config.operation == "rerank":
            request = {
                "model": config.model,
                "input": {"query": "Which document describes learning?", "documents": PROBE_TEXTS},
                "parameters": {"top_n": 2},
            }
        else:
            image = (Path(__file__).parent / "assets" / "ocr-connection-probe.png").read_bytes()
            encoded = base64.b64encode(image).decode("ascii")
            request = {
                "model": config.model,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64," + encoded},
                            },
                            {"type": "text", "text": "Output only the text in the image."},
                        ],
                    }
                ],
            }
        return request, policy

    def check_destination(self, endpoint, request):
        if endpoint != self.endpoint or request.get("model") != self.configuration.model:
            raise ModelProtocolError("provider_configuration_changed")
        if self.destination is None:
            self.destination = resolve_destination(
                self.configuration.base_url,
                self.configuration.local_endpoint,
            )

    def send(self, endpoint, request, *, policy):
        self.check_destination(endpoint, request)
        return asyncio.run(self._send(endpoint, request, policy))

    async def _send(self, endpoint, request, policy):
        config = self.configuration
        transport = AsyncPinnedModelTransport(config.base_url, self.destination, self.transport)
        try:
            async with (
                asyncio.timeout(policy["timeout_seconds"]),
                httpx.AsyncClient(
                    transport=transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(
                        policy["timeout_seconds"],
                        connect=policy["connect_timeout_seconds"],
                    ),
                ) as client,
                client.stream(
                    "POST",
                    endpoint,
                    json=request,
                    headers={"Authorization": "Bearer " + config.api_key},
                ) as response,
            ):
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > policy["response_bytes"]:
                        raise DeliveryUnknown("incomplete_or_oversized_response")
                return Receipt(
                    body=redact_credential(body.decode("utf-8", errors="replace"), config.api_key),
                    http_status=response.status_code,
                    provider_request_id=redact_credential(
                        response.headers.get("x-request-id", ""), config.api_key
                    )[:200]
                    or None,
                )
        except (TimeoutError, httpx.TransportError) as error:
            raise DeliveryUnknown(type(error).__name__) from None

    def validate(self, body):
        config = self.configuration
        try:
            response = json.loads(body)
            if config.operation == "embedding":
                native = config.protocol == "dashscope"
                values = response["output"]["embeddings"] if native else response["data"]
                indices = [entry["text_index" if native else "index"] for entry in values]
                if (
                    len(values) != 2
                    or any(type(i) is not int for i in indices)
                    or set(indices) != {0, 1}
                ):
                    raise ValueError("incomplete_embeddings")
                for entry in values:
                    vector = entry["embedding"]
                    if (
                        len(vector) != config.dimensions
                        or any(type(v) not in {int, float} or not math.isfinite(v) for v in vector)
                        or not any(vector)
                    ):
                        raise ValueError("invalid_embedding_dimensions")
                return {"embedding_dimensions": config.dimensions, "input_count": 2}
            if config.operation == "rerank":
                values = response["output"]["results"]
                indices = [entry["index"] for entry in values]
                if (
                    len(values) != 2
                    or any(type(i) is not int for i in indices)
                    or set(indices) != {0, 1}
                ):
                    raise ValueError("incomplete_ranking")
                if any(
                    type(entry["relevance_score"]) not in {int, float}
                    or not math.isfinite(entry["relevance_score"])
                    or not 0 <= entry["relevance_score"] <= 1
                    for entry in values
                ):
                    raise ValueError("invalid_ranking")
                return {"ranked_count": 2}
            choices = response["choices"]
            if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
                raise ValueError("incomplete_ocr")
            message = choices[0]["message"]
            if message.get("tool_calls") or "".join(message["content"].split()) != "LEORNIAN123":
                raise ValueError("fixed_ocr_sample_mismatch")
            return {"fixed_text_recognition": "verified", "layout_and_code_quality": "not_tested"}
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise ModelProtocolError("invalid_material_probe_response") from None
