# -*- coding: utf-8 -*-
"""抖音竖屏宣传图 · 「你以为…其实…」反转版（1080x1920）。

一张一个反转，节奏靠引导词推进：你以为 → 其实 → 而且 → 甚至 → 不止这些。
截图仍是 main.py 真实绘制代码现场渲染，改界面重跑即可整组更新。

    QT_QPA_PLATFORM=windows python make_douyin_hook.py
"""
import os
import sys
import tempfile
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QLinearGradient,
                         QPainter, QPainterPath, QPen, QRadialGradient)
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main  # noqa: E402

W, H = 1080, 1920
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "douyin")

BG_TOP = QColor("#16191f")
BG_BOT = QColor("#0a0c0f")
CARD = QColor("#181c22")
CARD_LINE = QColor("#2a3039")
TEXT = QColor("#f5f7fa")
SUB = QColor("#9aa4b0")
DIM = QColor("#6d7683")
GOLD = QColor("#ffd60a")
BLUE = QColor("#4c8dff")
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
    grad.setColorAt(0, QColor("#1f242b"))
    grad.setColorAt(1, QColor("#161a20"))
    p.fillPath(path, grad)
    p.setPen(QPen(QColor("#2f3641"), 1))
    p.drawPath(path)
    return img, p


def bar_strip(bar, page, bar_w=742, **kw):
    """小条放进模拟任务栏：左图标、右时钟，小条占七成宽。"""
    w, h = 1000, 200
    img, p = _strip_base(w, h)
    bim = bar_image(bar, page, **kw)
    bh = bar_w * 32.0 / 186.0
    x, y = 86.0, (h - bh) / 2
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 90))
    p.drawRoundedRect(QRectF(x - 8, y - 6, bar_w + 16, bh + 12), 12, 12)
    p.drawImage(QRectF(x, y, bar_w, bh), bim)

    p.setBrush(QColor("#2f3641"))
    p.drawRoundedRect(QRectF(26, (h - 44) / 2, 44, 44), 11, 11)
    p.setPen(TEXT)
    p.setFont(f(27, True, "Consolas"))
    p.drawText(QRectF(w - 150, h / 2 - 34, 118, 34),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "11:24")
    p.setPen(SUB)
    p.setFont(f(17, False, "Consolas"))
    p.drawText(QRectF(w - 150, h / 2 + 2, 118, 26),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "11/25")
    p.end()
    return img


def toast_card(w=940):
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


# ---------------------------------------------------------------- 版面

def canvas(glow=None):
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    grad = QLinearGradient(0, 0, 0, H)
    grad.setColorAt(0, BG_TOP)
    grad.setColorAt(1, BG_BOT)
    p.fillRect(QRectF(0, 0, W, H), grad)

    if glow is not None:
        g = QRadialGradient(QPointF(120, 220), 620)
        c = QColor(glow)
        c.setAlpha(16)
        g.setColorAt(0, c)
        c2 = QColor(glow)
        c2.setAlpha(0)
        g.setColorAt(1, c2)
        p.fillRect(QRectF(0, 0, W, H), g)
    return img, p


def draw_lead(p, idx, total, lead, lead_color, big, note):
    """引导词 + 大字 + 一句说明。"""
    p.setFont(f(26, True, "Consolas"))
    p.setPen(QColor("#39414d"))
    p.drawText(QRectF(0, 132, W - 80, 34), Qt.AlignmentFlag.AlignRight,
               f"{idx:02d}/{total:02d}")

    # 引导词
    p.setFont(f(50, True))
    p.setPen(lead_color)
    p.drawText(QRectF(80, 262, W - 160, 62),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lead)

    # 大字（放不下自动降字号）
    ty = 340
    line_h = 132
    size = 112
    fm = QFontMetricsF(f(size, True))
    while fm.horizontalAdvance(big) > W - 160 and size > 60:
        size -= 6
        fm = QFontMetricsF(f(size, True))
    p.setFont(f(size, True))
    p.setPen(TEXT)
    p.drawText(QRectF(78, ty, W - 156, line_h),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, big)

    if note:
        p.setFont(f(34))
        p.setPen(SUB)
        p.drawText(QRectF(80, ty + line_h + 26, W - 160, 52),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, note)
    return ty + line_h


def draw_shot(p, shot, top, max_w=1000, radius=20):
    w = min(max_w, shot.width())
    h = shot.height() * w / shot.width()
    x = (W - w) / 2
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(14, 0, -1):
        p.setBrush(QColor(0, 0, 0, 5))
        p.drawRoundedRect(QRectF(x - i, top + 12 - i * 0.4, w + i * 2, h + i * 1.3),
                          radius + 5, radius + 5)
    p.drawImage(QRectF(x, top, w, h), shot)
    return top + h


