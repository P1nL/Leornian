"""DeepSeek Chat Completions wire format for a single public teaching question."""

import json
from urllib.parse import urlsplit

from leornian.agent_runtime.policies import estimate_tokens

LOOKUP_STAGE = "node_web_lookup.v1"


def supported_binding(binding):
    return bool(binding and binding.get("scope") == "user" and binding.get("role") == "tutor.v1"
                and binding.get("protocol") == "chat_completions"
                and binding.get("base_url", "").rstrip("/") in {
                    "https://api.deepseek.com", "https://api.deepseek.com/v1",
                } and binding.get("model") in {"deepseek-flash", "deepseek-v4-pro"})


def lookup_request(binding, author_policy, question):
    request = {
        "model": binding["model"], "thinking": {"type": "disabled"}, "stream": True,
        "max_tokens": min(2048, author_policy["max_output_tokens"]),
        "tools": [{"type": "deepseek_web_search"}],
        "messages": [
            {"role": "system", "content": (
                "Search for the exact named feature and version. When the question asks for "
                "official documentation, search the publisher's own documentation using site: "
                "and cite the original page for that feature. A forum, mirror or a link mentioned "
                "in a snippet is not that page. Use the course documentation host if relevant. "
                "Return only the requested finding with citations; report missing evidence."
            )},
            {"role": "user", "content": question},
        ],
    }
    policy = {
        "stage": LOOKUP_STAGE, "thinking": "disabled",
        "max_output_tokens": request["max_tokens"],
        "estimated_input_tokens": estimate_tokens(request),
        "response_bytes": 512_000, "timeout_seconds": author_policy["timeout_seconds"],
        "connect_timeout_seconds": author_policy["connect_timeout_seconds"],
    }
    return request, policy


def lookup_evidence(body):
    sources = {}
    try:
        choice = json.loads(body)["choices"][0]
        message = choice["message"]
        if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
            return []
        for step in message.get("server_tool_calls") or []:
            for call in step.get("calls") or []:
                if call.get("status") != "completed":
                    continue
                for item in [*(call.get("sources") or []), call.get("page") or {}]:
                    url = item.get("url")
                    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                        continue
                    parsed = urlsplit(url)
                    if not parsed.hostname or parsed.username is not None:
                        continue
                    sources.setdefault(url, {"url": url, "title": item.get("title") or url,
                                             "snippet": item.get("snippet") or ""})
        answer = message.get("content") or ""
        cited = {}
        for item in message.get("annotations") or []:
            citation = item.get("url_citation") or {}
            url = citation.get("url")
            if item.get("type") != "url_citation" or url not in sources:
                continue
            start, end = citation.get("start_index"), citation.get("end_index")
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(answer):
                cited.setdefault(url, []).append(answer[start:end])
        ordered = dict.fromkeys([*cited, *sources])
        return [{**sources[url], **({"cited_answer": " ".join(cited[url])} if url in cited else {})}
                for url in ordered if url in cited or sources[url]["snippet"]][:8]
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        return []
