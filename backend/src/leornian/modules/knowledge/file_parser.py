"""Bounded deterministic extraction. Originals never pass through a renderer or a model."""

import io
import json
import logging
import os
import re
import subprocess
import sys
from html.parser import HTMLParser

from leornian.modules.knowledge.file_contracts import MAX_FILE_BYTES
from leornian.modules.knowledge.materials import MAX_BLOCKS, parse_blocks
from leornian.shared_kernel.errors import BusinessError

MAX_TEXT_BYTES = 2_000_000
MAX_PDF_PAGES = 100000
PARSER_SECONDS = 60
HTML_MAIN_PARSER_VERSION = "html-main-text.v8"


def html_chrome(tag, attributes):
    classes = set((attributes.get("class") or "").split())
    label = (attributes.get("aria-label") or attributes.get("title") or "").strip().casefold()
    return (
        tag in {"nav", "footer", "aside"}
        or attributes.get("role") in {"navigation", "contentinfo"}
        or attributes.get("aria-hidden") == "true"
        or "hidden" in attributes
        or bool(re.search(
            r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)"
            r"\s*(?:!important)?\s*(?:;|$)",
            attributes.get("style") or "", re.I,
        ))
        or bool(classes & {
            "article-footer", "breadcrumbs", "table-of-contents", "recommendations",
        })
        or (tag == "button" and (
            bool(classes & {"copy-button", "copy-code", "code-copy", "copy-to-clipboard"})
            or label in {"copy", "copy code", "copy code to clipboard", "复制", "复制代码"}
        ))
    )


class HtmlText(HTMLParser):
    def __init__(self, *, main_content=False):
        super().__init__(convert_charrefs=True)
        self.blocks, self.parts, self.path = [], [], []
        self.kind, self.heading_depth = "paragraph", 0
        self.pre, self.table, self.skip = False, False, None
        self.issues, self.unresolved_regions = [], []
        self.main_content, self.skip_depth = main_content, 0

    def flush(self):
        text = "".join(self.parts)
        if not self.pre:
            text = text.strip()
        if text.strip():
            if self.heading_depth:
                self.path = self.path[: self.heading_depth - 1] + [text]
            self.blocks.append(dict(kind=self.kind, section_path=list(self.path), text=text))
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag == self.skip:
                self.skip_depth += 1
            return
        attributes = dict(attrs)
        if self.main_content and html_chrome(tag, attributes):
            if tag not in {"img", "br", "hr", "input", "meta", "link", "source", "embed"}:
                self.skip, self.skip_depth = tag, 1
            return
        decorative = (
            attributes.get("aria-hidden") == "true" or attributes.get("role") == "presentation"
        )
        nontext = tag in {"svg", "canvas", "iframe", "math", "img", "object", "embed"}
        if nontext and not decorative and not (
            tag == "img" and "alt" in attributes and not (attributes["alt"] or "").strip()
        ):
            self.flush()
            self.issues.append("html_nontext_content_pending")
            self.unresolved_regions.append({
                "ordinal": len(self.unresolved_regions), "kind": tag,
                "label": attributes.get("alt") or attributes.get("title") or "",
                "source_url": attributes.get("src") or attributes.get("data"),
                "section_path": list(self.path), "after_block": len(self.blocks),
            })
        if tag in {"script", "style", "head", "template", "iframe", "svg", "canvas", "math"} or (
            self.main_content and tag in {"nav", "footer"}
        ):
            self.skip, self.skip_depth = tag, 1
            return
        if self.table:
            if tag == "tr" and self.parts:
                self.parts.append("\n")
            elif tag in {"td", "th"} and self.parts and self.parts[-1] != "\n":
                self.parts.append("\t")
            return
        if tag in {"p", "div", "section", "article", "li", "pre", "table"} or re.fullmatch(
            r"h[1-6]", tag
        ):
            self.flush()
            self.heading_depth = int(tag[1]) if re.fullmatch(r"h[1-6]", tag) else 0
            self.pre, self.table = tag == "pre", tag == "table"
            self.kind = (
                "heading"
                if self.heading_depth
                else "code"
                if self.pre
                else "table"
                if self.table
                else "paragraph"
            )
        elif tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip:
                self.skip_depth -= 1
                if not self.skip_depth:
                    self.skip = None
            return
        if self.table and tag != "table":
            return
        if tag in {"p", "div", "section", "article", "li", "pre", "table"} or re.fullmatch(
            r"h[1-6]", tag
        ):
            self.flush()
            self.pre, self.table, self.heading_depth, self.kind = False, False, 0, "paragraph"

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data if self.pre else re.sub(r"[ \r\n\f\v]+", " ", data))


