"""PNG and JPEG headers, and decoding 8-bit PNGs, with ``struct`` and ``zlib`` only.

``info`` reads what the stores check (size, alpha, colour space) without decoding pixels. ``decode_rgb``
decodes a whole 8-bit, non-interlaced PNG for checks that look at pixels (contrast, seams between panels), and
``decode_alpha`` its opacity (a device art's see-through screen).
"""

from __future__ import annotations

import collections
import hashlib
import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

ImageInfo = collections.namedtuple(
    "ImageInfo",
    ["format", "width", "height", "bit_depth", "color_type", "has_alpha", "interlaced", "srgb", "icc_name"],
)
ImageInfo.__doc__ = """What a picture's header says.

- ``format``: ``png`` or ``jpeg``.
- ``width``, ``height``: pixels.
- ``bit_depth``: bits a sample (a JPEG's sample precision).
- ``color_type``: PNG's colour type (0 grey, 2 RGB, 3 palette, 4 grey+alpha, 6 RGBA); for a JPEG, the number
  of components (1 grey, 3 colour, 4 CMYK).
- ``has_alpha``: colour types 4 and 6, or a ``tRNS`` chunk. Always false for a JPEG.
- ``interlaced``: Adam7 for a PNG, progressive for a JPEG.
- ``srgb``: an ``sRGB`` chunk, no colour profile at all (untagged, read as sRGB), or an ICC profile whose
  name or description says sRGB.
- ``icc_name``: the embedded ICC profile's description (or a PNG ``iCCP`` chunk's name), else ``None``.
"""


class ImageError(ValueError):
    """A file that isn't a PNG or JPEG this module can read."""


_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _icc_description(profile):
    """The ``desc`` tag of an ICC profile (v2 ``desc`` or v4 ``mluc``), or ``None``."""
    try:
        if len(profile) < 132:
            return None
        (count,) = struct.unpack(">I", profile[128:132])
        for i in range(min(count, 200)):
            sig, offset, size = struct.unpack(">4sII", profile[132 + 12 * i: 144 + 12 * i])
            if sig != b"desc":
                continue
            tag = profile[offset: offset + size]
            kind = tag[:4]
            if kind == b"desc":
                (n,) = struct.unpack(">I", tag[8:12])
                return tag[12: 12 + n].split(b"\0", 1)[0].decode("latin-1").strip() or None
            if kind == b"mluc":
                records, rec_size = struct.unpack(">II", tag[8:16])
                if records < 1:
                    return None
                _lang, length, off = struct.unpack(">4sII", tag[16:28])
                return tag[off: off + length].decode("utf-16-be", "replace").strip("\0 ") or None
            return None
    except (struct.error, IndexError, UnicodeDecodeError):
        return None
    return None


def _is_srgb_name(name):
    return bool(name) and "srgb" in name.lower().replace(" ", "")


def _png_info(data, path):
    pos = 8
    ihdr = None
    has_trns = False
    srgb_chunk = False
    icc_name = None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos: pos + 8])
        body = data[pos + 8: pos + 8 + length]
        if len(body) < length:
            raise ImageError("%s: truncated %s chunk" % (path, kind.decode("latin-1")))
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body[:13])
        elif kind == b"tRNS":
            has_trns = True
        elif kind == b"sRGB":
            srgb_chunk = True
        elif kind == b"iCCP":
            name, _, rest = body.partition(b"\0")
            icc_name = name.decode("latin-1") or None
            try:
                desc = _icc_description(zlib.decompress(rest[1:]))
            except zlib.error:
                desc = None
            if desc:
                icc_name = desc
        elif kind in (b"IDAT", b"IEND"):
            break
        pos += 12 + length
    if ihdr is None:
        raise ImageError("%s: PNG without an IHDR chunk" % path)
    width, height, depth, ctype, _comp, _filt, interlace = ihdr
    return ImageInfo(
        format="png",
        width=width,
        height=height,
        bit_depth=depth,
        color_type=ctype,
        has_alpha=ctype in (4, 6) or has_trns,
        interlaced=interlace == 1,
        srgb=srgb_chunk or icc_name is None or _is_srgb_name(icc_name),
        icc_name=icc_name,
    )


