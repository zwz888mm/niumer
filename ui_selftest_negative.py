"""负向对照：证明自检探测器真的会报错，而不是恒通过。

做法：故意破坏版面（把内容右边界放到贴边），同一个检测函数必须报越界。
"""
import sys

from PyQt6.QtWidgets import QApplication

import main

app = QApplication(sys.argv)
bar = main.SalaryBar(app)
SCALE = main.PREVIEW_SCALE
RIGHT_EDGE = 186 - main.DOTS_ZONE


def rightmost_content(image, c):
    """与 _audit.py 同一套量法：关掉页码点后量最右非背景像素。"""
    h = image.height()
    top_rgb = c["top"].getRgb()[:3]
    bottom_rgb = c["bottom"].getRgb()[:3]
    border_rgb = c["border"].getRgb()[:3]
    scan_to = min(image.width() - 1, int((186 - 8) * SCALE))
    for x in range(scan_to, 0, -1):
        for y in range(h):
            px = image.pixelColor(x, y)
            if px.alpha() < 180:
                continue
            rgb = px.getRgb()[:3]
            if all(abs(rgb[i] - border_rgb[i]) <= 14 for i in range(3)):
                continue
            t = y / h
            ref = [int(top_rgb[i] + (bottom_rgb[i] - top_rgb[i]) * t) for i in range(3)]
            if max(abs(rgb[i] - ref[i]) for i in range(3)) > 60:
                return x / SCALE
    return 0.0


def render(page, **kw):
    saved = bar.draw_page_dots
    bar.draw_page_dots = lambda *a, **k: None
    try:
        return main.render_bar_image(bar, page=page, **kw)
    finally:
        bar.draw_page_dots = saved


c = bar.colors()

# ---- 对照 1：正常版面必须判合格 ----
ok_edge = rightmost_content(render(main.PAGE_WORD), c)
print(f"[基线] 正常版面最右 {ok_edge:.1f} ≤ {RIGHT_EDGE} ? "
      f"{'是' if ok_edge <= RIGHT_EDGE + 0.5 else '否 → 探测器基线有问题'}")

# ---- 对照 2：故意把内容右边界放到贴边，必须判越界 ----
main.DOTS_ZONE = 4
bad_edge = rightmost_content(render(main.PAGE_WORD), c)
main.DOTS_ZONE = 34
print(f"[破坏] 内容放到贴边后最右 {bad_edge:.1f} > {RIGHT_EDGE} ? "
      f"{'是 → 探测器有效' if bad_edge > RIGHT_EDGE + 0.5 else '否 → 探测器失灵'}")

# ---- 对照 3：对比度探测器 ----
def lum(q):
    def f(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(q.red()) + 0.7152 * f(q.green()) + 0.0722 * f(q.blue())


def contrast(fg, bg):
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


bg_mid = main.QColor((c["top"].red() + c["bottom"].red()) // 2,
                     (c["top"].green() + c["bottom"].green()) // 2,
                     (c["top"].blue() + c["bottom"].blue()) // 2)
good = contrast(c["text"], bg_mid)
bad = contrast(main.QColor(60, 64, 71), bg_mid)  # 故意贴近背景
print(f"[对照] 正常文字对比度 {good:.2f} ≥ 4.5 ? "
      f"{'是' if good >= 4.5 else '否'}；故意压暗后 {bad:.2f} < 4.5 ? "
      f"{'是 → 探测器有效' if bad < 4.5 else '否 → 探测器失灵'}")

# ---- 浅色主题也要能画出来（不落盘，只验证不抛异常） ----
main.is_light_theme = lambda: True
for page in (main.PAGE_SALARY, main.PAGE_WORD, main.PAGE_NOVEL):
    img = main.render_bar_image(bar, page)
    assert not img.isNull() and img.width() > 0
h = main.HelpDialog(bar)
h.setAttribute(main.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
h.show()
for _ in range(4):
    app.processEvents()
sc = main.SettingsCenter(bar)
sc.setAttribute(main.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
sc.show_panel("remind")
sc.show()
for _ in range(4):
    app.processEvents()
print("浅色主题渲染正常（三页 + 帮助 + 设置）")
