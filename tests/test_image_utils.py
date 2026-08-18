# SPDX-License-Identifier: MIT
"""Tests for dxrk.utils.image (format detection, codecs, cache, processor, PDF)."""

from __future__ import annotations

import io
import os
import sys
from datetime import timedelta

import pytest
from PIL import Image

from dxrk.utils import image as img

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def make_img():
    """Create a solid RGBA PIL image of the given size."""

    def _make(width: int = 16, height: int = 16, mode: str = "RGBA"):
        return Image.new(mode, (width, height), (200, 100, 50, 255))

    return _make


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (10, 20, 30, 255)).save(buf, "PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _gif_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("P", (8, 8), 1).save(buf, "GIF")
    return buf.getvalue()


def _webp_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buf, "WEBP")
    return buf.getvalue()


def _write_pdf(path, body: bytes, header: bytes = b"%PDF-1.4\n") -> None:
    with open(path, "wb") as f:
        f.write(header + body)


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


def test_format_string_mime_extension():
    assert img.Format.JPEG.string() == "jpeg"
    assert img.Format.PNG.string() == "png"
    assert img.Format.GIF.string() == "gif"
    assert img.Format.WEBP.string() == "webp"
    assert img.Format.UNKNOWN.string() == "unknown"

    assert img.Format.JPEG.mime() == "image/jpeg"
    assert img.Format.PNG.mime() == "image/png"
    assert img.Format.GIF.mime() == "image/gif"
    assert img.Format.WEBP.mime() == "image/webp"
    assert img.Format.UNKNOWN.mime() == "application/octet-stream"

    assert img.Format.JPEG.extension() == ".jpg"
    assert img.Format.PNG.extension() == ".png"
    assert img.Format.GIF.extension() == ".gif"
    assert img.Format.WEBP.extension() == ".webp"
    assert img.Format.UNKNOWN.extension() == ".bin"


def test_format_aliases_and_supported():
    assert img.JPEG is img.Format.JPEG
    assert img.PNG is img.Format.PNG
    assert img.GIF is img.Format.GIF
    assert img.WebP is img.Format.WEBP
    assert img.Unknown is img.Format.UNKNOWN
    assert img.SupportedFormats == [
        img.Format.JPEG,
        img.Format.PNG,
        img.Format.GIF,
        img.Format.WEBP,
    ]
    assert img.SupportedMIMEs["image/jpg"] is img.Format.JPEG
    assert img.SupportedExtensions[".jpeg"] is img.Format.JPEG


def test_format_error_str():
    err = img.FormatError("boom")
    assert str(err) == "image: boom"
    assert err.msg == "boom"
    assert str(img.ErrUnsupportedFormat) == "image: unsupported format"


def test_coerce_format():
    assert img._coerce_format(img.Format.PNG) is img.Format.PNG
    assert img._coerce_format(1) is img.Format.JPEG
    assert img._coerce_format(2) is img.Format.PNG
    assert img._coerce_format(3) is img.Format.GIF
    assert img._coerce_format(4) is img.Format.WEBP
    assert img._coerce_format(99) is img.Format.UNKNOWN


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def test_detect_format():
    assert img.detect_format(_png_bytes()) is img.Format.PNG
    assert img.detect_format(_jpeg_bytes()) is img.Format.JPEG
    assert img.detect_format(_gif_bytes()) is img.Format.GIF
    assert img.detect_format(_webp_bytes()) is img.Format.WEBP
    assert img.detect_format(b"") is img.Format.UNKNOWN
    assert img.detect_format(b"not enough bytes") is img.Format.UNKNOWN
    assert img.detect_format(b"random-garbage-data") is img.Format.UNKNOWN


def test_detect_format_from_reader():
    reader = io.BytesIO(_png_bytes())
    assert img.detect_format_from_reader(reader) is img.Format.PNG
    assert reader.tell() == 0  # reader not consumed

    reader = io.BytesIO(_jpeg_bytes())
    assert img.detect_format_from_reader(reader) is img.Format.JPEG