def draw_points(p, items, top, line_h=92, size=33):
    bw = 940
    x = (W - bw) / 2
    pad_x, pad_y = 48, 40
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


def draw_foot(p, text, y, color=None):
    p.setFont(f(30, True))
    p.setPen(color or DIM)
    p.drawText(QRectF(0, y, W, 44), Qt.AlignmentFlag.AlignHCenter, text)


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

    total = 7

    # ---- 1 你以为它只能看天气 ----
    img, p = canvas(BLUE)
    draw_lead(p, 1, total, "你以为", DIM, "它只能看天气",
              "一个贴在任务栏上的天气小条，186 × 32")
    draw_shot(p, weather, 612)
    draw_points(p, ["本地实时天气，30 分钟更新一次",
                    "鼠标一碰，就换回它真正的内容",
                    "长得像系统自带的小挂件，谁看都不奇怪"], 928)
    draw_foot(p, "往下翻，后面全是你没想到的", 1440, GOLD)
    p.end()
    save(img, "1-weather.png")

    # ---- 2 其实它还能背单词 ----
    img, p = canvas(GOLD)
    draw_lead(p, 2, total, "其实", GOLD, "它还在背单词",
              "同一块地方，换一页就是一行英文")
    draw_shot(p, word, 604)
    draw_shot(p, spell, 842)
    draw_points(p, ["空格进默写，按字母数给下划线",
                    "自带 300 多个词，也能导入自己的 txt",
                    "进度按词库分开记，下次接着上次的"], 1058, line_h=84, size=32)
    draw_foot(p, "右键就能换词库，主界面只占一行", 1450)
    p.end()
    save(img, "2-words.png")

    # ---- 3 而且它还在看小说 ----
    img, p = canvas(GOLD)
    draw_lead(p, 3, total, "而且", GOLD, "它还在看小说",
              "正文就在这一条里慢慢往上爬")
    draw_shot(p, novel, 612)
    draw_points(p, ["导入 txt 自动分章，记得读到哪一页",
                    "鼠标停在条上自动滚，点一下暂停，滚轮手动翻",
                    "同事走近，鼠标一移开它立刻变天气"], 928)
    draw_foot(p, "一章看完，下一页接着爬", 1440)
    p.end()
    save(img, "3-novel.png")

    # ---- 4 甚至每秒工资都在涨 ----
    img, p = canvas(GOLD)
    draw_lead(p, 4, total, "甚至", GOLD, "每秒工资都在涨",
              "今天的钱，精确到分，一直在跳")
    draw_shot(p, salary, 612)
    draw_points(p, ["两种显示：累计金额＋每秒速率，或者只看每秒",
                    "月薪自己填，按每月 22 个工作日、每天 8 小时折算",
                    "纯本机计算，不注册、不上传"], 928)
    draw_foot(p, "抬眼看一眼，就知道今天摸到哪一步了", 1440)
    p.end()
    save(img, "4-salary.png")

    # ---- 5 不止这些 ----
    img, p = canvas(GOLD)
    draw_lead(p, 5, total, "不止这些", GOLD, "它还惦记你身体",
              "喝水、起身、看远处，到点弹一下")
    draw_shot(p, toast, 606)
    draw_points(p, ["三类提醒各自设间隔，只在工作时段响",
                    "走 Windows 系统通知，不弹自家大窗口挡屏幕",
                    "到点不响铃，不打断你正在打的字"], 922)
    draw_foot(p, "可以设成只在工作日提醒，下班就不烦你", 1440)
    p.end()
    save(img, "5-remind.png")

    # ---- 6 就一小块 ----
    img, p = canvas(BLUE)
    draw_lead(p, 6, total, "就一小块", BLUE, "186 × 32",
              "三个页面，左键拖动就换，右键出菜单")
    draw_shot(p, salary, 672, max_w=1000)
    draw_shot(p, word, 888, max_w=1000)
    draw_shot(p, novel, 1104, max_w=1000)
    draw_foot(p, "Ctrl+Q 一键隐藏 · 单文件 exe · 数据全在本机", 1392)
    p.end()
    save(img, "6-threepages.png")

    # ---- 7 这下打工有点意思了 ----
    img, p = canvas(GOLD)
    draw_lead(p, 7, total, "这下", GOLD, "打工有点意思了",
              "摸鱼摸出了工资条、单词本和一章小说")
    draw_points(p, ["免安装，单文件 exe，拷过去双击就能用",
                    "除了取天气，不联网、不注册、不上传",
                    "设置全在本机，换机拷一份就搬走",
                    "自己写给自己用的，顺手才做"], 628, line_h=100, size=33)
    draw_shot(p, salary, 1180, max_w=900)
    draw_foot(p, "你要不要也来一条", 1430, TEXT)
    p.end()
    save(img, "7-end.png")

    print("全部完成 ->", OUT_DIR)


if __name__ == "__main__":
    main_()
