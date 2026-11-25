# -*- coding: utf-8 -*-
"""生成抖音竖屏介绍图卡（1080x1920）。

截图全部来自真实绘制代码：小条用 render_bar_image 现场渲染，
设置中心用离屏 grab。改动界面后重跑本脚本即可整组更新。

    QT_QPA_PLATFORM=windows python make_douyin.py
"""
import os
import sys
import tempfile
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QLinearGradient,
                         QPainter, QPainterPath, QPen)
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main  # noqa: E402

W, H = 1080, 1920
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "douyin")

BG_TOP = QColor("#13161b")
BG_BOT = QColor("#0a0c0f")
CARD = QColor("#181c22")
CARD_LINE = QColor("#2a3039")
TEXT = QColor("#f4f6f8")
SUB = QColor("#98a2ae")
DIM = QColor("#6b7481")
ACCENT = QColor("#4c8dff")
GREEN = QColor("#3fbf8f")


def f(px, bold=False, family="Microsoft YaHei"):
    ft = QFont(family)
    ft.setPixelSize(px)
    ft.setBold(bold)
    return ft


# ---------------------------------------------------------------- 素材

def build_bar(app):
    bar = main.SalaryBar(app)
    bar.monthly = 12000.0
    bar.shown_earned = 638.42
    bar.shown_rate = main.per_second(12000.0)
    bar.phase = 1.0
    bar.paused = False
    bar.show_total = True
    bar.weather_data = {
        "city": "济南", "desc": "多云", "temp": 12, "tmax": 15, "tmin": 6,
        "humidity": 46, "code": 1, "at": time.time(),
    }
    return bar


def load_demo_novel(bar):
    """塞一本临时书，让小说页有正文可画（只在截图进程里有效）。"""
    text = (
        "第一章 夜行\n\n"
        "　　风从楼缝里挤过来，带着一点铁锈和尘土的味道。他把外套的领子往上拉了拉，"
        "顺手看了一眼手表，离末班车还有二十多分钟。\n\n"
        "　　街上已经没什么人了。便利店的灯亮得刺眼，收银台后面的姑娘正在低头算账。"
        "他买了一瓶水，拧开喝了两口，忽然听见远处传来一阵很轻的、金属摩擦的声音。\n\n"
        "　　那声音时断时续，像是有人在拖着一件很重的东西走路。他停下来，回头望了一眼，"
        "巷子深处什么也没有，只有一盏路灯在风里微微发晃。\n"
    )
    path = os.path.join(tempfile.gettempdir(), "_dy_demo_novel.txt")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    book = {"title": "夜行", "path": path, "pos": 240, "chapters": ["第一章 夜行"]}
    bar.shelf.current_book = lambda: book
    bar.novel.set_viewport(150.0, 30.0)
    bar.novel.load(book, text)
    bar.novel.offset = 26.0
    return book


def bar_image(bar, page, **kw):
    return main.render_bar_image(bar, page, scale=6, **kw)


def _strip_base(w, h, radius=20):
    img = QImage(int(w), int(h), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)
    grad = QLinearGradient(0, 0, 0, h)
    grad.setColorAt(0, QColor("#1e2229"))
    grad.setColorAt(1, QColor("#161a20"))
    p.fillPath(path, grad)
    p.setPen(QPen(QColor("#2d343e"), 1))
    p.drawPath(path)
    return img, p


def bar_strip(bar, page, bar_w=730, **kw):
    """放大特写：一条任务栏，小条占七成宽，手机上也看得清字。"""
    w, h = 1000, 200
    img, p = _strip_base(w, h)
    bim = bar_image(bar, page, **kw)
    bw = bar_w
    bh = bw * 32.0 / 186.0
    x = 88.0
    y = (h - bh) / 2
    # 小条底下垫一层，看起来是凹进去的一块
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 80))
    p.drawRoundedRect(QRectF(x - 8, y - 6, bw + 16, bh + 12), 12, 12)
    p.drawImage(QRectF(x, y, bw, bh), bim)

    # 左侧一个应用图标，右侧时钟，交代这是任务栏
    p.setBrush(QColor("#2d343e"))
    p.drawRoundedRect(QRectF(26, (h - 44) / 2, 44, 44), 11, 11)
    p.setPen(TEXT)
    p.setFont(f(27, True, "Consolas"))
    p.drawText(QRectF(w - 140, h / 2 - 34, 110, 34),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "11:24")
    p.setPen(SUB)
    p.setFont(f(17, False, "Consolas"))
    p.drawText(QRectF(w - 140, h / 2 + 2, 110, 26),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "11/25")
    p.end()
    return img