def test_detect_mime():
    assert img.detect_mime(_png_bytes()) == "image/png"
    assert img.detect_mime(_jpeg_bytes()) == "image/jpeg"
    assert img.detect_mime(_webp_bytes()) == "image/webp"
    assert img.detect_mime(b"junk") == "application/octet-stream"


def test_detect_mime_from_reader():
    reader = io.BytesIO(_gif_bytes())
    assert img.detect_mime_from_reader(reader) == "image/gif"
    assert reader.tell() == 0


def test_format_from_extension_and_mime():
    assert img.format_from_extension(".PNG") is img.Format.PNG
    assert img.format_from_extension("jpg") is img.Format.JPEG
    assert img.format_from_extension(".webp") is img.Format.WEBP
    assert img.format_from_extension(".txt") is img.Format.UNKNOWN

    assert img.format_from_mime("Image/PNG") is img.Format.PNG
    assert img.format_from_mime("image/gif") is img.Format.GIF
    assert img.format_from_mime("text/plain") is img.Format.UNKNOWN


def test_is_supported_format():
    assert img.is_supported_format(img.Format.JPEG)
    assert img.is_supported_format(img.Format.PNG)
    assert img.is_supported_format(img.Format.GIF)
    assert img.is_supported_format(img.Format.WEBP)
    assert not img.is_supported_format(img.Format.UNKNOWN)
    assert not img.is_supported_format(99)


# ---------------------------------------------------------------------------
# Decode / encode / conversion
# ---------------------------------------------------------------------------


def test_decode_and_decode_config(make_img):
    png = _png_bytes()
    decoded = img.decode(io.BytesIO(png))
    assert decoded.size == (8, 8)
    assert decoded.format == "PNG"

    config, fmt = img.decode_config(io.BytesIO(png))
    assert config.width == 8
    assert config.height == 8
    assert config.color_model == "RGBA"
    assert fmt == "png"


def test_encode_and_encode_to_bytes(make_img):
    im = make_img()
    buf = io.BytesIO()
    img.encode(buf, im.convert("RGB"), img.Format.JPEG, quality=80)
    assert buf.getvalue()[:3] == b"\xff\xd8\xff"

    png_bytes = img.encode_to_bytes(im, img.Format.PNG, quality=85)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    gif_bytes = img.encode_to_bytes(im.convert("P"), img.Format.GIF, quality=85)
    assert gif_bytes[:6] in (b"GIF87a", b"GIF89a")

    with pytest.raises(img.FormatError):
        img.encode(io.BytesIO(), im, img.Format.WEBP, quality=85)
    with pytest.raises(img.FormatError):
        img.encode(io.BytesIO(), im, img.Format.UNKNOWN, quality=85)


def test_encode_format(make_img):
    im = make_img()
    assert img.encode_format(im.convert("RGB"), img.Format.JPEG, 70)[:3] == b"\xff\xd8\xff"


def test_decode_format():
    decoded, fmt = img.decode_format(_png_bytes())
    assert fmt is img.Format.PNG
    assert decoded.size == (8, 8)

    with pytest.raises(img.FormatError):
        img.decode_format(b"garbage")
    with pytest.raises(img.FormatError):
        img.decode_format(_webp_bytes())


def test_resize(make_img):
    im = make_img(16, 8)
    resized = img.resize(im, 8, 4)
    assert resized.size == (8, 4)
    assert resized.mode == "RGBA"

    # Aspect-preserving when one dimension is 0.
    resized = img.resize(im, 0, 4)
    assert resized.size == (8, 4)

    resized = img.resize(im, 4, 0)
    assert resized.size == (4, 2)

    # No-op when both dimensions are 0.
    assert img.resize(im, 0, 0) is im

    # Same size returns the original.
    assert img.resize(im, 16, 8) is im


def test_resize_fit_and_fill(make_img):
    im = make_img(16, 8)

    # Fits within bounds -> returns original.
    assert img.resize_fit(im, 64, 64) is im

    fitted = img.resize_fit(im, 8, 8)
    assert fitted.size == (8, 4)

    filled = img.resize_fill(im, 8, 8)
    assert filled.size == (8, 8)


