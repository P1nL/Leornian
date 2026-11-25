"""Approved public HTTPS reads, with each redirect pinned to a public address."""

import ipaddress
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from leornian.platform.model_network import PinnedModelTransport, resolve_destination
from leornian.shared_kernel.errors import BusinessError


class SourceHTTPError(BusinessError):
    def __init__(self, status):
        super().__init__("source_http_unavailable", f"Source returned HTTP {status}.")
        self.http_status = status


def canonical_source_url(value):
    try:
        url = urlsplit(value)
        host = (url.hostname or "").encode("idna").decode("ascii").lower()
        port = url.port
    except (ValueError, UnicodeError):
        raise BusinessError("precondition_failed", "Invalid source address.") from None
    if (
        url.scheme != "https"
        or not host
        or port not in {None, 443}
        or url.username
        or url.password
        or url.fragment
        or url.query
        or "\\" in value
        or any(c.isspace() for c in value)
        or "%" in host
    ):
        raise BusinessError(
            "precondition_failed", "Sources require public HTTPS:443 without credentials or query."
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise BusinessError("precondition_failed", "Source address is not public.")
    path = url.path or "/"
    decoded = unquote(path)
    if (
        "\\" in decoded
        or "\x00" in decoded
        or any(p in {".", ".."} for p in decoded.split("/"))
        or "%" in decoded
        or "//" in decoded
    ):
        raise BusinessError("precondition_failed", "Source path is not canonical.")
    host = f"[{host}]" if ":" in host else host
    return urlunsplit(("https", host, path, "", ""))


def approved_source_url(value, prefixes):
    value = canonical_source_url(value)
    candidate = urlsplit(value)
    for prefix in prefixes:
        allowed = urlsplit(canonical_source_url(prefix))
        if candidate.netloc != allowed.netloc:
            continue
        base, path = unquote(allowed.path), unquote(candidate.path)
        if path == base or (base.endswith("/") and path.startswith(base)):
            return value
    raise BusinessError("source_not_current", "Source is outside its approved address scope.")


@dataclass(frozen=True)
class SourceResponse:
    url: str
    status_code: int
    content: bytes
    content_type: str | None
    etag: str | None
    last_modified: str | None
    redirects: tuple[str, ...]


def remaining_seconds(deadline):
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise BusinessError("material_example_deadline", "示例补读时间已用完。")
    return remaining


def response_bytes(response, limit, deadline=None):
    coding = response.headers.get("content-encoding", "identity").lower().strip()
    if coding not in {"identity", "gzip", "deflate"}:
        raise BusinessError("source_encoding_unsupported", "Source uses an unsupported encoding.")
    decoder = (
        zlib.decompressobj(16 + zlib.MAX_WBITS)
        if coding == "gzip"
        else zlib.decompressobj()
        if coding == "deflate"
        else None
    )
    result = bytearray()
    try:
        for block in response.iter_raw(chunk_size=None if deadline else 65536):
            if deadline:
                remaining_seconds(deadline)
            if decoder:
                block = decoder.decompress(block, limit + 1 - len(result))
                if decoder.unconsumed_tail:
                    raise BusinessError("material_file_limit", "Source exceeds its byte limit.")
            result.extend(block)
            if len(result) > limit:
                raise BusinessError("material_file_limit", "Source exceeds its byte limit.")
        if decoder:
            result.extend(decoder.flush(limit + 1 - len(result)))
            if len(result) > limit or not decoder.eof or decoder.unused_data:
                raise BusinessError("material_file_limit", "Source encoding exceeds its limit.")
    except zlib.error:
        raise BusinessError("source_encoding_invalid", "Source encoding is invalid.") from None
    return bytes(result)


class ApprovedSourceClient:
    def __init__(self, *, timeout=30, max_bytes=20_000_000, max_redirects=4, transport=None):
        self.timeout, self.max_bytes, self.max_redirects = timeout, max_bytes, max_redirects
        self.transport = transport

    def get(self, url, prefixes, *, etag=None, last_modified=None, deadline=None):
        current = approved_source_url(url, prefixes)
        redirects = []
        headers = {
            "Accept": "text/html,text/plain,text/markdown,application/pdf,image/png,image/jpeg",
            "Accept-Encoding": "identity",
            "User-Agent": "Leornian-materials/1",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        while True:
            parts = urlsplit(current)
            origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
            try:
                if deadline:
                    remaining_seconds(deadline)
                destination = resolve_destination(origin, False)
                transport = PinnedModelTransport(origin, destination, self.transport)
                timeout = self.timeout
                if deadline:
                    timeout = min(timeout, remaining_seconds(deadline))
                with httpx.Client(
                    transport=transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(timeout, connect=min(10, timeout)),
                ) as client:
                    with client.stream("GET", current, headers=headers) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            target = response.headers.get("location")
                            if not target or len(redirects) >= self.max_redirects:
                                raise BusinessError(
                                    "source_redirect_limit", "Source redirect did not resolve."
                                )
                            current = approved_source_url(urljoin(current, target), prefixes)
                            if current in redirects or current == url:
                                raise BusinessError(
                                    "source_redirect_limit", "Source redirect repeats an address."
                                )
                            redirects.append(current)
                            continue
                        if response.status_code == 304 and not (etag or last_modified):
                            raise BusinessError(
                                "source_response_invalid", "An unconditional source returned 304."
                            )
                        if response.status_code not in {200, 304}:
                            raise SourceHTTPError(response.status_code)
                        content = (
                            response_bytes(response, self.max_bytes, deadline)
                            if response.status_code == 200
                            else b""
                        )
                        if response.status_code == 200 and not content:
                            raise BusinessError("source_response_invalid", "Source body is empty.")
                        return SourceResponse(
                            current,
                            response.status_code,
                            content,
                            response.headers.get("content-type"),
                            response.headers.get("etag"),
                            response.headers.get("last-modified"),
                            tuple(redirects),
                        )
            except httpx.HTTPError:
                raise BusinessError(
                    "source_network_unavailable", "Source read ended without a complete response."
                ) from None
            except BusinessError as error:
                if error.code == "model_unavailable":
                    raise BusinessError(
                        "source_network_unavailable", "Source DNS is not publicly routable."
                    ) from None
                raise