def _assemble(
    blocks,
    *,
    pages=(),
    issues=(),
    parser_version,
    basis="extracted_text",
    complete=False,
    unresolved_regions=(),
):
    if len(blocks) > MAX_BLOCKS:
        raise BusinessError("material_block_limit", "Split material into fewer blocks.")
    parts, offset = [], 0
    for block in blocks:
        text = block["text"]
        block["start"], block["end"] = offset, offset + len(text)
        parts.append(text + "\n\n")
        offset += len(text) + 2
    text = "".join(parts)
    if len(text.encode("utf-8")) > (MAX_FILE_BYTES if complete else MAX_TEXT_BYTES):
        raise BusinessError(
            "material_text_limit", "Extracted text must be split into smaller imports."
        )
    return dict(
        text=text,
        blocks=blocks,
        pages=list(pages),
        issues=sorted(set(issues)),
        parser_version=parser_version,
        text_basis=basis,
        unresolved_regions=list(unresolved_regions),
    )


class HtmlMain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active, self.sections = [], []

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        for item in self.active:
            item["parts"].append(raw)
            if tag == item["tag"]:
                item["depth"] += 1
        attributes = dict(attrs)
        labels = set(re.split(r"[\s_]+", (
            attributes.get("class", "") + " " + attributes.get("id", "")
        ).casefold()))
        markers = {
            "post-content", "postcontent", "article-content", "articlecontent",
            "markdown-body", "theme-default-content", "vp-doc", "entry-content",
            "content", "content-body", "readme", "markdown",
        }
        content = {
            marker for marker in markers
            if any(label == marker or (
                marker != "content" and label.endswith("-" + marker)
            ) for label in labels)
        }
        if attributes.get("itemprop") == "articleBody":
            content.add("article-body")
        if tag in {"main", "article"} or attributes.get("role") == "main" or content:
            self.active.append(
                {
                    "tag": tag,
                    "depth": 1,
                    "main": tag == "main" or attributes.get("role") == "main",
                    "within_main": any(section["main"] for section in self.active),
                    "content": bool(content),
                    "parts": [],
                }
            )

    def handle_startendtag(self, tag, attrs):
        self.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        for item in list(self.active):
            if tag == item["tag"]:
                item["depth"] -= 1
                if item["depth"] == 0:
                    self.sections.append(item)
                    self.active.remove(item)
                    continue
            item["parts"].append(f"</{tag}>")

    def append(self, value):
        for item in self.active:
            item["parts"].append(value)

    def handle_data(self, value):
        self.append(value)

    def handle_entityref(self, value):
        self.append("&" + value + ";")

    def handle_charref(self, value):
        self.append("&#" + value + ";")