def test_crop(make_img):
    im = make_img(16, 16)
    cropped = img.crop(im, 2, 2, 4, 4)
    assert cropped.size == (4, 4)


def test_convert_functions(make_img):
    im = make_img()

    rgba = img.to_rgba(im)
    assert rgba.mode == "RGBA"
    assert img.to_rgba(rgba) is rgba

    nrgba = img.to_nrgba(im)
    assert nrgba.mode == "RGBA"
    assert img.to_nrgba(nrgba) is nrgba

    pal = img.to_paletted(im)
    assert pal.mode == "P"
    assert img.to_paletted(pal) is pal

    gray = img.to_grayscale(im)
    assert gray.mode == "L"
    assert img.to_grayscale(gray) is gray

    assert img.convert(im, img.Format.JPEG).mode == "RGBA"
    assert img.convert(im, img.Format.PNG).mode == "RGBA"
    assert img.convert(im, img.Format.GIF).mode == "P"
    assert img.convert(im, img.Format.UNKNOWN).mode == "RGBA"


def test_base64_roundtrip(make_img):
    im = make_img(8, 8)
    b64 = img.to_base64(im, img.Format.PNG, 85)
    assert b64.startswith("data:image/png;base64,")

    raw = img.to_base64_raw(im, img.Format.PNG, 85)
    assert not raw.startswith("data:")
    assert raw == b64.split(",", 1)[1]

    decoded, fmt = img.from_base64(raw)
    assert fmt is img.Format.PNG
    assert decoded.size == (8, 8)

    decoded, fmt = img.from_base64(b64)
    assert fmt is img.Format.PNG
    assert decoded.size == (8, 8)


def test_dimensions_bounds_colormodel(make_img):
    im = make_img(12, 7)
    assert img.get_dimensions(im) == (12, 7)
    assert img.get_bounds(im) == (0, 0, 12, 7)
    assert img.get_color_model(im) == "RGBA"


def test_mime_extension_helpers(tmp_path):
    png = tmp_path / "a.png"
    assert img.mime_from_extension(str(png)) == "image/png"
    assert img.mime_from_extension("noext") == ""
    assert img.extension_from_mime("image/png") == ".png"
    assert img.extension_from_mime("bogus/type") == ""


# ---------------------------------------------------------------------------
# ImageCache
# ---------------------------------------------------------------------------


def test_cache_set_get_delete(tmp_path):
    cache = img.ImageCache(max_size=10)
    key = str(tmp_path / "k")
    cache.set(key, b"data123", img.Format.PNG, 4, 4)

    data, fmt, w, h, ok = cache.get(key)
    assert ok is True
    assert data == b"data123"
    assert fmt is img.Format.PNG
    assert (w, h) == (4, 4)

    data, fmt, w, h, ok = cache.get("missing")
    assert ok is False
    assert fmt is img.Format.UNKNOWN

    assert cache.delete(key) is True
    assert cache.delete(key) is False


def test_cache_clear_stats_keys(tmp_path):
    cache = img.ImageCache()
    cache.set("a", b"1", img.Format.JPEG, 1, 1)
    cache.set("b", b"22", img.Format.PNG, 2, 2)

    assert sorted(cache.keys()) == ["a", "b"]
    stats = cache.stats()
    assert stats.entry_count == 2
    assert stats.total_size == 3
    assert stats.max_size == 100
    assert stats.max_age == timedelta(hours=24)

    cache.clear()
    assert cache.keys() == []
    assert cache.stats().entry_count == 0
    assert cache.stats().total_size == 0


def test_cache_evict_lru(tmp_path):
    cache = img.ImageCache(max_size=2)
    cache.set("a", b"1", img.Format.JPEG, 1, 1)
    cache.get("a")  # bump access count
    cache.set("b", b"2", img.Format.PNG, 1, 1)
    cache.set("c", b"3", img.Format.GIF, 1, 1)  # evicts "a"

    assert cache.get("a")[4] is False
    assert cache.get("b")[4] is True
    assert cache.get("c")[4] is True


