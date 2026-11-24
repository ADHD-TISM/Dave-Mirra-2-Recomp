"""Make the Windows icon for bmx2.exe from the game's own memory card icon.

    python -I tools/make_icon.py <ICON.DAT from the disc's ASSETS folder> <out.ico>

ICON.DAT is a PS2 save icon: a small 3D model with one 128x128 texture, which
holds the game's logo tile. This takes only the texture (16-bit, the last
32768 bytes when uncompressed) and writes it as a .ico with the usual sizes.
The icon comes from the player's disc at build time and is never committed.
"""
import struct
import sys

TEX = 128


def texture(data):
    if len(data) < 20 + TEX * TEX * 2:
        raise SystemExit("ICON.DAT is too short (%d bytes)" % len(data))
    magic, _shapes, ttype = struct.unpack_from("<III", data, 0)
    if magic != 0x00010000:
        raise SystemExit("ICON.DAT is not a PS2 icon (magic %08x)" % magic)
    if ttype & 8 or not ttype & 4:
        raise SystemExit("ICON.DAT has no plain texture (type %x), not handled" % ttype)
    raw = data[-TEX * TEX * 2:]
    px = []
    for i in range(TEX * TEX):
        p = raw[2 * i] | raw[2 * i + 1] << 8      # A1 B5 G5 R5
        px.append(((p & 31) * 255 // 31, (p >> 5 & 31) * 255 // 31, (p >> 10 & 31) * 255 // 31))
    return px


def scaled(px, n):
    """Area average of the 128x128 picture down to n x n."""
    out = []
    f = TEX / n
    for y in range(n):
        y0, y1 = int(y * f), max(int(y * f) + 1, int((y + 1) * f))
        for x in range(n):
            x0, x1 = int(x * f), max(int(x * f) + 1, int((x + 1) * f))
            r = g = b = 0
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    p = px[yy * TEX + xx]
                    r += p[0]; g += p[1]; b += p[2]
            k = (y1 - y0) * (x1 - x0)
            out.append((r // k, g // k, b // k))
    return out


def bmp_entry(px, n):
    """One icon image: BITMAPINFOHEADER (height doubled), 32-bit BGRA rows bottom-up, empty AND mask."""
    hdr = struct.pack("<IiiHHIIiiII", 40, n, n * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = b"".join(bytes(c for p in px[y * n:(y + 1) * n] for c in (p[2], p[1], p[0], 255))
                    for y in range(n - 1, -1, -1))
    mask = b"\0" * (((n + 31) // 32) * 4 * n)
    return hdr + rows + mask


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__)
    with open(argv[1], "rb") as f:
        px = texture(f.read())
    sizes = (16, 24, 32, 48, 64, 128)
    imgs = [bmp_entry(px if n == TEX else scaled(px, n), n) for n in sizes]
    out = struct.pack("<HHH", 0, 1, len(sizes))
    off = 6 + 16 * len(sizes)
    for n, im in zip(sizes, imgs):
        out += struct.pack("<BBBBHHII", n, n, 0, 0, 1, 32, len(im), off)
        off += len(im)
    with open(argv[2], "wb") as f:
        f.write(out + b"".join(imgs))
    print("icon written: %s" % argv[2])


if __name__ == "__main__":
    main(sys.argv)
