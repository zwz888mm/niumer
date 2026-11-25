"""
原图四角加圆角 → PNG inside ICO（Windows Vista+ 原生支持，完美保留 alpha）。
"""
from PIL import Image, ImageDraw
import struct, os, io

SRC = r"c:\Users\wenzheng.zhang\Downloads\Niumer软件logo设计 (3).png"
DST = r"c:\Users\wenzheng.zhang\Desktop\desktop-tool"

src = Image.open(SRC).convert("RGBA")
print(f"原图: {src.size}")

ICO_SIZES = [16, 20, 24, 28, 32, 36, 40, 48, 64, 128, 256]
RATIO = 0.18


def apply_rounded_corners(im):
    w, h = im.size
    r = max(1, int(min(w, h) * RATIO))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    result = im.copy()
    result.putalpha(mask)
    return result


def make_ico_png_inside(images):
    """PNG inside ICO：把每张图存成 PNG 字节，直接塞进 ICO entry。"""
    entries = []
    for im in images:
        w, h = im.size
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        entries.append((w, h, png_bytes))

    header = struct.pack('<HHH', 0, 1, len(entries))
    offset = 6 + len(entries) * 16
    dir_entries = b''
    for w, h, png in entries:
        wb = w if w < 256 else 0
        hb = h if h < 256 else 0
        # bitcount=0 + dwBytesInRes=size + dwImageOffset → 表示 PNG
        entry = struct.pack('<BBBBHHII', wb, hb, 0, 0, 1, 0, len(png), offset)
        dir_entries += entry
        offset += len(png)

    data = b''.join(png for _, _, png in entries)
    return header + dir_entries + data


# 1) 生成所有带圆角的尺寸图
sized = []
for sz in ICO_SIZES:
    im = src.resize((sz, sz), Image.LANCZOS)
    im = apply_rounded_corners(im)
    sized.append(im)
    im.save(os.path.join(DST, f"Niumer-tray-{sz}.png"), "PNG")
print(f"已保存 {len(ICO_SIZES)} 个带圆角 tray PNG")

# 2) 主图
rounded = apply_rounded_corners(src)
rounded.save(os.path.join(DST, "Niumer-logo.png"), "PNG")
rounded.save(os.path.join(DST, "Niumer-head.png"), "PNG")
print("已保存 Niumer-logo.png / Niumer-head.png")

# 3) PNG inside ICO
for name in ["logo.ico", "Niumer.ico", "Niumer-head.ico"]:
    ico_path = os.path.join(DST, name)
    ico_data = make_ico_png_inside(sized)
    with open(ico_path, 'wb') as f:
        f.write(ico_data)
    print(f"  {name}: {len(ico_data)} bytes")

# 4) 验证每层（ICO 里的是 PNG，直接 PIL 读）
print("\n=== 验证 ICO 每层四角 ===")
with open(os.path.join(DST, "logo.ico"), 'rb') as f:
    raw = f.read()
_, _, cnt = struct.unpack_from('<HHH', raw, 0)
off = 6
for i in range(cnt):
    wb, hb = struct.unpack_from('<BB', raw, off)
    w = wb if wb else 256
    h = hb if hb else 256
    size, img_off = struct.unpack_from('<II', raw, off + 8)
    png = raw[img_off:img_off + size]
    try:
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        px = im.load()
        a = [px[0, 0][3], px[w - 1, 0][3], px[0, h - 1][3], px[w - 1, h - 1][3]]
        cut = sum(1 for x in a if x < 128)
        print(f"  {w:>3}x{h}: 透明角={cut}/4  alpha={a}")
    except Exception as e:
        print(f"  {w:>3}x{h}: FAIL - {e}")
    off += 16

print("\n完成！PNG inside ICO，每层独立，完美圆角。")