def test_cache_prune_expired(tmp_path):
    cache = img.ImageCache(max_age=timedelta(seconds=10))
    cache.set("old", b"1", img.Format.JPEG, 1, 1)
    cache.set("new", b"2", img.Format.PNG, 1, 1)
    # Manually age the first entry.
    cache._entries["old"].created_at -= timedelta(hours=1)

    assert cache.prune_expired() == 1
    assert cache.get("old")[4] is False
    assert cache.get("new")[4] is True


def test_cache_defaults_and_invalid():
    cache = img.ImageCache(max_size=0)
    assert cache._max_size == 100
    assert cache._max_age == timedelta(hours=24)

    cache2 = img.ImageCache(max_age=timedelta(0))
    assert cache2._max_age == timedelta(hours=24)


# ---------------------------------------------------------------------------
# ImageProcessor
# ---------------------------------------------------------------------------


def test_processor_chain(make_img):
    proc = img.ImageProcessor(make_img(16, 8), img.Format.JPEG)
    assert proc.image().size == (16, 8)

    proc.resize(8, 4)
    assert proc.image().size == (8, 4)

    proc.crop(0, 0, 4, 4)
    assert proc.image().size == (4, 4)

    proc.grayscale()
    assert proc.image().mode == "L"

    out = proc.encode()
    assert out[:3] == b"\xff\xd8\xff"


def test_processor_rotate_and_blur(make_img):
    proc = img.ImageProcessor(make_img(8, 8), img.Format.PNG)
    proc.rotate(0.5)
    assert proc.image().size == (8, 8)

    proc2 = img.ImageProcessor(make_img(8, 8), img.Format.PNG)
    proc2.blur(1)
    assert proc2.image().size == (8, 8)

    # blur with radius <= 0 is a no-op
    proc3 = img.ImageProcessor(make_img(8, 8), img.Format.PNG)
    proc3.blur(0)
    assert proc3.image().size == (8, 8)


def test_processor_quality_format(make_img):
    proc = img.ImageProcessor(make_img(8, 8), img.Format.JPEG)
    assert proc.set_quality(150) is proc
    assert proc._quality == 100
    assert proc.set_quality(0) is proc
    assert proc._quality == 1
    assert proc.set_quality(50) is proc
    assert proc._quality == 50

    assert proc.set_format(img.Format.PNG) is proc
    assert proc._format is img.Format.PNG
    assert proc.set_format(img.Format.UNKNOWN) is proc
    assert proc._format is img.Format.UNKNOWN


def test_processor_encode_unsupported(make_img):
    proc = img.ImageProcessor(make_img(8, 8), img.Format.WEBP)
    with pytest.raises(ValueError, match="unsupported format"):
        proc.encode()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific file mode")
