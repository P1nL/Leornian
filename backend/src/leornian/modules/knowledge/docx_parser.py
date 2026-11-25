import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree

from leornian.shared_kernel.errors import BusinessError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def read_part(archive, name):
    try:
        entry = archive.getinfo(name)
        if entry.file_size > 40_000_000:
            raise BusinessError("material_parser_limit", "Office XML exceeds parser memory.")
        content = archive.read(name)
    except (KeyError, zipfile.BadZipFile):
        raise BusinessError(
            "material_format_mismatch", "Office source part is unavailable."
        ) from None
    if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
        raise BusinessError("material_format_mismatch", "Office XML cannot declare entities.")
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError:
        raise BusinessError("material_format_mismatch", "Office XML is invalid.") from None


def relationships(archive):
    name = "word/_rels/document.xml.rels"
    if name not in archive.namelist():
        return {}
    return {
        item.attrib["Id"]: item.attrib
        for item in read_part(archive, name).findall(REL + "Relationship")
    }


def image_part(relationship):
    if relationship.get("TargetMode") == "External":
        return None
    value = relationship.get("Target", "")
    path = posixpath.normpath(posixpath.join("word", value))
    if not path.startswith("word/media/") or "\\" in path or ":" in path:
        return None
    return path


def parse_docx(content):
    from PIL import Image

    from leornian.modules.knowledge.file_parser import _assemble, image_regions

    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise BusinessError("material_format_mismatch", "Source is not an Office document.")
    blocks, pages, issues, section = [], [], [], []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if (
                len(archive.infolist()) > 20000
                or sum(entry.file_size for entry in archive.infolist()) > 100_000_000
            ):
                raise BusinessError(
                    "material_parser_limit", "Office package exceeds parser memory."
                )
            document = read_part(archive, "word/document.xml")
            rels = relationships(archive)

            def text_part(text, kind, locator):
                if not text.strip():
                    return
                number = len(pages) + 1
                pages.append(
                    dict(
                        number=number,
                        method="embedded_text",
                        requires_ocr=False,
                        reason_code=None,
                        original_part=locator,
                        location_basis="document_part",
                    )
                )
                blocks.append(
                    dict(
                        kind=kind,
                        section_path=list(section),
                        text=text,
                        source_page=number,
                    )
                )

            def media(relationship_id):
                name = image_part(rels.get(relationship_id, {}))
                if not name or name not in archive.namelist():
                    issues.append("docx_external_or_missing_image")
                    return
                raw = archive.read(name)
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format not in {"PNG", "JPEG"}:
                            issues.append("docx_image_conversion_pending")
                            return
                        width, height = image.size
                        image.verify()
                except (OSError, ValueError, Image.DecompressionBombError):
                    issues.append("docx_image_invalid")
                    return
                for region in image_regions(width, height):
                    pages.append(
                        dict(
                            number=len(pages) + 1,
                            method="none",
                            requires_ocr=True,
                            reason_code="docx_image_ocr",
                            region=region,
                            original_part=name,
                            location_basis="document_part",
                        )
                    )
                issues.append("docx_image_ocr_pending")

            def paragraph(element, locator):
                nonlocal section
                style = element.find(W + "pPr/" + W + "pStyle")
                style_id = style.get(W + "val", "") if style is not None else ""
                heading = re.fullmatch(r"Heading([1-6])", style_id, re.IGNORECASE)
                code = "code" in style_id.casefold() or any(
                    font.get(W + "ascii", "").casefold() in {"consolas", "courier new", "menlo"}
                    for font in element.iter(W + "rFonts")
                )
                fragments = []
                for item in element.iter():
                    if item.tag == W + "t":
                        fragments.append(item.text or "")
                    elif item.tag == W + "tab":
                        fragments.append("\t")
                    elif item.tag in {W + "br", W + "cr"}:
                        fragments.append("\n")
                    elif item.tag == A + "blip":
                        text_part("".join(fragments), "code" if code else "paragraph", locator)
                        fragments = []
                        media(item.get(R + "embed") or item.get(R + "link"))
                    elif item.tag.endswith("}chart") or item.tag == W + "object":
                        issues.append("docx_embedded_object_pending")
                    elif item.tag == W + "hyperlink":
                        relationship = rels.get(item.get(R + "id"), {})
                        target = relationship.get("Target")
                        if target:
                            fragments.append("[link: " + target + "] ")
                    elif item.tag.endswith("}oMath"):
                        fragments.append(ElementTree.tostring(item, encoding="unicode"))
                value = "".join(fragments)
                if heading and value.strip():
                    section = section[: int(heading[1]) - 1] + [value.strip()]
                text_part(value, "heading" if heading else "code" if code else "paragraph", locator)

            def table(element, locator):
                rows = []
                for row in element.findall(W + "tr"):
                    cells = []
                    for cell in row.findall(W + "tc"):
                        values = []
                        for item in cell:
                            if item.tag == W + "p":
                                values.append(
                                    "".join(
                                        "\t"
                                        if node.tag == W + "tab"
                                        else "\n"
                                        if node.tag in {W + "br", W + "cr"}
                                        else node.text or ""
                                        if node.tag == W + "t"
                                        else ""
                                        for node in item.iter()
                                    )
                                )
                            elif item.tag == W + "tbl":
                                issues.append("docx_nested_table_pending")
                        cells.append("\n".join(values))
                        for image in cell.iter(A + "blip"):
                            media(image.get(R + "embed") or image.get(R + "link"))
                    rows.append("\t".join(cells))
                text_part("\n".join(rows), "table", locator)

            body = document.find(W + "body")
            if body is None:
                raise BusinessError("material_format_mismatch", "Office source body is missing.")

            def walk(element, path):
                for index, child in enumerate(element):
                    locator = f"{path}/{index}"
                    if child.tag == W + "p":
                        paragraph(child, locator)
                    elif child.tag == W + "tbl":
                        table(child, locator)
                    elif child.tag == W + "altChunk":
                        issues.append("docx_embedded_document_pending")
                    elif child.tag in {W + "sdt", W + "sdtContent", W + "customXml"}:
                        walk(child, locator)

            walk(body, "word/document.xml#body")
            for name in ("word/footnotes.xml", "word/endnotes.xml"):
                if name in archive.namelist():
                    walk(read_part(archive, name), name)
                    for note in read_part(archive, name):
                        if int(note.get(W + "id", "0")) > 0:
                            walk(note, name + "#" + note.get(W + "id", "0"))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise BusinessError(
            "material_format_mismatch", "Office source could not be read."
        ) from None
    return _assemble(
        blocks,
        pages=pages,
        issues=issues + ([] if blocks or pages else ["empty_body"]),
        parser_version="docx-exact-parts.v1",
        complete=True,
    )


def render_docx_image(content, number):
    import base64

    from PIL import Image

    parsed = parse_docx(content)
    pages = {page["number"]: page for page in parsed["pages"]}
    page = pages.get(number)
    if not page or not page.get("requires_ocr"):
        raise BusinessError("material_page_limit", "Office image part is outside its bounds.")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        raw = archive.read(page["original_part"])
    with Image.open(io.BytesIO(raw)) as image:
        with image.crop(page["region"]).convert("RGB") as region:
            output = io.BytesIO()
            region.save(output, format="PNG")
    return {"image": base64.b64encode(output.getvalue()).decode("ascii")}
