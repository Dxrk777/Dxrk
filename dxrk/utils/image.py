# SPDX-License-Identifier: MIT
"""Image and PDF processing utilities.

Provides image format detection, decoding, encoding, resizing, format
conversion, base64 handling, an LRU image cache, a chainable image
processor, and basic (naive byte-scanning) PDF text extraction and
metadata reading.

Python's standard library has
no image codecs, so the codec operations (decode, encode, resize, ...)
lazily require Pillow (PIL). When Pillow is not installed those
functions raise ``ImportError``; format detection, MIME mapping,
caching, the processor math and all PDF helpers work without it.
"""

from __future__ import annotations

import base64 as base64
import io as io
import mimetypes as mimetypes
import os as os
import threading as threading

from dxrk.utils.image_cache import CacheEntry as CacheEntry
from dxrk.utils.image_cache import CacheStats as CacheStats
from dxrk.utils.image_cache import ImageCache as ImageCache
from dxrk.utils.image_codec import decode as decode
from dxrk.utils.image_codec import decode_config as decode_config
from dxrk.utils.image_codec import decode_format as decode_format
from dxrk.utils.image_codec import detect_format as detect_format
from dxrk.utils.image_codec import detect_format_from_reader as detect_format_from_reader
from dxrk.utils.image_codec import encode as encode
from dxrk.utils.image_codec import encode_format as encode_format
from dxrk.utils.image_codec import encode_to_bytes as encode_to_bytes
from dxrk.utils.image_codec import from_base64 as from_base64
from dxrk.utils.image_codec import to_base64 as to_base64
from dxrk.utils.image_codec import to_base64_raw as to_base64_raw
from dxrk.utils.image_detect import detect_mime as detect_mime
from dxrk.utils.image_detect import detect_mime_from_reader as detect_mime_from_reader
from dxrk.utils.image_detect import extension_from_mime as extension_from_mime
from dxrk.utils.image_detect import format_from_extension as format_from_extension
from dxrk.utils.image_detect import format_from_mime as format_from_mime
from dxrk.utils.image_detect import get_bounds as get_bounds
from dxrk.utils.image_detect import get_color_model as get_color_model
from dxrk.utils.image_detect import get_dimensions as get_dimensions
from dxrk.utils.image_detect import is_supported_format as is_supported_format
from dxrk.utils.image_detect import mime_from_extension as mime_from_extension
from dxrk.utils.image_format import _PILLOW_REQUIRED as _PILLOW_REQUIRED
from dxrk.utils.image_format import _STR_PDF as _STR_PDF
from dxrk.utils.image_format import _STR_UNKNOWN as _STR_UNKNOWN
from dxrk.utils.image_format import GIF as GIF
from dxrk.utils.image_format import JPEG as JPEG
from dxrk.utils.image_format import PNG as PNG
from dxrk.utils.image_format import Config as Config
from dxrk.utils.image_format import ErrUnsupportedFormat as ErrUnsupportedFormat
from dxrk.utils.image_format import Format as Format
from dxrk.utils.image_format import FormatError as FormatError
from dxrk.utils.image_format import ImageType as ImageType
from dxrk.utils.image_format import SupportedExtensions as SupportedExtensions
from dxrk.utils.image_format import SupportedFormats as SupportedFormats
from dxrk.utils.image_format import SupportedMIMEs as SupportedMIMEs
from dxrk.utils.image_format import Unknown as Unknown
from dxrk.utils.image_format import WebP as WebP
from dxrk.utils.image_format import _coerce_format as _coerce_format
from dxrk.utils.image_format import _PILImage as _PILImage
from dxrk.utils.image_pdf import ErrNotPDF as ErrNotPDF
from dxrk.utils.image_pdf import ErrPageNotFound as ErrPageNotFound
from dxrk.utils.image_pdf import ErrPDFEncrypted as ErrPDFEncrypted
from dxrk.utils.image_pdf import PDFError as PDFError
from dxrk.utils.image_pdf import PDFMetadata as PDFMetadata
from dxrk.utils.image_pdf import _bytes_to_temp as _bytes_to_temp
from dxrk.utils.image_pdf import _decode_stream as _decode_stream
from dxrk.utils.image_pdf import _extract_text_from_bytes as _extract_text_from_bytes
from dxrk.utils.image_pdf import _find_end_of_string as _find_end_of_string
from dxrk.utils.image_pdf import _find_field as _find_field
from dxrk.utils.image_pdf import _has_eof_marker as _has_eof_marker
from dxrk.utils.image_pdf import _is_octal as _is_octal
from dxrk.utils.image_pdf import _page_count_from_bytes as _page_count_from_bytes
from dxrk.utils.image_pdf import _read_all as _read_all
from dxrk.utils.image_pdf import extract_images as extract_images
from dxrk.utils.image_pdf import extract_text as extract_text
from dxrk.utils.image_pdf import get_metadata as get_metadata
from dxrk.utils.image_pdf import get_page_count as get_page_count
from dxrk.utils.image_pdf import get_pdf_version as get_pdf_version
from dxrk.utils.image_pdf import is_pdf_encrypted as is_pdf_encrypted
from dxrk.utils.image_pdf import render_page as render_page
from dxrk.utils.image_pdf import validate_pdf as validate_pdf
from dxrk.utils.image_processor import ImageProcessor as ImageProcessor
from dxrk.utils.image_processor import Operation as Operation
from dxrk.utils.image_processor import _cos as _cos
from dxrk.utils.image_processor import _exp as _exp
from dxrk.utils.image_processor import _gaussian_kernel as _gaussian_kernel
from dxrk.utils.image_processor import _sin as _sin
from dxrk.utils.image_transform import _scale_bilinear as _scale_bilinear
from dxrk.utils.image_transform import convert as convert
from dxrk.utils.image_transform import crop as crop
from dxrk.utils.image_transform import resize as resize
from dxrk.utils.image_transform import resize_fill as resize_fill
from dxrk.utils.image_transform import resize_fit as resize_fit
from dxrk.utils.image_transform import to_grayscale as to_grayscale
from dxrk.utils.image_transform import to_nrgba as to_nrgba
from dxrk.utils.image_transform import to_paletted as to_paletted
from dxrk.utils.image_transform import to_rgba as to_rgba

# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

Decode = decode
DecodeConfig = decode_config
Encode = encode
EncodeToBytes = encode_to_bytes
Resize = resize
ResizeFit = resize_fit
ResizeFill = resize_fill
Crop = crop
Convert = convert
ToRGBA = to_rgba
ToNRGBA = to_nrgba
ToPaletted = to_paletted
ToGrayscale = to_grayscale
ToBase64 = to_base64
ToBase64Raw = to_base64_raw
FromBase64 = from_base64
DetectMIME = detect_mime
DetectMIMEFromReader = detect_mime_from_reader
GetDimensions = get_dimensions
GetBounds = get_bounds
GetColorModel = get_color_model
MIMEFromExtension = mime_from_extension
ExtensionFromMIME = extension_from_mime
DetectFormat = detect_format
DetectFormatFromReader = detect_format_from_reader
DecodeFormat = decode_format
EncodeFormat = encode_format
FormatFromExtension = format_from_extension
FormatFromMIME = format_from_mime
IsSupportedFormat = is_supported_format
ExtractText = extract_text
GetPageCount = get_page_count
GetMetadata = get_metadata
RenderPage = render_page
ExtractImages = extract_images
IsPDFEncrypted = is_pdf_encrypted
ValidatePDF = validate_pdf
GetPDFVersion = get_pdf_version
NewImageCache = ImageCache
NewProcessor = ImageProcessor
