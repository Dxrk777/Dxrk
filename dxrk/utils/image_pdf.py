# SPDX-License-Identifier: MIT
"""Naive byte-scanning PDF helpers: text extraction, page count, and metadata."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass

from dxrk.utils.image_format import _STR_PDF as _STR_PDF


class PDFError(Exception):
    """Base class for PDF-related errors."""


ErrNotPDF = PDFError("not a valid PDF file")
ErrPDFEncrypted = PDFError("PDF is encrypted")
ErrPageNotFound = PDFError("page not found")


@dataclass
class PDFMetadata:
    """PDF metadata. Mirrors image.PDFMetadata."""

    title: str = ""
    author: str = ""
    subject: str = ""
    creator: str = ""
    producer: str = ""
    creation_date: str = ""
    mod_date: str = ""
    pages: int = 0


def _read_all(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def extract_text(path: str) -> str:
    """Extract text from a PDF by scanning raw stream content."""
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    return _extract_text_from_bytes(data)


def _extract_text_from_bytes(data: bytes) -> str:
    text = io.StringIO()
    in_stream = False
    stream_start = 0

    for i in range(len(data) - 1):
        if data[i] == ord("s") and data[i + 1] == ord("t") and i + 5 < len(data) and data[i : i + 6] == b"stream":
            in_stream = True
            stream_start = i + 6
            if stream_start < len(data) and data[stream_start] == ord("\r"):
                stream_start += 1
            if stream_start < len(data) and data[stream_start] == ord("\n"):
                stream_start += 1
        elif (
            in_stream
            and data[i] == ord("e")
            and data[i + 1] == ord("n")
            and i + 8 < len(data)
            and data[i : i + 9] == b"endstream"
        ):
            stream_data = data[stream_start:i]
            decoded = _decode_stream(stream_data)
            text.write(decoded)
            in_stream = False

    return text.getvalue()


def _decode_stream(data: bytes) -> str:
    """Decode PDF literal string escapes within a stream. Mirrors image.decodeStream."""
    result = bytearray()
    i = 0
    while i < len(data):
        if data[i] == ord("\\") and i + 1 < len(data):
            nxt = data[i + 1]
            if nxt == ord("n"):
                result.append(ord("\n"))
            elif nxt == ord("r"):
                result.append(ord("\r"))
            elif nxt == ord("t"):
                result.append(ord("\t"))
            elif nxt == ord("("):
                result.append(ord("("))
            elif nxt == ord(")"):
                result.append(ord(")"))
            elif nxt == ord("\\"):
                result.append(ord("\\"))
            else:
                if i + 3 < len(data) and _is_octal(data[i + 1]) and _is_octal(data[i + 2]) and _is_octal(data[i + 3]):
                    val = ((data[i + 1] - ord("0")) << 6) | ((data[i + 2] - ord("0")) << 3) | (data[i + 3] - ord("0"))
                    result.append(val & 0xFF)
                    i += 2
                else:
                    result.append(data[i + 1])
            i += 2
        elif 32 <= data[i] <= 126:
            result.append(data[i])
            i += 1
        else:
            i += 1
    return result.decode("latin-1")


def _is_octal(b: int) -> bool:
    return ord("0") <= b <= ord("7")


def get_page_count(path: str) -> int:
    """Return the max "/Count N" value found in a PDF."""
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    count = 0
    for i in range(len(data) - 7):
        if data[i : i + 7] == b"/Count ":
            j = i + 7
            while j < len(data) and ord("0") <= data[j] <= ord("9"):
                j += 1
            if j > i + 7:
                c = int(data[i + 7 : j])
                count = max(count, c)
    return count


def get_metadata(path: str) -> PDFMetadata:
    """Extract basic metadata from a PDF (title, author, subject, ...)."""
    meta = PDFMetadata()
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    meta.pages, _ = _page_count_from_bytes(data)

    fields = {
        "/Title": "title",
        "/Author": "author",
        "/Subject": "subject",
        "/Creator": "creator",
        "/Producer": "producer",
        "/CreationDate": "creation_date",
        "/ModDate": "mod_date",
    }

    for field, attr in fields.items():
        idx = _find_field(data, field)
        if idx >= 0:
            start = data.find(b"(", idx + len(field))
            if start >= 0:
                end = _find_end_of_string(data, start)
                if end > start:
                    setattr(meta, attr, data[start : end + 1].decode("latin-1"))

    return meta


def _page_count_from_bytes(data: bytes) -> tuple[int, Exception | None]:
    """GetPageCount over raw bytes; returns (count, error-or-None)."""
    try:
        return get_page_count(_bytes_to_temp(data)), None
    except Exception as exc:  # noqa: BLE001 - defer/recover style cleanup in GetMetadata
        return 0, exc


def _bytes_to_temp(data: bytes) -> str:
    """Write bytes to a temp file and return its path (for parity re-reads)."""
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def _find_field(data: bytes, field: str) -> int:
    field_bytes = field.encode("ascii")
    for i in range(len(data) - len(field_bytes) + 1):
        if data[i : i + len(field_bytes)] == field_bytes:
            return i
    return -1


def _find_end_of_string(data: bytes, start: int) -> int:
    paren = 0
    in_string = False
    for i in range(start, len(data)):
        if data[i] == ord("(") and (i == start or data[i - 1] != ord("\\")):
            if not in_string:
                in_string = True
                continue
            paren += 1
        elif data[i] == ord(")") and (i == 0 or data[i - 1] != ord("\\")):
            if paren > 0:
                paren -= 1
            elif in_string:
                return i
    return -1


def render_page(path: str, page_num: int, dpi: int) -> bytes:
    """Not implemented (requires an external library)."""
    raise ValueError("PDF rendering not implemented (requires external library)")


def extract_images(path: str) -> list[bytes]:
    """Not implemented (requires an external library)."""
    raise ValueError("PDF image extraction not implemented (requires external library)")


def is_pdf_encrypted(path: str) -> bool:
    """Return True if the PDF contains an /Encrypt entry."""
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    for i in range(len(data) - 8):
        if data[i : i + 9] == b"/Encrypt ":
            return True
    return False


def validate_pdf(path: str) -> None:
    """Validate that a PDF has an %%EOF marker. Raises ErrNotPDF or ValueError."""
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    if _has_eof_marker(data):
        return

    raise ValueError("PDF missing EOF marker (possibly truncated)")


def _has_eof_marker(data: bytes) -> bool:
    start = max(0, len(data) - 1024)
    for i in range(start, len(data)):
        if i + 5 <= len(data) and data[i : i + 5] == b"%%EOF":
            return True
    return False


def get_pdf_version(path: str) -> str:
    """Return the PDF header version (e.g. "1.4")."""
    with open(path, "rb") as f:
        header = f.read(8)

    if len(header) >= 8 and header[:5] == _STR_PDF.encode("ascii"):
        return header[5:8].decode("ascii")
    raise ErrNotPDF