def main_html(text):
    from lxml import etree, html
    from readability import Document
    from readability.readability import Unparseable

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    marker = "data-leornian-source-node"
    try:
        original = html.document_fromstring(text, parser=html.HTMLParser(no_network=True))
        nodes = {}
        for index, node in enumerate(original.iter()):
            if isinstance(node.tag, str):
                node.set(marker, str(index))
                nodes[str(index)] = node
        summary = Document(html.tostring(original, encoding="unicode")).summary(
            html_partial=True, keep_all_images=True,
        )
        extracted = html.fromstring(summary)
    except (etree.ParserError, Unparseable):
        return _fallback_main_html(text)

    selected = []
    for node in extracted.iter():
        key = node.get(marker)
        if key in nodes and nodes[key].tag in {"html", "body"}:
            return _fallback_main_html(text)
        if key in nodes and node.tag not in {"html", "body"} and not any(
            parent.get(marker) in nodes and parent.tag not in {"html", "body"}
            for parent in node.iterancestors()
        ):
            selected.append(nodes[key])
    if not selected:
        return _fallback_main_html(text)

    for index, node in enumerate(selected):
        articles = node.xpath(".//article[not(ancestor::article)]")
        if len(articles) == 1 and (
            len(articles[0].text_content().strip()) * 2 >= len(node.text_content().strip())
        ):
            selected[index] = articles[0]

    # Use Readability's region selection, not its rewritten code, tables or diagrams.
    for node in list(selected):
        container = next((
            parent for parent in (node, *node.iterancestors())
            if parent.tag in {"main", "article"} or parent.get("role") == "main"
        ), None)
        headings = [
            heading for heading in container.iter("h1")
            if not any(html_chrome(parent.tag, parent.attrib)
                       for parent in (heading, *heading.iterancestors()))
        ] if container is not None else []
        if len(headings) == 1 and not any(
            root is headings[0] or root in headings[0].iterancestors() for root in selected
        ) and int(headings[0].get(marker)) < int(node.get(marker)):
            selected.append(headings[0])
    selected.sort(key=lambda node: int(node.get(marker)))
    for node in original.iter():
        if isinstance(node.tag, str):
            node.attrib.pop(marker, None)
    return "<div>" + "".join(
        html.tostring(node, encoding="unicode", with_tail=False) for node in selected
    ) + "</div>"


def _fallback_main_html(text):
    document = HtmlMain()
    document.feed(text)
    document.close()
    candidates = [(text, 0.35)]
    candidates.extend(
        ("".join(item["parts"]), 1.5 if item["within_main"] and item["tag"] == "article"
         else 1.2 if item["content"] else 1.0)
        for item in document.sections
    )

    def score(candidate):
        body, preference = candidate
        parsed = HtmlText(main_content=True)
        parsed.feed(body)
        parsed.flush()
        meaningful = sum(len(block["text"]) for block in parsed.blocks)
        structure = sum(
            min(len(block["text"]), 2000)
            for block in parsed.blocks if block["kind"] in {"code", "table"}
        )
        # Small recommendation cards must not displace a substantial article.
        links = len(re.findall(r"<a(?:\s|>)", body, re.I))
        return preference * (meaningful + structure) / (1 + links / max(meaningful / 80, 1))

    return max(candidates, key=score)[0]


class EmbeddedSource(HTMLParser):
    """Read repository source data without executing the page's scripts."""

    def __init__(self):
        super().__init__()
        self.active, self.parts, self.source, self.path = False, [], None, ""

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("data-target") == "react-app.embeddedData"
            self.parts = []

    def handle_data(self, value):
        if self.active:
            self.parts.append(value)

    def handle_endtag(self, tag):
        if tag != "script" or not self.active:
            return
        self.active = False
        try:
            payload = json.loads("".join(self.parts)).get("payload", {})
            blob = payload.get("codeViewBlobLayoutRoute.StyledBlob", payload.get("blob", {}))
            lines = blob.get("rawLines")
            if isinstance(lines, list) and lines and all(isinstance(line, str) for line in lines):
                self.source = "\n".join(lines)
                self.path = payload.get("codeViewBlobLayoutRoute.blob", {}).get(
                    "path", payload.get("blob", {}).get("path", ""),
                )
        except (ValueError, AttributeError):
            return