def test_processor_save(tmp_path, make_img):
    proc = img.ImageProcessor(make_img(8, 8), img.Format.PNG)
    path = tmp_path / "out.png"
    proc.save(str(path))
    assert path.exists()
    assert os.stat(path).st_mode & 0o777 == 0o644
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_math_helpers():
    assert img._cos(0) == 1.0
    assert img._sin(0) == 0.0
    assert abs(img._exp(0) - 1.0) < 1e-9
    kernel = img._gaussian_kernel(1)
    assert len(kernel) == 3
    assert all(len(row) == 3 for row in kernel)
    total = sum(sum(row) for row in kernel)
    assert abs(total - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------


def test_extract_text(tmp_path):
    pdf = tmp_path / "t.pdf"
    body = b"1 0 obj\n<<>>\nstream\n(Hello World)\nendstream\nendobj\n"
    _write_pdf(pdf, body)
    assert "Hello World" in img.extract_text(str(pdf))

    notpdf = tmp_path / "n.txt"
    notpdf.write_bytes(b"plain text")
    with pytest.raises(img.PDFError):
        img.extract_text(str(notpdf))


def test_decode_stream():
    assert img._decode_stream(b"\\n\\r\\t\\134") == "\n\r\t\\"
    assert img._decode_stream(b"\\(paren\\)") == "(paren)"
    assert img._decode_stream(b"\\101\\102") == "AB"
    assert img._decode_stream(b"\\x") == "x"
    assert img._decode_stream(b"plain text") == "plain text"
    assert img._decode_stream(b"\x01\x02") == ""


def test_is_octal():
    assert img._is_octal(ord("0"))
    assert img._is_octal(ord("7"))
    assert not img._is_octal(ord("8"))
    assert not img._is_octal(ord("a"))


def test_get_page_count(tmp_path):
    pdf = tmp_path / "p.pdf"
    _write_pdf(pdf, b"/Count 5\n/Count 2\n")
    assert img.get_page_count(str(pdf)) == 5

    notpdf = tmp_path / "n.txt"
    notpdf.write_bytes(b"junk")
    with pytest.raises(img.PDFError):
        img.get_page_count(str(notpdf))


def test_get_metadata(tmp_path):
    pdf = tmp_path / "m.pdf"
    body = (
        b"/Title (My Doc)\n/Author (Dxrk)\n/Subject (Testing)\n"
        b"/Creator (Writer)\n/Producer (Producer X)\n/CreationDate (D:20260101)\n"
        b"/ModDate (D:20260202)\n/Count 3\n"
    )
    _write_pdf(pdf, body)
    meta = img.get_metadata(str(pdf))
    assert meta.title == "(My Doc)"
    assert meta.author == "(Dxrk)"
    assert meta.subject == "(Testing)"
    assert meta.creator == "(Writer)"
    assert meta.producer == "(Producer X)"
    assert meta.creation_date == "(D:20260101)"
    assert meta.mod_date == "(D:20260202)"
    assert meta.pages == 3


def test_page_count_from_bytes():
    count, err = img._page_count_from_bytes(b"%PDF-1.4\n/Count 4\n")
    assert count == 4
    assert err is None


def test_find_field_and_end_of_string():
    data = b"/Title (abc)"
    idx = img._find_field(data, "/Title")
    assert idx == 0
    assert img._find_field(data, "/Nope") == -1
    assert img._find_end_of_string(data, len("/Title")) == len(data) - 1
    assert img._find_end_of_string(b"/Title abc", 0) == -1


def test_pdf_not_implemented(tmp_path):
    pdf = tmp_path / "x.pdf"
    _write_pdf(pdf, b"")
    with pytest.raises(ValueError, match="not implemented"):
        img.render_page(str(pdf), 1, 72)
    with pytest.raises(ValueError, match="not implemented"):
        img.extract_images(str(pdf))


def test_is_pdf_encrypted(tmp_path):
    pdf = tmp_path / "e.pdf"
    _write_pdf(pdf, b"/Encrypt /Standard\n")
    assert img.is_pdf_encrypted(str(pdf)) is True
    plain = tmp_path / "p.pdf"
    _write_pdf(plain, b"/Title (x)\n")
    assert img.is_pdf_encrypted(str(plain)) is False
    junk = tmp_path / "junk.txt"
    junk.write_bytes(b"not a pdf")
    with pytest.raises(img.PDFError):
        img.is_pdf_encrypted(str(junk))


def test_validate_pdf(tmp_path):
    good = tmp_path / "good.pdf"
    _write_pdf(good, b"/Count 1\n%%EOF")
    assert img.validate_pdf(str(good)) is None

    bad = tmp_path / "bad.pdf"
    _write_pdf(bad, b"/Count 1\n")
    with pytest.raises(ValueError, match="EOF"):
        img.validate_pdf(str(bad))

    junk = tmp_path / "junk.txt"
    junk.write_bytes(b"not a pdf")
    with pytest.raises(img.PDFError):
        img.validate_pdf(str(junk))


def test_has_eof_marker():
    assert img._has_eof_marker(b"%PDF-1.4\n%%EOF") is True
    assert img._has_eof_marker(b"%PDF-1.4\nno marker") is False


def test_get_pdf_version(tmp_path):
    pdf = tmp_path / "v.pdf"
    _write_pdf(pdf, b"", header=b"%PDF-2.0\n")
    assert img.get_pdf_version(str(pdf)) == "2.0"

    junk = tmp_path / "junk.txt"
    junk.write_bytes(b"not a pdf")
    with pytest.raises(img.PDFError):
        img.get_pdf_version(str(junk))
