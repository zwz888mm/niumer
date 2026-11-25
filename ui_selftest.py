"""界面自检：小条排版越界、对比度、帮助配图、五个设置面板尺寸。

跑法（在 desktop-tool 目录下）：
    QT_QPA_PLATFORM=windows python ui_selftest.py
全过退出码 0，有失败退出码 1，可以挂到改完代码后的例行检查里。

检测思路（越界部分）：同一页渲染两遍，一遍正常、一遍关掉右侧页码点，
两图做像素差就得到页码点的真实范围；去掉点阵那张图里量到的最右
非背景像素就是纯内容的右边界。这样不依赖任何颜色常量，抗锯齿的
边缘也不会被误判成内容。
"""
import re
import sys

from PyQt6.QtWidgets import QApplication

import main

app = QApplication(sys.argv)
bar = main.SalaryBar(app)
results = []


def check(name, ok, detail=""):
    results.append((ok, name, detail))


def lum(c):
    def f(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(c.red()) + 0.7152 * f(c.green()) + 0.0722 * f(c.blue())


def contrast(fg, bg):
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ---- 1. 对比度（小条） ----
c = bar.colors()
bg_mid = main.QColor(
    (c["top"].red() + c["bottom"].red()) // 2,
    (c["top"].green() + c["bottom"].green()) // 2,
    (c["top"].blue() + c["bottom"].blue()) // 2,
)
for key, need in (("text", 4.5), ("sub", 3.0), ("faint", 2.2)):
    ratio = contrast(c[key], bg_mid)
    check(f"小条 {key} 对比度 ≥ {need}", ratio >= need, f"{ratio:.2f}")

# ---- 2. 内容是否压到右侧页码区 ----
SCALE = main.PREVIEW_SCALE
RIGHT_EDGE = 186 - main.DOTS_ZONE


def render(page, dots=True, **kw):
    saved = bar.draw_page_dots
    if not dots:
        bar.draw_page_dots = lambda *a, **k: None
    try:
        return main.render_bar_image(bar, page=page, **kw)
    finally:
        bar.draw_page_dots = saved


def _pixel_rgb(image, x, y):
    px = image.pixelColor(x, y)
    if px.alpha() < 180:
        return None
    return px.getRgb()[:3]


def rightmost_content(image):
    """纯内容的右边界（逻辑像素）。页码点必须已被关掉。"""
    h = image.height()
    top_rgb = c["top"].getRgb()[:3]
    bottom_rgb = c["bottom"].getRgb()[:3]
    border_rgb = c["border"].getRgb()[:3]
    # 圆角半径 7，右侧 8px 内只有圆角与边框，不可能是内容
    scan_to = min(image.width() - 1, int((186 - 8) * SCALE))
    for x in range(scan_to, 0, -1):
        for y in range(h):
            rgb = _pixel_rgb(image, x, y)
            if rgb is None:
                continue
            if all(abs(rgb[i] - border_rgb[i]) <= 14 for i in range(3)):
                continue
            t = y / h
            ref = [int(top_rgb[i] + (bottom_rgb[i] - top_rgb[i]) * t) for i in range(3)]
            if max(abs(rgb[i] - ref[i]) for i in range(3)) > 60:
                return x / SCALE
    return 0.0


def dot_band(full, bare):
    """两图差异 = 页码点范围，返回 (左, 右) 逻辑像素。"""
    left, right = None, 0
    for x in range(full.width()):
        for y in range(full.height()):
            if full.pixel(x, y) != bare.pixel(x, y):
                if left is None:
                    left = x
                right = x
                break
    if left is None:
        return None, None
    return left / SCALE, right / SCALE


bar.show_total = False
cases = [
    ("工资条", True, dict(page=main.PAGE_SALARY)),
    ("工资条·每秒", False, dict(page=main.PAGE_SALARY)),
    ("单词卡", True, dict(page=main.PAGE_WORD)),
    ("单词卡·默写", True, dict(page=main.PAGE_WORD, spelling=True, typed="ab")),
    ("小说", True, dict(page=main.PAGE_NOVEL)),
    ("天气", True, dict(page=main.PAGE_NOVEL, weather=True,
                        weather_data=main.demo_weather())),
]
for label, total, kw in cases:
    bar.show_total = total
    kw = dict(kw)
    page = kw.pop("page")
    full = render(page, dots=True, **kw)
    bare = render(page, dots=False, **kw)
    edge = rightmost_content(bare)
    dleft, dright = dot_band(full, bare)
    check(f"{label} 内容不出右边界", edge <= RIGHT_EDGE + 0.5,
          f"最右 {edge:.1f} / 限 {RIGHT_EDGE}")
    if dleft is not None:
        check(f"{label} 页码点不与内容重叠", dleft >= edge + 2,
              f"点从左 {dleft:.1f}，内容到 {edge:.1f}")
bar.show_total = True

# 极端数据也不能越界
_saved_base = bar.earned_base
bar.earned_base = 9_999_999.99
bar.elapsed.restart()
bar.shown_earned = bar.earned
bar.shown_rate = 37.5
img = render(main.PAGE_SALARY, dots=False)
edge = rightmost_content(img)
check("大金额内容不出右边界", edge <= RIGHT_EDGE + 0.5, f"最右 {edge:.1f}")
bar.earned_base = _saved_base

orig_current = bar.deck.current
bar.deck.current = lambda: ("internationalization", "/ˌɪntəˌnæʃnəlaɪzˈeɪʃn/",
                            "n. 国际化；国际化的过程与状态说明")
img = render(main.PAGE_WORD, dots=False)
edge = rightmost_content(img)
check("超长单词不出右边界", edge <= RIGHT_EDGE + 0.5, f"最右 {edge:.1f}")
img = render(main.PAGE_WORD, dots=False, spelling=True, typed="intern")
edge = rightmost_content(img)
check("超长单词默写不出右边界", edge <= RIGHT_EDGE + 0.5, f"最右 {edge:.1f}")
bar.deck.current = orig_current

# ---- 3. 帮助页：图片齐不齐 ----
images = main.HelpDialog.build_images(bar)
pages = main.help_pages()
check("帮助页数量 = 11", len(pages) == 11, str(len(pages)))
missing = []
for title, html in pages:
    for name in re.findall(r"preview/([\w-]+)\.png", html):
        if name not in images or images[name].isNull():
            missing.append(f"{title}:{name}")
check("帮助配图全部可用", not missing, "、".join(missing) or f"{len(images)} 张")
for title, html in pages:
    if len(html) < 400:
        check(f"“{title}”内容过短", False, f"{len(html)} 字符")

# ---- 4. 设置面板不横向溢出 ----
for key in ("salary", "words", "remind", "novel", "appearance"):
    sc = main.SettingsCenter(bar)
    sc.setAttribute(main.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    sc.show_panel(key)
    sc.show()
    for _ in range(3):
        app.processEvents()
    panel = sc.panels[key]
    area = next(sc.stack.widget(i) for i in range(sc.stack.count())
                if sc.stack.widget(i).widget() is panel)
    check(f"{key} 面板无横向溢出",
          panel.minimumSizeHint().width() <= area.viewport().width() + 2,
          f"需要 {panel.minimumSizeHint().width()} / 可用 {area.viewport().width()}")
    # 默认窗口下不该需要纵向滚动：一旦挤出去，卡片底部会被切掉
    need_h = panel.minimumSizeHint().height()
    have_h = area.viewport().height()
    check(f"{key} 面板一行排得下", need_h <= have_h,
          f"需要 {need_h} / 可用 {have_h}")
    sc.close()

print()
ok = sum(1 for r in results if r[0])
for good, name, detail in results:
    print(("PASS " if good else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
print(f"\n{ok}/{len(results)} 通过")
sys.exit(0 if ok == len(results) else 1)