def taskbar_real(bar, page, w=1080):
    """真实比例的任务栏，用来说明它贴在哪儿。"""
    s = 2.0
    h = 144
    img = QImage(int(w * s), int(h * s), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(s, s)

    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 18, 18)
    grad = QLinearGradient(0, 0, 0, h)
    grad.setColorAt(0, QColor("#1e2229"))
    grad.setColorAt(1, QColor("#161a20"))
    p.fillPath(path, grad)
    p.setPen(QPen(QColor("#2d343e"), 1))
    p.drawPath(path)

    p.setPen(Qt.PenStyle.NoPen)
    for i in range(3):
        p.setBrush(QColor("#2b323c"))
        p.drawRoundedRect(QRectF(24 + i * 52, 54, 36, 36), 9, 9)

    bim = bar_image(bar, page)
    p.drawImage(QRectF(210, 24, 558, 96), bim)

    p.setPen(TEXT)
    p.setFont(f(27, True, "Consolas"))
    p.drawText(QRectF(790, 48, 150, 34), Qt.AlignmentFlag.AlignRight, "11:24")
    p.setPen(SUB)
    p.setFont(f(18, False, "Consolas"))
    p.drawText(QRectF(790, 80, 150, 26), Qt.AlignmentFlag.AlignRight, "11/25 周三")
    p.end()
    return img


def toast_card(w=940):
    """Windows 风格的通知卡片示意。"""
    h = 224
    img = QImage(w * 2, h * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(2, 2)

    path = QPainterPath()
    path.addRoundedRect(QRectF(1, 1, w - 2, h - 2), 20, 20)
    p.fillPath(path, QColor("#f5f6f8"))
    p.setPen(QPen(QColor("#d8dbe0"), 1))
    p.drawPath(path)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2b7fff"))
    p.drawRoundedRect(QRectF(42, 56, 72, 72), 18, 18)
    p.setPen(QColor("#ffffff"))
    p.setFont(f(40, True))
    p.drawText(QRectF(42, 56, 72, 72), Qt.AlignmentFlag.AlignCenter, "窝")

    p.setPen(QColor("#1a1d22"))
    p.setFont(f(33, True))
    p.drawText(QRectF(134, 42, w - 200, 40),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "窝囊费")
    p.setPen(QColor("#8b929c"))
    p.setFont(f(22))
    p.drawText(QRectF(w - 140, 42, 96, 40),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "刚刚")

    p.setPen(QColor("#22262c"))
    p.setFont(f(30, True))
    p.drawText(QRectF(134, 98, w - 200, 40),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "该喝水了")
    p.setPen(QColor("#5c646f"))
    p.setFont(f(23))
    p.drawText(QRectF(134, 150, w - 200, 34),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "已经坐了一小时，起来接杯水，顺手活动下肩颈。")
    p.end()
    return img


def grab_window(widget, panel=None, size=None):
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    if size:
        widget.resize(*size)
    if panel and hasattr(widget, "show_panel"):
        widget.show_panel(panel)
    widget.show()
    for _ in range(6):
        QApplication.processEvents()
    return widget.grab().toImage()


# ---------------------------------------------------------------- 版面

def canvas():
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    grad = QLinearGradient(0, 0, 0, H)
    grad.setColorAt(0, BG_TOP)
    grad.setColorAt(1, BG_BOT)
    p.fillRect(QRectF(0, 0, W, H), grad)
    return img, p


def draw_head(p, idx, total, kicker, title, sub=None, y=196):
    p.setFont(f(26, True, "Consolas"))
    p.setPen(QColor("#39414d"))
    p.drawText(QRectF(0, y - 4, W - 80, 34), Qt.AlignmentFlag.AlignRight,
               f"{idx:02d}/{total:02d}")

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ACCENT)
    p.drawRoundedRect(QRectF(80, y + 8, 34, 6), 3, 3)
    p.setFont(f(28, True))
    p.setPen(ACCENT)
    p.drawText(QRectF(126, y - 8, 820, 38),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, kicker)

    ty = y + 62
    tf = f(88, True)
    for line in title.split("\n"):
        p.setFont(tf)
        p.setPen(TEXT)
        p.drawText(QRectF(78, ty, W - 156, 112),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
        ty += 112

    if sub:
        p.setFont(f(36))
        p.setPen(SUB)
        p.drawText(QRectF(80, ty + 4, W - 160, 50),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub)
        ty += 66
    return ty


def draw_shot(p, shot, top, max_w=1000, radius=20):
    w = min(max_w, shot.width())
    h = shot.height() * w / shot.width()
    x = (W - w) / 2
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(12, 0, -1):
        p.setBrush(QColor(0, 0, 0, 5))
        p.drawRoundedRect(QRectF(x - i, top + 10 - i * 0.4, w + i * 2, h + i * 1.2),
                          radius + 4, radius + 4)
    p.drawImage(QRectF(x, top, w, h), shot)
    return top + h


def draw_points(p, items, top, line_h=90, size=34):
    bw = 940
    x = (W - bw) / 2
    pad_x, pad_y = 48, 42
    bh = pad_y * 2 + line_h * len(items)
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, top, bw, bh), 26, 26)
    p.fillPath(path, CARD)
    p.setPen(QPen(CARD_LINE, 1))
    p.drawPath(path)

    ty = top + pad_y
    for it in items:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(GREEN)
        p.drawEllipse(QPointF(x + pad_x + 7, ty + line_h / 2 - 1), 7, 7)
        p.setFont(f(size))
        p.setPen(QColor("#e2e7ed"))
        p.drawText(QRectF(x + pad_x + 34, ty, bw - pad_x * 2 - 34, line_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, it)
        ty += line_h
    return top + bh


def draw_foot(p, text, y):
    p.setFont(f(27))
    p.setPen(DIM)
    p.drawText(QRectF(0, y, W, 40), Qt.AlignmentFlag.AlignHCenter, text)


def draw_tags(p, tags, top, size=30):
    """一排圆角小胶囊。"""
    p.setFont(f(size, True))
    fm = QFontMetricsF(p.font())
    gap, pad = 22, 30
    total = sum(fm.horizontalAdvance(t) + pad * 2 for t in tags) + gap * (len(tags) - 1)
    x = (W - total) / 2
    for t in tags:
        w = fm.horizontalAdvance(t) + pad * 2
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, top, w, 62), 31, 31)
        p.setPen(QPen(QColor("#333b46"), 1))
        p.setBrush(QColor("#1c2129"))
        p.drawPath(path)
        p.setPen(QColor("#c7ced8"))
        p.drawText(QRectF(x, top, w, 62), Qt.AlignmentFlag.AlignCenter, t)
        x += w + gap