_SOF = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_PROGRESSIVE = {0xC2, 0xC6, 0xCA, 0xCE}


def _jpeg_info(data, path):
    pos = 2
    icc_parts = {}
    sof = None
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise ImageError("%s: JPEG marker expected at byte %d" % (path, pos))
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker in (0xD9, 0xDA):  # end of image, start of scan: no more headers
            break
        (length,) = struct.unpack(">H", data[pos + 2: pos + 4])
        body = data[pos + 4: pos + 2 + length]
        if marker == 0xE2 and body.startswith(b"ICC_PROFILE\0") and len(body) >= 14:
            icc_parts[body[12]] = body[14:]
        elif marker in _SOF and sof is None:
            precision, height, width, components = struct.unpack(">BHHB", body[:6])
            sof = (marker, precision, height, width, components)
        pos += 2 + length
    if sof is None:
        raise ImageError("%s: JPEG without a frame header (SOF)" % path)
    marker, precision, height, width, components = sof
    icc_name = None
    if icc_parts:
        profile = b"".join(icc_parts[k] for k in sorted(icc_parts))
        icc_name = _icc_description(profile) or "ICC profile"
    return ImageInfo(
        format="jpeg",
        width=width,
        height=height,
        bit_depth=precision,
        color_type=components,
        has_alpha=False,
        interlaced=marker in _PROGRESSIVE,
        srgb=icc_name is None or _is_srgb_name(icc_name),
        icc_name=icc_name,
    )


def info(path):
    """Read a PNG's or JPEG's header and return an ``ImageInfo``; raise ``ImageError`` for anything else."""
    data = _read(path)
    if data.startswith(PNG_SIGNATURE):
        return _png_info(data, path)
    if data.startswith(b"\xff\xd8"):
        return _jpeg_info(data, path)
    raise ImageError("%s: not a PNG or JPEG" % path)


def _unfilter(raw, width, height, bpp):
    """Undo PNG's per-row filters (None, Sub, Up, Average, Paeth); return the bare scanlines."""
    stride = width * bpp
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        if pos + 1 + stride > len(raw):
            raise ImageError("image data ends early (row %d of %d)" % (y, height))
        ftype = raw[pos]
        line = bytearray(raw[pos + 1: pos + 1 + stride])
        pos += 1 + stride
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, prev))
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                if i >= bpp:
                    a = line[i - bpp]
                    c = prev[i - bpp]
                else:
                    a = c = 0
                b = prev[i]
                p = a + b - c
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c)
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                line[i] = (line[i] + pred) & 0xFF
        else:
            raise ImageError("unknown PNG filter type %d in row %d" % (ftype, y))
        out[y * stride: (y + 1) * stride] = line
        prev = line
    return out


def _decode(path, who):
    """Parse and unfilter an 8-bit, non-interlaced PNG: ``(width, height, colour type, bpp, pixels, palette,
    trns)``. ``who`` names the caller in errors."""
    data = _read(path)
    if not data.startswith(PNG_SIGNATURE):
        raise ImageError("%s: %s reads PNGs only" % (path, who))
    pos = 8
    ihdr = None
    palette = None
    trns = None
    idat = []
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos: pos + 8])
        body = data[pos + 8: pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body[:13])
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
        pos += 12 + length
    if ihdr is None:
        raise ImageError("%s: PNG without an IHDR chunk" % path)
    width, height, depth, ctype, _comp, _filt, interlace = ihdr
    if depth != 8:
        raise ImageError("%s: %s reads 8-bit PNGs only (this one is %d-bit)" % (path, who, depth))
    if interlace:
        raise ImageError("%s: %s doesn't read interlaced PNGs" % (path, who))
    if ctype not in _CHANNELS:
        raise ImageError("%s: unknown PNG colour type %d" % (path, ctype))
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise ImageError("%s: damaged image data (%s)" % (path, e)) from None
    bpp = _CHANNELS[ctype]
    try:
        pixels = _unfilter(raw, width, height, bpp)
    except ImageError as e:
        raise ImageError("%s: %s" % (path, e)) from None
    if ctype == 3 and palette is None:
        raise ImageError("%s: palette PNG without a PLTE chunk" % path)
    return width, height, ctype, bpp, pixels, palette, trns


