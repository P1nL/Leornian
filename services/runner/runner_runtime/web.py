"""Build course web assets and inspect them in an isolated browser."""

import json
import secrets

from .sandbox import (
    _bounded_container,
    _mount,
    _new_volume,
    _project_options,
    _remove_volume,
    _stage_archive,
    _unavailable_cases,
)

_WEB_CHECK = r"""
import json, mimetypes, pathlib, sys
from urllib.parse import unquote, urlsplit
from playwright.sync_api import sync_playwright
data = json.load(sys.stdin)
root = pathlib.Path("/workspace").resolve()
origin = "http://leornian.invalid/"
def serve(route):
    url = urlsplit(route.request.url)
    if url.scheme != "http" or url.netloc != "leornian.invalid":
        return route.abort()
    target = (root / unquote(url.path).lstrip("/")).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return route.fulfill(status=404, body="Not found")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    route.fulfill(path=str(target), content_type=content_type)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, chromium_sandbox=False,
                               args=["--disable-dev-shm-usage"])
    context = browser.new_context(service_workers="block", accept_downloads=False)
    context.route("**/*", serve)
    page = context.new_page()
    page.set_default_timeout(1500)
    page.goto(origin + data["entrypoint"], wait_until="load")
    results = []
    for check in data["checks"]:
        locator = page.locator(check["selector"])
        kind = check["kind"]
        if kind == "exists":
            value = locator.count() > 0
        elif kind == "style":
            value = locator.first.evaluate(
                "(node, property) => getComputedStyle(node).getPropertyValue(property)",
                check["property"])
        else:
            if kind == "click_text":
                page.locator(check["action_selector"]).first.click()
            value = locator.first.inner_text()
        actual = value[:500] if isinstance(value,str) else value
        results.append({"key": check["key"], "actual": actual})
    print(json.dumps({"protocol":"web-check-result.v1","results":results},ensure_ascii=False))
    browser.close()
"""



def execute_web(program, release, authorize=None):
    return execute_web_with_build(program, release, authorize)[1]



def execute_web_with_build(program, release, authorize=None):
    from leornian.modules.execution.contracts import WebCheckResult, WebProgram

    data = WebProgram.model_validate(program).model_dump(mode="json")
    if (
        not release or release["id"] != data["environment_release_id"]
        or release["profile"] != data["profile"] or release["language"] != data["language"]
        or release["runtime_version"] != data["runtime_version"]
    ):
        return None, _unavailable_cases(1, "runner_environment_unavailable")
    if authorize and not authorize():
        return None, _unavailable_cases(1, "environment_authorization_changed")
    course = release.get("verification", {}).get("course_environment")
    if data["language"] != "html-css" and (not course or course["build"] != "vite"):
        return None, _unavailable_cases(1, "runner_environment_unavailable")
    source = "leornian-web-" + secrets.token_hex(10)
    build = None
    compilation = None
    _new_volume(source)
    try:
        _stage_archive(source, data["files"], release["image_id"], course)
        browser_volume = source
        if course and course["build"] == "vite":
            build = source + "-build"
            _new_volume(build)
            _stage_archive(build, [], release["image_id"])
            command = _project_options(source + "-compile", memory="1024m") + [
                "--mount", _mount(source, "/workspace", readonly=True),
                "--mount", _mount(build, "/build"), "--workdir=/workspace",
                release["image_id"], "node", "/opt/leornian/course/build.mjs",
            ]
            compilation = _bounded_container(command, b"", source + "-compile", 90, authorize)
            if compilation["outcome"] != "completed" or compilation["exit_code"] != 0:
                return compilation, []
            browser_volume = build
        name = source + "-browser"
        command = _project_options(name, memory="768m") + [
            "--shm-size=128m", "--mount", _mount(browser_volume, "/workspace", readonly=True),
            "--workdir=/workspace", "-i", release["image_id"], "python", "-I", "-B", "-c",
            _WEB_CHECK,
        ]
        result = _bounded_container(command, json.dumps(data).encode(), name, 35, authorize)
        if result["outcome"] == "completed" and result["exit_code"] == 0:
            parsed = WebCheckResult.model_validate_json(result["stdout"])
            if [item.key for item in parsed.results] != [item["key"] for item in data["checks"]]:
                return compilation, _unavailable_cases(1, "invalid_web_check_result")
        return compilation, [result]
    finally:
        if build is not None:
            _remove_volume(build)
        _remove_volume(source)