def draw_tiles(p, tiles, top, tile_w=296, gap=26):
    """并排的小卡片：一个大字符当图标，下面是页名和一句说明。"""
    n = len(tiles)
    total = tile_w * n + gap * (n - 1)
    x = (W - total) / 2
    th = 196
    for icon, label, hint in tiles:
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, top, tile_w, th), 24, 24)
        p.fillPath(path, CARD)
        p.setPen(QPen(CARD_LINE, 1))
        p.drawPath(path)

        p.setFont(f(54, True, "Consolas"))
        p.setPen(ACCENT)
        p.drawText(QRectF(x, top + 26, tile_w, 62), Qt.AlignmentFlag.AlignCenter, icon)

        p.setFont(f(32, True))
        p.setPen(TEXT)
        p.drawText(QRectF(x, top + 92, tile_w, 44),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, label)
        p.setFont(f(22))
        p.setPen(DIM)
        p.drawText(QRectF(x, top + 140, tile_w, 34),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, hint)
        x += tile_w + gap
    return top + th


def save(img, name):
    img.save(os.path.join(OUT_DIR, name), "PNG")
    print("  ->", name)


# ---------------------------------------------------------------- 主流程

def main_():
    os.makedirs(OUT_DIR, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    bar = build_bar(app)
    load_demo_novel(bar)

    salary = bar_strip(bar, main.PAGE_SALARY)
    word = bar_strip(bar, main.PAGE_WORD)
    spell = bar_strip(bar, main.PAGE_WORD, spelling=True, typed="ne")
    novel = bar_strip(bar, main.PAGE_NOVEL)
    weather = bar_strip(bar, main.PAGE_NOVEL, weather=True)
    toast = toast_card()
    print("素材就绪")

    total = 8

    # ---- 01 封面 ----
    img, p = canvas()
    draw_head(p, 1, total, "打工人自用 · 免安装 · 不登录",
              "把工资条\n贴在任务栏上", "每秒赚多少，抬眼就能看见")
    draw_shot(p, salary, 640, max_w=1040)
    p.setFont(f(31))
    p.setPen(DIM)
    p.drawText(QRectF(0, 886, W, 46), Qt.AlignmentFlag.AlignHCenter,
               "它只有 186 × 32，就占这么一小块")
    draw_tiles(p, [("¥", "工资条", "今天挣了多少"),
                   ("A", "单词卡", "偷偷背单词"),
                   ("文", "小说", "一行字一章")], 1060)
    draw_foot(p, "往下看，8 张图讲清楚它怎么用", 1466)
    p.end()
    save(img, "01-cover.png")

    # ---- 02 工资条 ----
    img, p = canvas()
    draw_head(p, 2, total, "01 · 工资条", "今天挣了多少\n不用再算")
    draw_shot(p, salary, 690)
    draw_points(p, [
        "实时累计，精确到分，抬眼就知道摸到哪一步",
        "两种显示：累计金额＋每秒速率，或者只看每秒",
        "月薪自己填，按每月 22 个工作日、每天 8 小时折算",
        "纯本机计算，不注册、不上传",
    ], 972, line_h=108, size=35)
    p.end()
    save(img, "02-salary.png")

    # ---- 03 单词卡 ----
    img, p = canvas()
    draw_head(p, 3, total, "02 · 单词卡", "别人以为\n你在看代码")
    draw_shot(p, word, 640)
    draw_shot(p, spell, 872)
    draw_points(p, [
        "一行英文贴在任务栏，远看就是一行普通文字",
        "空格进默写，按字母数给下划线，自己拼一遍",
        "自带 300 多个词，也能导入自己的 txt",
    ], 1120, line_h=100, size=34)
    p.end()
    save(img, "03-words.png")

    # ---- 04 摸鱼阅读 ----
    img, p = canvas()
    draw_head(p, 4, total, "03 · 摸鱼阅读", "小说藏进\n一行小字里")
    draw_shot(p, novel, 636)
    draw_points(p, [
        "导入 txt 自动分章，下次接着上次的位置读",
        "鼠标停在条上自动滚，点一下暂停，滚轮手动翻",
        "正文底下一条细进度条，读了百分之几一眼看到",
        "不想看了拖回第一页，工资条还在那儿",
    ], 936, line_h=118, size=35)
    p.end()
    save(img, "04-novel.png")

    # ---- 05 天气伪装 ----
    img, p = canvas()
    draw_head(p, 5, total, "04 · 天气伪装", "有人凑过来\n它就是天气")
    draw_shot(p, weather, 636)
    draw_points(p, [
        "鼠标一离开，正文立刻换成城市、天气、气温",
        "联网取当地天气，30 分钟更新一次",
        "数据超过 3 小时会直接标「几点更新」，不装懂",
        "同事盯着看，也只会以为你装了个天气小工具",
    ], 940, line_h=118, size=35)
    p.end()
    save(img, "05-weather.png")

    # ---- 06 健康提醒 ----
    img, p = canvas()
    draw_head(p, 6, total, "05 · 健康提醒", "该喝水了\n它替你记着")
    draw_shot(p, toast, 628)
    draw_points(p, [
        "喝水 / 起身 / 看远处，三类各设间隔",
        "只在工作日和你设的时段内提醒，下班不打扰",
        "走系统通知，不弹自家大窗口挡屏幕",
        "到点不响铃，不打断你正在打的字",
    ], 946, line_h=118, size=35)
    p.end()
    save(img, "06-remind.png")

    # ---- 07 设置中心 ----
    sc = main.SettingsCenter(bar)
    shot_set = grab_window(sc, "salary", (900, 900))
    sc.close()
    img, p = canvas()
    draw_head(p, 7, total, "06 · 设置中心", "四项分开管\n改完一键保存")
    draw_shot(p, shot_set.copy(0, 20, 880, 420), 604, max_w=1040, radius=14)
    draw_points(p, ["工资 / 单词 / 阅读 / 提醒，各占一页",
                    "月薪直接填，也有几个常用档位一键选",
                    "配色自动跟随系统深浅色"], 1170, line_h=96, size=33)
    p.end()
    save(img, "07-settings.png")

    # ---- 08 尾页 ----
    img, p = canvas()
    draw_head(p, 8, total, "就这样", "工资 · 单词 · 小说",
              "左键拖动切页 · Ctrl+Q 一键隐藏")
    draw_shot(p, salary, 646, max_w=1000)
    draw_shot(p, word, 884, max_w=1000)
    draw_shot(p, novel, 1122, max_w=1000)
    draw_foot(p, "一个 186×32 的小窗口 · 单文件 exe · 数据全在本机", 1420)
    p.end()
    save(img, "08-end.png")

    print("全部完成 ->", OUT_DIR)


if __name__ == "__main__":
    main_()