def decode_rgb(path):
    """Decode an 8-bit, non-interlaced PNG and return ``(width, height, rgb_bytes)``.

    ``rgb_bytes`` holds 3 bytes a pixel, rows top to bottom. RGB and RGBA are the cases this is for; grey,
    grey+alpha and palette pictures are expanded to RGB too. Alpha is dropped (not blended). Raises
    ``ImageError`` for a JPEG, a 16-bit or sub-byte depth, or an interlaced PNG.
    """
    width, height, ctype, bpp, pixels, palette, _trns = _decode(path, "decode_rgb")
    if ctype == 2:
        return width, height, bytes(pixels)
    out = bytearray(width * height * 3)
    if ctype == 6:
        out[0::3] = pixels[0::4]
        out[1::3] = pixels[1::4]
        out[2::3] = pixels[2::4]
    elif ctype in (0, 4):
        grey = pixels[0::bpp]
        out[0::3] = grey
        out[1::3] = grey
        out[2::3] = grey
    else:  # palette
        table = [bytes(palette[i * 3: i * 3 + 3]).ljust(3, b"\0") for i in range(256)]
        out = bytearray(b"".join(table[i] for i in pixels))
    return width, height, bytes(out)


def decode_alpha(path):
    """Decode an 8-bit, non-interlaced PNG's opacity: ``(width, height, alpha_bytes)``, one byte a pixel (0 clear,
    255 opaque), rows top to bottom. RGBA and grey+alpha read their alpha channel; a palette picture its ``tRNS``
    table; anything else is opaque (every byte 255). For finding a device art's see-through screen. Raises
    ``ImageError`` as ``decode_rgb`` does."""
    width, height, ctype, bpp, pixels, _palette, trns = _decode(path, "decode_alpha")
    if ctype in (4, 6):
        return width, height, bytes(pixels[bpp - 1::bpp])
    if ctype == 3 and trns:
        table = bytes(bytearray(trns[:256]).ljust(256, b"\xff"))
        return width, height, bytes(pixels).translate(table)
    return width, height, b"\xff" * (width * height)


def has_transparency(path):
    """True when a picture has see-through pixels, not merely an alpha channel (a 32-bit PNG whose every
    pixel is opaque has none). A JPEG never does. Colour types 4 and 6 at 8 bits, non-interlaced, are decoded
    and their alpha read; a ``tRNS`` chunk, or an alpha channel this module can't decode (16-bit, interlaced),
    counts as transparency. Raises ``ImageError`` for a file that isn't a PNG or JPEG."""
    meta = info(path)
    if not meta.has_alpha:
        return False
    data = _read(path)
    pos = 8
    idat = []
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos: pos + 8])
        if kind == b"tRNS":
            return True
        if kind == b"IDAT":
            idat.append(data[pos + 8: pos + 8 + length])
        elif kind == b"IEND":
            break
        pos += 12 + length
    if meta.bit_depth != 8 or meta.interlaced or meta.color_type not in (4, 6):
        return True
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise ImageError("%s: damaged image data (%s)" % (path, e)) from None
    bpp = _CHANNELS[meta.color_type]
    try:
        pixels = _unfilter(raw, meta.width, meta.height, bpp)
    except ImageError as e:
        raise ImageError("%s: %s" % (path, e)) from None
    return min(pixels[bpp - 1::bpp], default=255) < 255

def _digest(path, algo):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def md5(path):
    """The file's MD5 as lower-case hex (App Store Connect's upload checksum)."""
    return _digest(path, "md5")


def sha256(path):
    """The file's SHA-256 as lower-case hex."""
    return _digest(path, "sha256")