def parse_file(content, format):
    if not content or len(content) > MAX_FILE_BYTES:
        raise BusinessError("material_file_limit", "Material exceeds the file limit.")
    if format == "pdf":
        return _pdf(content)
    if format == "docx":
        from leornian.modules.knowledge.docx_parser import parse_docx

        return parse_docx(content)
    if format in {"png", "jpeg"}:
        from PIL import Image

        try:
            with Image.open(io.BytesIO(content)) as image:
                if image.format != ("PNG" if format == "png" else "JPEG"):
                    raise ValueError("image_format")
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise BusinessError(
                "material_format_mismatch", "Image is not a valid source."
            ) from None
        with Image.open(io.BytesIO(content)) as image:
            regions = page_image_regions(*image.size)
        return _assemble(
            [],
            pages=[
                dict(
                    number=i,
                    method="none",
                    requires_ocr=True,
                    reason_code="image_ocr",
                    region=region,
                    location_basis="image_region",
                )
                for i, region in enumerate(regions, 1)
            ],
            issues=["image_ocr_pending"],
            parser_version="image-original.v2",
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise BusinessError(
            "material_encoding_required", "Text and HTML uploads require UTF-8."
        ) from None
    if len(content) > MAX_FILE_BYTES or "\x00" in text:
        raise BusinessError("material_text_limit", "Text is too large or contains binary data.")
    if format in {"html", "html-main"}:
        embedded = EmbeddedSource()
        if format == "html-main":
            embedded.feed(text)
        if embedded.source is not None:
            markdown = not embedded.path or embedded.path.lower().endswith((".md", ".markdown"))
            issues = []
            if markdown:
                try:
                    blocks = parse_blocks(embedded.source, True)
                except BusinessError as error:
                    if error.code != "precondition_failed":
                        raise
                    blocks = parse_blocks(embedded.source, False)
                    issues.append("markdown_fence_incomplete")
            else:
                blocks = [{"kind": "code", "section_path": [], "text": embedded.source}]
            regions = []
            for index, block in enumerate(blocks):
                if block["kind"] == "code":
                    continue
                html = HtmlText(main_content=True)
                html.feed(block["text"])
                found = [*html.unresolved_regions, *(
                    {"kind": "img", "label": match.group(1), "source_url": match.group(2)}
                    for match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", block["text"])
                )]
                for region in found:
                    regions.append({
                        **region, "ordinal": len(regions), "section_path": block["section_path"],
                        "after_block": index,
                    })
            return _assemble(
                blocks, unresolved_regions=regions,
                issues=issues + (["html_nontext_content_pending"] if regions else [])
                + ([] if blocks else ["empty_body"]),
                parser_version=HTML_MAIN_PARSER_VERSION, complete=True,
            )
        parser = HtmlText(main_content=format == "html-main")
        parser.feed(main_html(text) if format == "html-main" else text)
        parser.close()
        parser.flush()
        issues = parser.issues + ([] if parser.blocks else ["empty_body"])
        if format == "html-main" and (
            "Repository navigation" in "".join(block["text"] for block in parser.blocks)
            and not any(block["kind"] == "code" for block in parser.blocks)
        ):
            issues.append("source_body_missing")
        return _assemble(
            parser.blocks,
            issues=issues,
            unresolved_regions=parser.unresolved_regions,
            parser_version=HTML_MAIN_PARSER_VERSION if format == "html-main" else "html-text.v1",
            complete=True,
        )
    issues = []
    try:
        blocks = parse_blocks(text, format == "markdown")
    except BusinessError as error:
        if error.code != "precondition_failed":
            raise
        blocks = parse_blocks(text, False)
        issues = ["markdown_fence_incomplete"]
    return dict(
        text=text,
        blocks=blocks,
        pages=[],
        issues=issues + ([] if blocks else ["empty_body"]),
        parser_version="exact-text.markdown-fallback.v1" if issues else "exact-text.v1",
        text_basis="source_text",
    )


def _pdf(content, page_start=1, page_end=None):
    from pypdf import PdfReader, apply_configuration
    from pypdf.errors import LimitReachedError, PdfReadError

    if not content.startswith(b"%PDF-"):
        raise BusinessError("material_format_mismatch", "Upload is not a PDF document.")
    blocks, pages, issues = [], [], []
    try:
        with apply_configuration(
            maximum_declared_stream_length=10_000_000,
            array_based_stream_maximum_output_length=10_000_000,
            lzw_maximum_output_length=10_000_000,
            run_length_maximum_output_length=10_000_000,
            zlib_maximum_output_length=10_000_000,
            stream_decoding_work_maximum_length=30_000_000,
            page_tree_maximum_entries=MAX_PDF_PAGES * 4,
            page_tree_maximum_page_entries=MAX_PDF_PAGES,
        ):
            reader = PdfReader(
                io.BytesIO(content), strict=True, xref_stream_maximum_entries=100_000
            )
            if reader.is_encrypted:
                raise BusinessError("material_encrypted", "Provide an unencrypted authorized PDF.")
            count = len(reader.pages)
            end = min(page_end or count, count)
            if not 1 <= page_start <= end:
                raise BusinessError("material_page_limit", "PDF range is outside its bounds.")
            total = 0
            for number in range(page_start, end + 1):
                page = reader.pages[number - 1]
                value = page.extract_text(extraction_mode="layout", layout_mode_strip_rotated=False)
                total += len(value.encode("utf-8"))
                if total > MAX_TEXT_BYTES:
                    raise BusinessError("material_text_limit", "Split the extracted PDF text.")
                meaningful = sum(ch.isalnum() for ch in value)
                bad = "\ufffd" in value or "\x00" in value
                needs_ocr = meaningful < 8 or bad
                if needs_ocr:
                    issues.append("pdf_ocr_pending")
                pages.append(
                    dict(
                        number=number,
                        method="embedded_text" if value.strip() else "none",
                        requires_ocr=needs_ocr,
                        reason_code="pdf_text_quality"
                        if bad
                        else "pdf_text_sparse"
                        if needs_ocr
                        else None,
                    )
                )
                # Even questionable extracted text stays distinct from any later OCR result.
                if "\x00" not in value:
                    blocks.extend(
                        {**block, "source_page": number} for block in parse_blocks(value, False)
                    )
    except LimitReachedError:
        raise BusinessError(
            "material_pdf_limit", "PDF exceeds safe parser capacity; split it."
        ) from None
    except (PdfReadError, ValueError, KeyError, TypeError, RecursionError):
        raise BusinessError("material_pdf_invalid", "PDF could not be extracted safely.") from None
    return _assemble(
        blocks,
        pages=pages,
        issues=issues,
        parser_version="pypdf-6.21.4.layout.v1",
    )


def extract_file(content, format):
    # No model, database, proxy or application secrets enter the parser process.
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "VIRTUAL_ENV")
        if key in os.environ
    }
    environment["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "leornian.modules.knowledge.file_parser", format],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=PARSER_SECONDS,
            env=environment,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        raise BusinessError(
            "material_parser_timeout", "Split the document into smaller uploads."
        ) from None
    if result.returncode != 0 or len(result.stdout) > MAX_FILE_BYTES * 8:
        raise BusinessError("material_parser_limit", "Parser could not complete within its limits.")
    output = json.loads(result.stdout)
    if "error" in output:
        raise BusinessError(
            output["error"], "Material needs a different source or processing strategy."
        )
    return output


def render_pdf_page(content, page_number):
    import base64

    import pypdfium2

    try:
        with pypdfium2.PdfDocument(content) as document:
            if not 1 <= page_number <= min(len(document), MAX_PDF_PAGES):
                raise BusinessError("material_page_limit", "PDF page is outside its bounds.")
            page = document[page_number - 1]
            width, height = page.get_size()
            scale = min(2, 2200 / max(width, height))
            if scale <= 0:
                raise ValueError("invalid_page_size")
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            output = io.BytesIO()
            image.save(output, format="PNG")
            image.close()
            bitmap.close()
            page.close()
            if len(output.getvalue()) > 8_000_000:
                raise BusinessError("material_file_limit", "Split the page image.")
            return {"image": base64.b64encode(output.getvalue()).decode("ascii")}
    except BusinessError:
        raise
    except (ValueError, RuntimeError, pypdfium2.PdfiumError):
        raise BusinessError("material_pdf_invalid", "PDF page could not be rendered.") from None


def pdf_metadata(content, *, include_outline=False):
    from pypdf import PdfReader
    from pypdf.errors import LimitReachedError, PdfReadError

    try:
        with PdfReader(
            io.BytesIO(content), strict=True, xref_stream_maximum_entries=100_000
        ) as document:
            if document.is_encrypted:
                raise BusinessError("material_encrypted", "Provide an unencrypted authorized PDF.")
            count = len(document.pages)
            if count > MAX_PDF_PAGES:
                raise BusinessError(
                    "material_pdf_limit", "PDF exceeds its supported page capacity."
                )
            result = {"page_count": count}
            if include_outline:
                outline = []

                def visit(items, depth=0):
                    for item in items:
                        if len(outline) >= 500 or depth > 20:
                            return
                        if isinstance(item, list):
                            visit(item, depth + 1)
                            continue
                        page = document.get_destination_page_number(item)
                        if page is not None:
                            outline.append({
                                "title": str(item.title)[:300], "page": page + 1, "depth": depth,
                            })

                visit(document.outline)
                result["outline"] = outline
            return result
    except LimitReachedError:
        raise BusinessError("material_pdf_limit", "PDF exceeds safe parser capacity.") from None
    except (ValueError, PdfReadError, KeyError, TypeError, RecursionError):
        raise BusinessError("material_pdf_invalid", "PDF metadata is unavailable.") from None


def image_regions(width, height):
    return [
        [x, y, min(x + 1000, width), min(y + 1000, height)]
        for y in range(0, height, 1000)
        for x in range(0, width, 1000)
    ]


def page_image_regions(width, height):
    # Keep ordinary pages whole; bounded, balanced tiles avoid narrow edge strips.
    columns = (width + 2199) // 2200
    tile_width = (width + columns - 1) // columns
    max_height = min(2200, 2_500_000 // tile_width)
    rows = (height + max_height - 1) // max_height
    return [
        [
            column * width // columns,
            row * height // rows,
            (column + 1) * width // columns,
            (row + 1) * height // rows,
        ]
        for row in range(rows)
        for column in range(columns)
    ]


def render_image_region(content, number, region=None):
    import base64

    from PIL import Image

    try:
        with Image.open(io.BytesIO(content)) as image:
            if region is None:
                # Old numbered requests retain the original v1 grid.
                regions = image_regions(*image.size)
                if not 1 <= number <= len(regions):
                    raise BusinessError(
                        "material_page_limit", "Image region is outside its bounds."
                    )
                region = regions[number - 1]
            if (
                len(region) != 4
                or any(type(value) is not int for value in region)
                or not 0 <= region[0] < region[2] <= image.width
                or not 0 <= region[1] < region[3] <= image.height
            ):
                raise BusinessError("material_page_limit", "Image region is outside its bounds.")
            with image.crop(region).convert("RGB") as region:
                output = io.BytesIO()
                region.save(output, format="PNG")
        return {"image": base64.b64encode(output.getvalue()).decode("ascii")}
    except (OSError, ValueError, Image.DecompressionBombError):
        raise BusinessError("material_format_mismatch", "Image region could not be read.") from None


def _limit_process():
    if os.name != "nt":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (PARSER_SECONDS, PARSER_SECONDS))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working", ctypes.c_size_t),
            ("max_working", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io", ctypes.c_uint64 * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t),
            ("peak_job", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x100 | 0x8  # Per-process memory and no child processes.
    limits.basic.active_processes = 1
    limits.process_memory = 512 * 1024**2
    if (
        not job
        or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
        or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(-1))
    ):
        raise BusinessError(
            "material_parser_unavailable", "Parser resource isolation is unavailable."
        )
    return job  # The handle lives until process exit.


def main():
    logging.disable(logging.CRITICAL)
    try:
        _limit_process()
        content = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise BusinessError("material_file_limit", "Split the original file.")
        mode = sys.argv[1]
        if mode == "pdf-metadata":
            output = pdf_metadata(content)
        elif mode == "pdf-outline":
            output = pdf_metadata(content, include_outline=True)
        elif mode.startswith("pdf-range:"):
            _, start, end = mode.split(":")
            output = _pdf(content, int(start), int(end))
        elif mode.startswith("docx-image:"):
            from leornian.modules.knowledge.docx_parser import render_docx_image

            output = render_docx_image(content, int(mode.split(":")[1]))
        elif mode.startswith("image-region:"):
            parts = mode.split(":")
            if len(parts) not in {2, 6}:
                raise BusinessError("material_page_limit", "Image region is outside its bounds.")
            output = render_image_region(
                content, int(parts[1]),
                [int(value) for value in parts[2:]] if len(parts) == 6 else None,
            )
        else:
            output = (
                render_pdf_page(content, int(mode.split(":")[1]))
                if mode.startswith("pdf-page:")
                else parse_file(content, mode)
            )
    except BusinessError as error:
        output = {"error": error.code}
    except (MemoryError, OSError):
        output = {"error": "material_parser_limit"}
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=True).encode("utf-8"))


if __name__ == "__main__":
    main()
