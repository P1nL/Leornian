import ipaddress
import json
import socket
from urllib.parse import urlsplit

import httpx

from leornian.shared_kernel.errors import BusinessError


def redact_credential(body, secret):
    if secret:
        for representation in {secret, json.dumps(secret, ensure_ascii=False)[1:-1]}:
            body = body.replace(representation, "[leornian-redacted-credential]")
    return body


def validate_endpoint(base_url, local_endpoint):
    url = urlsplit(base_url)
    try:
        port = url.port
    except ValueError:
        raise BusinessError("precondition_failed", "Invalid model endpoint port.") from None
    if not url.hostname or url.username or url.password or url.query or url.fragment:
        raise BusinessError("precondition_failed", "Model endpoint is not a safe base URL.")
    host = url.hostname.lower()
    if "%" in host or "\\" in base_url or any(c.isspace() for c in base_url):
        raise BusinessError("precondition_failed", "Invalid model endpoint.")
    if local_endpoint:
        if host not in {"127.0.0.1", "::1", "localhost"} or url.scheme not in {"http", "https"}:
            raise BusinessError("precondition_failed", "Local models must use explicit loopback.")
    elif url.scheme != "https" or port not in {None, 443}:
        raise BusinessError("precondition_failed", "External model endpoints require HTTPS:443.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if not local_endpoint and address is not None and not public_address(address):
        raise BusinessError("precondition_failed", "External model endpoint is not public.")


def public_address(address):
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_global


def resolve_destination(base_url, local_endpoint):
    validate_endpoint(base_url, local_endpoint)
    url = urlsplit(base_url)
    host = url.hostname
    port = url.port or (443 if url.scheme == "https" else 80)
    if local_endpoint:
        return "::1" if host == "::1" else "127.0.0.1"
    try:
        addresses = list(
            dict.fromkeys(
                entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            )
        )
        if not addresses or any(not public_address(ipaddress.ip_address(ip)) for ip in addresses):
            raise ValueError("private_destination")
    except (OSError, ValueError):
        raise BusinessError(
            "model_unavailable", "Model endpoint DNS is unavailable or not publicly routable."
        ) from None
    return addresses[0]


def pin_request(request, origin, destination):
    url = httpx.URL(origin)
    if (request.url.scheme, request.url.host, request.url.port) != (url.scheme, url.host, url.port):
        raise BusinessError("model_unavailable", "Model request changed its configured origin.")
    # Keep TLS certificate verification and Host bound to the original hostname.
    # The validated numeric address is the actual socket destination, avoiding DNS rebinding.
    request.headers["Host"] = url.netloc.decode("ascii")
    request.extensions["sni_hostname"] = url.host
    request.url = request.url.copy_with(host=destination)


class PinnedModelTransport(httpx.BaseTransport):
    def __init__(self, origin, destination, inner=None):
        self.origin, self.destination = origin, destination
        self.inner = inner or httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request):
        pin_request(request, self.origin, self.destination)
        return self.inner.handle_request(request)

    def close(self):
        self.inner.close()


class AsyncPinnedModelTransport(httpx.AsyncBaseTransport):
    def __init__(self, origin, destination, inner=None):
        self.origin, self.destination = origin, destination
        self.inner = inner or httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request):
        pin_request(request, self.origin, self.destination)
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()
