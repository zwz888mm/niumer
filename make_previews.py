# -*- coding: utf-8 -*-
"""生成 README 用到的全部预览图。

所有小条截图都直接调 main.py 里的真实绘制函数，不是预先截好的图，
所以改了界面重跑这个脚本，README 里的图会跟着变。

    QT_QPA_PLATFORM=windows python make_previews.py
"""
import os
import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter,
                         QPainterPath, QPen)
from PyQt6.QtWidgets import QApplication

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import main  # noqa: E402

OUT = HERE
WORD = ("resilient", "/rɪˈzɪliənt/", "adj. 有韧性的")


def save(image, name):
    if image is None or image.isNull():
        raise RuntimeError(f"生成失败：{name}")
    image.save(os.path.join(OUT, name))
    print(f"  {name}  {image.width()}x{image.height()}")


def word_result_image(bar, ok):
    """拼对/拼错：paintEvent 里是整条染色 + ✓/✗，这里照着画一遍。"""
    w, h = bar.width(), bar.height()
    scale = main.PREVIEW_SCALE
    image = QImage(int(w * scale), int(h * scale),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(scale, scale)

    top = QColor(16, 185, 129, 250) if ok else QColor(229, 72, 72, 250)
    bottom = QColor(12, 150, 103, 250) if ok else QColor(190, 45, 45, 250)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 7, 7)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, top)
    g.setColorAt(1, bottom)
    p.fillPath(path, g)
    p.setPen(QPen(bar.colors()["border"], 1))
    p.drawPath(path)

    p.setPen(QColor("#ffffff"))
    icon = QFont("Microsoft YaHei")
    icon.setPixelSize(14)
    icon.setBold(True)
    p.setFont(icon)
    p.drawText(QRectF(7, 0, 18, h), Qt.AlignmentFlag.AlignVCenter,
               "✓" if ok else "✗")
    body = QFont("Consolas")
    body.setPixelSize(13)
    body.setBold(True)
    p.setFont(body)
    p.drawText(QRectF(26, 0, 140, h), Qt.AlignmentFlag.AlignVCenter,
               WORD[0] if ok else f"{WORD[0]} ✗")
    p.end()
    return image


def word_image(bar, spelling=False, typed="", result=None):
    """截出单词页的某个状态，用完还原词库和 bar 字段。"""
    idx = bar.deck.index
    saved = (bar.deck.words[idx], bar.spell_input, bar.spell_result, bar.spelling)
    bar.deck.words[idx] = WORD
    try:
        if result is None:
            return main.render_bar_image(bar, main.PAGE_WORD,
                                         spelling=spelling, typed=typed)
        return word_result_image(bar, result)
    finally:
        bar.deck.words[idx] = saved[0]
        bar.spell_input = saved[1]
        bar.spell_result = saved[2]
        bar.spelling = saved[3]


def build_bar(app):
    bar = main.SalaryBar(app)
    bar.monthly = 12000.0
    bar.earned_base = 638.42
    bar.elapsed.restart()
    bar.phase = 1.0
    bar.paused = False
    bar.show_total = True
    bar.weather_on = True
    bar.weather_data = main.demo_weather()
    return bar


def main_run():
    app = QApplication(sys.argv)
    bar = build_bar(app)

    # 深浅两条：临时改主题判定，渲染后还原
    original_theme = main.is_light_theme
    for light, name in ((True, "preview-bar-light.png"),
                        (False, "preview-bar-dark.png")):
        main.is_light_theme = lambda light=light: light
        save(main.render_bar_image(bar, main.PAGE_SALARY), name)
    main.is_light_theme = original_theme

    save(main.render_bar_image(bar, main.PAGE_SALARY), "preview-bar.png")
    save(word_image(bar), "word-normal.png")
    save(word_image(bar, spelling=True, typed="re"), "word-spelling.png")
    save(word_image(bar, result=False), "word-wrong.png")
    save(word_image(bar, result=True), "word-correct.png")
    save(main.render_bar_image(bar, main.PAGE_NOVEL), "preview-novel-inline.png")
    save(main.render_bar_image(bar, main.PAGE_NOVEL, weather=True,
                               weather_data=main.demo_weather()), "preview-weather.png")

    shot = main.render_settings_image(bar, "salary")
    if shot is not None:
        save(shot, "preview-settings.png")
    else:
        print("  preview-settings.png 生成失败")

    dlg = main.HelpDialog(bar)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dlg.show()
    for _ in range(6):
        app.processEvents()
    save(dlg.grab().toImage(), "preview-help.png")
    dlg.close()

    bar.deleteLater()
    print("完成")


if __name__ == "__main__":
    main_run()
