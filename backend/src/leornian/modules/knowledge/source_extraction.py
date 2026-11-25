import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from leornian.modules.knowledge.file_parser import html_chrome
from leornian.modules.knowledge.source_network import approved_source_url
from leornian.shared_kernel.errors import BusinessError


class SourceLinks(HTMLParser):
    def __init__(self, url, prefixes, *, include_navigation=False):
        super().__init__(convert_charrefs=True)
        self.url, self.prefixes, self.links = url, prefixes, []
        self.skip, self.skip_depth = None, 0
        self.in_link, self.text_chars, self.link_text_chars = False, 0, 0
        self.link_labels, self.current_link = {}, None
        self.heading_depth, self.linked_headings, self.articles = 0, 0, 0
        self.candidates, self.include_navigation = [], include_navigation

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag == self.skip:
                self.skip_depth += 1
            return
        attributes = dict(attrs)
        navigation = self.include_navigation and (
            tag in {"nav", "aside"} or attributes.get("role") == "navigation"
            or "table-of-contents" in (attributes.get("class") or "").split()
        ) and not any(name in attributes for name in ("hidden", "aria-hidden", "style"))
        if (html_chrome(tag, attributes) and not navigation) or tag in {
            "script", "style", "head", "template",
        }:
            if tag not in {"img", "br", "hr", "input", "meta", "link", "source", "embed"}:
                self.skip, self.skip_depth = tag, 1
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_depth += 1
        if tag == "article":
            self.articles += 1
        if tag != "a":
            return
        self.in_link = False
        value = dict(attrs).get("href", "")
        if not value or value.startswith(("#", "javascript:", "mailto:", "data:")):
            return
        target = urldefrag(urljoin(self.url, value))[0]
        if target.lower().endswith((
            ".zip", ".tar", ".gz", ".exe", ".dmg", ".js", ".css", ".woff", ".svg",
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mp3",
        )):
            return
        parts = urlsplit(self.url)
        origin = urlunsplit(parts._replace(path="/", query="", fragment=""))
        approved = True
        try:
            target = approved_source_url(target, self.prefixes)
        except BusinessError:
            approved = False
            try:
                target = approved_source_url(target, [origin])
            except BusinessError:
                return
        self.in_link = target != self.url
        self.current_link = target if self.in_link else None
        if self.in_link and self.heading_depth:
            self.linked_headings += 1
        if self.in_link:
            if not approved:
                if target not in self.candidates:
                    self.candidates.append(target)
            else:
                if target not in self.links:
                    self.links.append(target)

    def handle_data(self, data):
        if not self.skip:
            size = len(" ".join(data.split()))
            self.text_chars += size
            if self.in_link:
                self.link_text_chars += size
                self.link_labels[self.current_link] = (
                    self.link_labels.get(self.current_link, "") + " " + data
                ).strip()

    def handle_endtag(self, tag):
        if tag == "a":
            self.in_link = False
            self.current_link = None
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.heading_depth:
            self.heading_depth -= 1
        if self.skip == tag:
            self.skip_depth -= 1
            if not self.skip_depth:
                self.skip = None

    def is_directory(self, parsed):
        count = len(self.links) + len(self.candidates)
        if count < 3 or not self.text_chars:
            return False
        setup = re.compile(
            r"^(?:[$>] ?)?(?:git (?:clone|checkout)|cd |(?:npm|pnpm|yarn|pip|uv) "
            r"(?:install|add|run|sync|build|test)|go (?:get|install)|dotnet (?:add|restore))"
        )
        dense_index = count >= 20 and self.link_text_chars * 5 >= self.text_chars * 2
        for block in parsed["blocks"]:
            if (block["kind"] == "table" and not (
                dense_index and len(block["text"]) <= 500
            )) or (
                block["kind"] == "code" and (
                    len(block["text"]) > 500
                    or any(
                        not setup.match(line.strip())
                        for line in block["text"].splitlines() if line.strip()
                    )
                )
            ):
                return False
        cards = self.articles >= 3 or self.linked_headings >= 3
        link_heavy = self.link_text_chars * 3 >= self.text_chars * 2
        annotated_index = (
            count >= 8 and self.link_text_chars * 5 >= self.text_chars
            and all(len(block["text"]) <= 600 for block in parsed["blocks"])
        )
        landing = (
            count >= 8
            and sum(len(block["text"]) for block in parsed["blocks"]) <= 1800
            and all(len(block["text"]) <= 350 for block in parsed["blocks"])
            and any(
                block["kind"] == "heading" and re.search(
                    r"教程|文档|指南|课程|目录|手册|tutorial|documentation|handbook|course|guide",
                    block["text"], re.I,
                ) for block in parsed["blocks"]
            )
        )
        if not (link_heavy or annotated_index or cards or landing):
            return False
        if not parsed["issues"]:
            return True
        regions = parsed.get("unresolved_regions", [])
        badges = regions and all(
            re.search(
                r"(?:badge|shields\.io|visitor|sponsor)", region.get("source_url") or "", re.I,
            )
            for region in regions
        )
        # Multiple article previews may have thumbnails; a lone teaching diagram stays pending.
        return bool(set(parsed["issues"]) == {"html_nontext_content_pending"} and (
            badges or (cards or dense_index) and regions
            and all(region["kind"] == "img" for region in regions)
        ))


def content_format(content, content_type, expected=None):
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if content.startswith(b"%PDF-"):
        actual = "pdf"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        actual = "png"
    elif content.startswith(b"\xff\xd8\xff"):
        actual = "jpeg"
    elif content.startswith(b"PK") and (
        expected == "docx"
        or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        actual = "docx"
    elif content_type in {"text/html", "application/xhtml+xml"}:
        actual = "html"
    elif content_type in {"text/markdown", "text/x-markdown"}:
        actual = "markdown"
    elif content_type in {"text/plain", ""}:
        actual = "text"
    else:
        raise BusinessError("material_format_mismatch", "Source is not a supported document.")
    if expected is not None and actual != expected:
        raise BusinessError("material_format_mismatch", "Source changed its declared format.")
    return actual


def teaching_identity(parsed):
    blocks = [
        {key: block.get(key) for key in ("kind", "section_path", "source_page", "text")}
        for block in parsed["blocks"]
    ]
    value = {
        "blocks": blocks, "unresolved_regions": parsed["unresolved_regions"],
    } if parsed.get("unresolved_regions") else blocks
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
