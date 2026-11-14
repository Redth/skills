"""Tests for appstores_lib.png (stdlib unittest). Every fixture is written here with zlib and struct."""

import hashlib
import os
import random
import struct
import sys
import tempfile
import unittest
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from appstores_lib import png  # noqa: E402


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def filter_row(ftype, row, prev, bpp):
    """Apply one PNG filter to a scanline, as an encoder would."""
    if ftype == 0:
        return bytes(row)
    out = bytearray()
    for i, x in enumerate(row):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        pred = {0: 0, 1: a, 2: b, 3: (a + b) // 2, 4: paeth(a, b, c)}[ftype]
        out.append((x - pred) & 0xFF)
    return bytes(out)


def png_bytes(width, height, ctype, rows=None, depth=8, interlace=0, filters=None, before_idat=b""):
    """A PNG of ``rows`` (raw scanlines), each row filtered with ``filters[y % len(filters)]``."""
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype] * max(1, depth // 8)
    stride = width * bpp
    if rows is None:
        rows = [bytes(stride) for _ in range(height)]
    filters = filters or [0]
    parts = []
    prev = bytes(stride)
    for y, row in enumerate(rows):
        f = filters[y % len(filters)]
        parts.append(bytes([f]) + filter_row(f, row, prev, bpp))
        prev = row
    raw = b"".join(parts)
    ihdr = struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, interlace)
    return (png.PNG_SIGNATURE + chunk(b"IHDR", ihdr) + before_idat
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def icc_profile(description, v4=False):
    """A minimal ICC profile: a 128-byte header and one ``desc`` tag."""
    if v4:
        name = description.encode("utf-16-be")
        tag = b"mluc" + bytes(4) + struct.pack(">II", 1, 12) + b"enUS" + struct.pack(">II", len(name), 28) + name
    else:
        name = description.encode("latin-1") + b"\0"
        tag = b"desc" + bytes(4) + struct.pack(">I", len(name)) + name
    table = struct.pack(">I", 1) + b"desc" + struct.pack(">II", 144, len(tag))
    return bytes(128) + table + tag


def jpeg_bytes(width, height, progressive=False, components=3, icc=None):
    """The headers of a JPEG: SOI, APP0, an optional APP2 ICC profile, a frame header (SOF0/SOF2), EOI."""
    app0 = b"JFIF\0" + bytes([1, 1, 0]) + struct.pack(">HH", 1, 1) + b"\0\0"
    out = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0
    if icc is not None:
        body = b"ICC_PROFILE\0" + bytes([1, 1]) + icc
        out += b"\xff\xe2" + struct.pack(">H", len(body) + 2) + body
    sof = struct.pack(">BHHB", 8, height, width, components) + b"".join(
        bytes([i + 1, 0x11, 0]) for i in range(components))
    out += (b"\xff\xc2" if progressive else b"\xff\xc0") + struct.pack(">H", len(sof) + 2) + sof
    return out + b"\xff\xd9"


class PngTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, data):
        path = os.path.join(self._tmp.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path


class InfoTests(PngTestCase):
    def test_rgb(self):
        i = png.info(self.write("rgb.png", png_bytes(1290, 2796, 2, rows=[bytes(3 * 1290)] * 2796)))
        self.assertEqual((i.format, i.width, i.height, i.bit_depth, i.color_type), ("png", 1290, 2796, 8, 2))
        self.assertFalse(i.has_alpha)
        self.assertFalse(i.interlaced)
        self.assertTrue(i.srgb, "an untagged PNG reads as sRGB")
        self.assertIsNone(i.icc_name)

    def test_rgba_has_alpha(self):
        i = png.info(self.write("rgba.png", png_bytes(4, 3, 6)))
        self.assertEqual(i.color_type, 6)
        self.assertTrue(i.has_alpha)

    def test_grey_alpha_has_alpha(self):
        self.assertTrue(png.info(self.write("ga.png", png_bytes(4, 3, 4))).has_alpha)

    def test_palette_with_trns_has_alpha(self):
        plte = chunk(b"PLTE", bytes([255, 0, 0, 0, 255, 0]))
        trns = chunk(b"tRNS", bytes([0]))
        i = png.info(self.write("pal.png", png_bytes(2, 2, 3, before_idat=plte + trns)))
        self.assertEqual(i.color_type, 3)
        self.assertTrue(i.has_alpha)
        self.assertFalse(png.info(self.write("pal2.png", png_bytes(2, 2, 3, before_idat=plte))).has_alpha)

    def test_sixteen_bit(self):
        i = png.info(self.write("16.png", png_bytes(2, 2, 2, depth=16)))
        self.assertEqual(i.bit_depth, 16)

    def test_interlaced_flag(self):
        self.assertTrue(png.info(self.write("i.png", png_bytes(2, 2, 2, interlace=1))).interlaced)

    def test_srgb_chunk(self):
        i = png.info(self.write("s.png", png_bytes(2, 2, 2, before_idat=chunk(b"sRGB", b"\0"))))
        self.assertTrue(i.srgb)

    def test_icc_profiles(self):
        def iccp(name, profile):
            return chunk(b"iCCP", name + b"\0\0" + zlib.compress(profile))

        p3 = png.info(self.write("p3.png", png_bytes(2, 2, 2, before_idat=iccp(b"ICC Profile", icc_profile("Display P3")))))
        self.assertFalse(p3.srgb)
        self.assertEqual(p3.icc_name, "Display P3", "the profile's description beats the chunk's name")

        s = png.info(self.write("s.png", png_bytes(2, 2, 2, before_idat=iccp(b"ICC Profile", icc_profile("sRGB IEC61966-2.1")))))
        self.assertTrue(s.srgb)

        v4 = png.info(self.write("v4.png", png_bytes(2, 2, 2, before_idat=iccp(b"x", icc_profile("Display P3", v4=True)))))
        self.assertEqual(v4.icc_name, "Display P3")

        named = png.info(self.write("n.png", png_bytes(2, 2, 2, before_idat=iccp(b"Adobe RGB", b"not a profile"))))
        self.assertEqual(named.icc_name, "Adobe RGB")
        self.assertFalse(named.srgb)

    def test_jpeg_size_from_the_frame_header(self):
        i = png.info(self.write("a.jpg", jpeg_bytes(1024, 500)))
        self.assertEqual((i.format, i.width, i.height, i.bit_depth, i.color_type), ("jpeg", 1024, 500, 8, 3))
        self.assertFalse(i.has_alpha)
        self.assertFalse(i.interlaced)
        self.assertTrue(i.srgb)

    def test_progressive_jpeg_with_a_profile(self):
        i = png.info(self.write("p.jpg", jpeg_bytes(640, 480, progressive=True, icc=icc_profile("Display P3"))))
        self.assertEqual((i.width, i.height), (640, 480))
        self.assertTrue(i.interlaced)
        self.assertEqual(i.icc_name, "Display P3")
        self.assertFalse(i.srgb)

    def test_other_files_raise(self):
        with self.assertRaises(png.ImageError):
            png.info(self.write("x.gif", b"GIF89a....."))
        with self.assertRaises(png.ImageError):
            png.info(self.write("nosof.jpg", b"\xff\xd8\xff\xd9"))


class DecodeTests(PngTestCase):
    def pixels(self, width, height, channels, seed):
        rnd = random.Random(seed)
        return [bytes(rnd.randrange(256) for _ in range(width * channels)) for _ in range(height)]

    def test_rgb_every_filter(self):
        rows = self.pixels(7, 10, 3, 1)
        path = self.write("f.png", png_bytes(7, 10, 2, rows=rows, filters=[0, 1, 2, 3, 4]))
        w, h, data = png.decode_rgb(path)
        self.assertEqual((w, h), (7, 10))
        self.assertEqual(data, b"".join(rows))

    def test_each_filter_alone(self):
        rows = self.pixels(5, 4, 3, 2)
        for f in range(5):
            path = self.write("f%d.png" % f, png_bytes(5, 4, 2, rows=rows, filters=[f]))
            self.assertEqual(png.decode_rgb(path)[2], b"".join(rows), "filter %d" % f)

    def test_rgba_drops_alpha(self):
        rows = self.pixels(6, 5, 4, 3)
        path = self.write("a.png", png_bytes(6, 5, 6, rows=rows, filters=[4, 3, 2, 1, 0]))
        expected = b"".join(bytes(b for i, b in enumerate(r) if i % 4 != 3) for r in rows)
        self.assertEqual(png.decode_rgb(path)[2], expected)

    def test_grey_and_palette_expand_to_rgb(self):
        grey = self.write("g.png", png_bytes(2, 1, 0, rows=[bytes([10, 200])], filters=[1]))
        self.assertEqual(png.decode_rgb(grey)[2], bytes([10, 10, 10, 200, 200, 200]))
        plte = chunk(b"PLTE", bytes([255, 0, 0, 0, 0, 255]))
        pal = self.write("p.png", png_bytes(3, 1, 3, rows=[bytes([1, 0, 1])], before_idat=plte))
        self.assertEqual(png.decode_rgb(pal)[2], bytes([0, 0, 255, 255, 0, 0, 0, 0, 255]))

    def test_what_it_does_not_read(self):
        with self.assertRaises(png.ImageError):
            png.decode_rgb(self.write("16.png", png_bytes(2, 2, 2, depth=16)))
        with self.assertRaises(png.ImageError):
            png.decode_rgb(self.write("i.png", png_bytes(2, 2, 2, interlace=1)))
        with self.assertRaises(png.ImageError):
            png.decode_rgb(self.write("a.jpg", jpeg_bytes(2, 2)))

    def test_truncated_data_raises(self):
        data = png_bytes(4, 4, 2, rows=self.pixels(4, 4, 3, 4))
        start = data.index(b"IDAT")
        (length,) = struct.unpack(">I", data[start - 4: start])
        idat = zlib.decompress(data[start + 4: start + 4 + length])[:-5]
        broken = data[: start - 4] + chunk(b"IDAT", zlib.compress(idat)) + chunk(b"IEND", b"")
        with self.assertRaises(png.ImageError):
            png.decode_rgb(self.write("t.png", broken))


class DigestTests(PngTestCase):
    def test_md5_and_sha256(self):
        data = png_bytes(3, 3, 2)
        path = self.write("d.png", data)
        self.assertEqual(png.md5(path), hashlib.md5(data).hexdigest())
        self.assertEqual(png.sha256(path), hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    unittest.main()
