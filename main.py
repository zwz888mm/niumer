"""Niumer —— 牛马打工人的桌面助手条。

窗口固定在任务栏右下角，尺寸恒定 186x32。左键按住水平拖动切换三页：
  1) 工资条：实时累计今日工钱与每秒收入
  2) 单词卡：显示单词；点一下窗口后按空格进入默写，逐字输入判定
  3) 小说页：正文直接在小条里滚动，鼠标停在条上才走，移开即停；
     鼠标一离开就换成当地天气（伪装），移回来立刻恢复小说
Ctrl+Q 或右键菜单隐藏/显示；左键轻点不隐藏窗口。
"""
import bisect
import ctypes
import datetime
import json
import math
import re
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import winreg
from ctypes import wintypes

from PyQt6.QtCore import (
    QAbstractNativeEventFilter, QEasingCurve, QElapsedTimer, QObject, QPointF,
    QRectF, QSettings, QSize, Qt, QTime, QTimer, QVariantAnimation, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetricsF, QIcon, QImage,
    QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF,
    QTextBlockFormat, QTextCursor, QTextDocument,
)
from PyQt6.QtGui import QAbstractTextDocumentLayout
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox,
    QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QSystemTrayIcon, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from niumer_words import CET4_WORDS, CET6_WORDS, KAOYAN_WORDS
from niumer_novel import BUILTIN_NOVEL_TEXT, BUILTIN_NOVEL_TITLE

DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "18:00"
DEFAULT_WORK_DAYS = 22

PAGE_SALARY, PAGE_WORD, PAGE_NOVEL, PAGE_MUYU = 0, 1, 2, 3
PAGE_COUNT = 4
PAGE_NAMES = ("工资条 · 窝囊费", "单词卡 · 偷偷背", "小说 · 摸鱼读", "电子木鱼 · 敲一敲")
VERSION = "1.1.8"
AUTHOR = "200Kg"
CONTACT_EMAIL = "zwz888123@gmail.com"
VK_SPACE = 0x20
FEEDBACK_MS = 1400

# 电子木鱼：轻点不敲，按住 250ms 后每 160ms 连击一次
MUYU_HOLD_MS = 250
MUYU_REPEAT_MS = 160
MUYU_HIT_ANIM_MS = 150        # 木鱼左右微震、计数跳动时长
MUYU_FLOAT_MIN_MS = 350
MUYU_FLOAT_MAX_MS = 600
MUYU_FLOAT_MAX = 4            # 最多同时存在的浮动文案数

# 文案池：低饱和柔和色，浅色 / 深色各一套，避免高饱和刺眼
MUYU_WORDS = ("功德+1", "财富+1", "好运+1", "开心+1", "摸鱼+1")
MUYU_COLORS_LIGHT = (
    QColor(38, 122, 86), QColor(150, 106, 30), QColor(38, 96, 158),
    QColor(150, 72, 104), QColor(104, 84, 158),
)
MUYU_COLORS_DARK = (
    QColor(127, 197, 165), QColor(217, 180, 94), QColor(127, 169, 212),
    QColor(217, 160, 181), QColor(173, 160, 212),
)

MOD_CONTROL = 0x0002
VK_Q = 0x51
WM_HOTKEY = 0x0312
HOTKEY_ID = 1

user32 = ctypes.windll.user32

# 64 位下必须声明签名，否则 HWND_TOPMOST(-1) 这类句柄参数会被截成 32 位
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.FindWindowW.restype = wintypes.HWND

HWND_TOPMOST = wintypes.HWND(-1)
GA_ROOT = 2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\Niumer_SingleInstance"
_single_instance_handle = None

# 词库目录：id -> (显示名, 词表)
DECK_LIBRARY = {
    "cet4": ("四级词汇", CET4_WORDS),
    "cet6": ("六级词汇", CET6_WORDS),
    "kaoyan": ("考研英语", KAOYAN_WORDS),
}


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, eventType, message):
        if eventType == "windows_generic_MSG":
            try:
                try:
                    address = int(message)
                except Exception:
                    address = message.__int__()
                msg = wintypes.MSG.from_address(address)
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self._callback()
                    return True, 0
            except Exception:
                pass
        return False, 0


def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def _window_rect(hwnd):
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def taskbar_geometry():
    bar_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    if not bar_hwnd:
        return None, None
    bar = _window_rect(bar_hwnd)
    tray_hwnd = user32.FindWindowExW(bar_hwnd, None, "TrayNotifyWnd", None)
    return bar, _window_rect(tray_hwnd)


def force_topmost(hwnd):
    """把窗口顶回“置顶层”的最前面：不动位置、不改大小、不抢焦点。"""
    if not hwnd:
        return
    user32.SetWindowPos(
        wintypes.HWND(hwnd), HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def window_under(hwnd):
    """窗口中心点上压着的那个顶层窗口（用来判断自己有没有被盖住）。"""
    rect = _window_rect(hwnd)
    if not rect:
        return 0
    left, top, right, bottom = rect
    # 中心点必然落在不透明的内容上；边角有空隙，不用它
    point = wintypes.POINT((left + right) // 2, (top + bottom) // 2)
    hit = user32.WindowFromPoint(point)
    if not hit:
        return 0
    return int(user32.GetAncestor(hit, GA_ROOT) or hit)


def is_light_theme():
    """读主题：优先 QSettings 覆盖值（0=跟随系统 / 1=浅色 / 2=深色）。"""
    try:
        s = QSettings("Niumer", "Niumer")
        override = int(s.value("theme_override", 0) or 0)
        if override == 1:
            return True
        if override == 2:
            return False
    except Exception:
        pass
    # 跟随 Windows
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
        winreg.CloseKey(key)
        return bool(value)
    except Exception:
        return True


def clock_time(text, fallback: str) -> QTime:
    """把 "09:00" 这类设置解析成 QTime，坏了就退回默认值。"""
    value = QTime.fromString(str(text or ""), "HH:mm")
    return value if value.isValid() else QTime.fromString(fallback, "HH:mm")


def money(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}"


def fmt_rate(rate: float) -> str:
    """每秒速率：数值越大留的小数越少，不然小条里挤成一串。"""
    if rate >= 10:
        return f"{rate:.1f}"
    if rate >= 1:
        return f"{rate:.2f}"
    if rate >= 0.01:
        return f"{rate:.3f}"
    return f"{rate:.4f}"


# 小条内部排版基准：右侧留一条固定宽度给页码指示，内容和它永远不打架
DOTS_ZONE = 34
PAD_L = 8


def fit_font(text, max_width, sizes, family="Consolas"):
    """挑一个能塞进 max_width 的字号；都塞不下就给最小号，由调用方再省略。"""
    for size in sizes:
        f = QFont(family)
        f.setPixelSize(size)
        f.setBold(True)
        if QFontMetricsF(f).horizontalAdvance(text) <= max_width:
            return f
    f = QFont(family)
    f.setPixelSize(sizes[-1])
    f.setBold(True)
    return f


def elide(font, text, width):
    """按字体宽度截断并补省略号，别让文字压到旁边的元素上。"""
    return QFontMetricsF(font).elidedText(text, Qt.TextElideMode.ElideRight, max(8.0, width))


def _resource_path(name: str) -> str:
    """定位资源：优先 exe 所在目录 → PyInstaller _MEIPASS → __file__ 目录。"""
    # 1) exe 所在目录（PyInstaller onefile 运行时目录）
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
        # 2) PyInstaller _MEIPASS 解压临时目录
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            p = os.path.join(meipass, name)
            if os.path.exists(p):
                return p
    # 3) 源码目录
    base = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(base, name)
    return p


def make_tray_icon() -> QIcon:
    """优先从 exe 同目录或打包资源加载 Niumer-head.png，找不到回退到绘制奶牛头像。"""
    icon_path = _resource_path("Niumer-head.png")
    if os.path.exists(icon_path):
        pixmap = QPixmap(icon_path)
        if not pixmap.isNull():
            # 原图是 1536x1536，补上各档尺寸，标题栏/任务栏才不会模糊
            icon = QIcon()
            for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
                icon.addPixmap(pixmap.scaled(
                    size, size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            return icon
    # 回退：正方形翠绿底 + 白色牛头 + 橙色牛角（与外部 PNG 同风格）
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    # 翠绿圆角正方形底
    painter.setBrush(QColor(16, 185, 129))
    painter.drawRoundedRect(0, 0, 64, 64, 14, 14)
    # 白色牛头（圆角矩形）
    painter.setBrush(QColor(255, 255, 255))
    painter.drawRoundedRect(16, 22, 32, 24, 8, 8)
    # 橙色牛角
    painter.setBrush(QColor(249, 115, 22))
    painter.drawPie(11, 8, 14, 16, 200 * 16, 140 * 16)   # 左角
    painter.drawPie(39, 8, 14, 16, 200 * 16, 140 * 16)   # 右角
    # 黑色眼睛
    painter.setBrush(QColor(22, 34, 29))
    painter.drawEllipse(22, 29, 5, 5)
    painter.drawEllipse(37, 29, 5, 5)
    # 鼻孔
    painter.setBrush(QColor(200, 100, 100))
    painter.drawEllipse(28, 37, 3, 3)
    painter.drawEllipse(33, 37, 3, 3)
    painter.end()
    return QIcon(pixmap)


class WordDeck:
    """词库与学习进度；内置四级 / 六级 / 考研三套，进度按词库独立保存。

    每个词的学习状态：0=未学 1=模糊(答错过) 2=已掌握(答对过且未再错)。
    状态按「单词」为键存 QSettings，切换词库互不干扰。
    """

    def __init__(self, settings):
        self.settings = settings
        self.deck_id = str(settings.value("deck_id", "cet4"))
        if self.deck_id not in DECK_LIBRARY:
            self.deck_id = "cet4"

        self.words = self._source_words()
        self.index = self._load_index()
        self.states = self._load_states()   # word -> [status, correct, wrong]
        self.combo = 0

    # ---------- 词库源 ----------
    def _source_words(self):
        return list(DECK_LIBRARY[self.deck_id][1])

    @property
    def deck_name(self):
        return DECK_LIBRARY[self.deck_id][0]

    # ---------- 持久化 ----------
    def _key(self, name):
        return f"deck_{self.deck_id}_{name}"

    def _load_index(self):
        try:
            return int(self.settings.value(self._key("index"), 0)) % len(self.words)
        except (ValueError, TypeError):
            return 0

    def _load_states(self):
        raw = self.settings.value(self._key("states"), "")
        states = {}
        for part in str(raw).split(";"):
            if not part:
                continue
            f = part.split(",")
            if len(f) == 4:
                try:
                    states[f[0]] = [int(f[1]), int(f[2]), int(f[3])]
                except ValueError:
                    pass
        return states

    def _save_states(self):
        parts = [f"{w},{v[0]},{v[1]},{v[2]}" for w, v in self.states.items()]
        self.settings.setValue(self._key("states"), ";".join(parts))

    def save(self):
        self.settings.setValue("deck_id", self.deck_id)
        self.settings.setValue(self._key("index"), self.index)
        self._save_states()

    # ---------- 学习状态 ----------
    def state_of(self, word):
        return self.states.get(word, [0, 0, 0])

    def mark(self, correct):
        """记录当前词的作答结果，返回本次状态。"""
        word = self.current()[0]
        st = list(self.state_of(word))
        if correct:
            st[1] += 1
            st[0] = 2 if st[2] == 0 else 1
            self.combo += 1
        else:
            st[2] += 1
            st[0] = 1
            self.combo = 0
        self.states[word] = st
        self._save_states()
        return st[0]

    @property
    def learned_count(self):
        return sum(1 for w in self.words if self.state_of(w[0])[0] > 0)

    @property
    def mastered_count(self):
        return sum(1 for w in self.words if self.state_of(w[0])[0] == 2)

    @property
    def fuzzy_count(self):
        return sum(1 for w in self.words if self.state_of(w[0])[0] == 1)

    def progress(self):
        return self.learned_count, len(self.words)

    # ---------- 导航 ----------
    def current(self):
        return self.words[self.index]

    def next_word(self, step=1):
        self.index = (self.index + step) % len(self.words)
        self.save()

    def goto_unlearned(self):
        """跳到下一个未掌握的词；全掌握则回到开头。"""
        n = len(self.words)
        for step in range(1, n + 1):
            idx = (self.index + step) % n
            if self.state_of(self.words[idx][0])[0] != 2:
                self.index = idx
                self.save()
                return True
        self.index = 0
        self.save()
        return False

    # ---------- 词库操作 ----------
    def select_deck(self, deck_id):
        """切换词库并加载对应进度。"""
        if deck_id not in DECK_LIBRARY:
            return False
        self.settings.setValue("deck_id", deck_id)
        self.deck_id = deck_id
        self.words = self._source_words()
        self.index = self._load_index()
        self.states = self._load_states()
        self.combo = 0
        return True

    def reset_progress(self):
        """仅清空当前词库的学习记录，保留词表。"""
        self.settings.remove(self._key("index"))
        self.settings.remove(self._key("states"))
        self.index = 0
        self.states = {}
        self.combo = 0
        self.save()


NOVEL_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5")
NOVEL_MAX_BYTES = 8 * 1024 * 1024
NOVEL_SPEED_MIN, NOVEL_SPEED_MAX = 4, 80
# 正文字号：小条只有 32px 高，可视区 30px，行高对半分就是 15px，
# 字号再大就只塞得下一行。所以上限卡在 11px，保证永远能看到完整两行。
NOVEL_FONT_MIN, NOVEL_FONT_MAX = 8, 11
NOVEL_FONT_DEFAULT = 9
# 没识别到章节标题的 txt，按这个字数虚拟分节，方便「上一节/下一节」快速跳
NOVEL_VIRTUAL_CHARS = 3000
NOVEL_MAX_CHAPTERS = 2000
# 内置短篇用这个假路径当书架主键：不用落盘，也不会和用户导入的文件撞名
BUILTIN_NOVEL_PATH = "builtin://niumer-novel"

# ---------------- 天气：鼠标离开小说页时顶上去的"普通小天气条" ----------------
WEATHER_CACHE_KEY = "weather_cache"
WEATHER_TIMEOUT = 5.0
WEATHER_DEFAULT_INTERVAL = 30  # 分钟
WEATHER_STALE_SEC = 3 * 3600

# WMO 天气代码 → 中文
WMO_TEXT = {
    0: "晴", 1: "少云", 2: "多云", 3: "阴",
    45: "有雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨", 99: "雷阵雨",
}


class MuyuCounter:
    """电子木鱼：累计计数本地持久化；浮动文案只在内存里，不保存。"""

    def __init__(self, settings):
        self.settings = settings
        try:
            self.total = max(0, int(self.settings.value("muyu_total", 0) or 0))
        except (TypeError, ValueError):
            self.total = 0
        self.hit_at = 0.0      # 最近一次敲击时刻，驱动微震与计数跳动
        self.floats = []       # [(文案, 颜色序号, 出生时刻, 寿命秒, x 起点)]

    def hit(self):
        self.total += 1
        self.settings.setValue("muyu_total", self.total)
        now = time.monotonic()
        self.hit_at = now
        i = random.randrange(len(MUYU_WORDS))
        life = random.uniform(MUYU_FLOAT_MIN_MS, MUYU_FLOAT_MAX_MS) / 1000.0
        self.floats.append((MUYU_WORDS[i], i, now, life))
        if len(self.floats) > MUYU_FLOAT_MAX:
            self.floats = self.floats[-MUYU_FLOAT_MAX:]

    def live_floats(self, now=None):
        """只保留还没飘完的文案；顺手清理过期项。"""
        now = now if now is not None else time.monotonic()
        self.floats = [f for f in self.floats if now - f[2] < f[3]]
        return self.floats

    def reset(self):
        self.total = 0
        self.hit_at = 0.0
        self.floats.clear()
        self.settings.setValue("muyu_total", 0)


def weather_desc(code):
    try:
        return WMO_TEXT.get(int(code), "未知")
    except (TypeError, ValueError):
        return "未知"


class WeatherService(QObject):
    """当地天气：IP 定位 + open-meteo 实况。

    全部请求丢到后台线程，结果用信号回主线程；界面不会因为断网卡住。
    """

    ready = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._busy = False

    def busy(self):
        return self._busy

    def refresh(self, city=None):
        if self._busy:
            return False
        self._busy = True
        threading.Thread(target=self._work, args=(city,), daemon=True).start()
        return True

    def cached(self):
        raw = self.settings.value(WEATHER_CACHE_KEY, "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    # ---- 后台线程 ----
    def _work(self, city):
        try:
            data = self._fetch(city)
        except Exception as e:  # 网络异常、解析失败都走这里
            self._busy = False
            self.failed.emit(str(e) or "网络请求失败")
            return
        self._busy = False
        self.settings.setValue(WEATHER_CACHE_KEY, json.dumps(data, ensure_ascii=False))
        self.ready.emit(data)

    def _fetch(self, city):
        """主源 open-meteo（快、结构规整），不通就换 wttr.in（能按城市名直接查）。"""
        city = (city or "").strip()
        lat = lon = None
        name = city
        if city:
            try:
                lat, lon, name = self._geocode(city)
            except Exception:
                lat = lon = None
            if lat is None:
                return self._wttr(city, city)
        else:
            try:
                lat, lon, name = self._locate()
            except Exception:
                return self._wttr("", "")
        try:
            return self._open_meteo(lat, lon, name)
        except Exception:
            return self._wttr("" if name in ("", "本地") else name, name)

    def _open_meteo(self, lat, lon, name):
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat:.4f}&longitude={lon:.4f}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            "weather_code,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min"
            "&timezone=auto&forecast_days=1"
        )
        data = self._get_json(url)
        cur = data.get("current") or {}
        daily = data.get("daily") or {}
        if "temperature_2m" not in cur:
            raise ValueError("天气数据不完整")
        temp = float(cur["temperature_2m"])
        tmax = (daily.get("temperature_2m_max") or [temp])[0]
        tmin = (daily.get("temperature_2m_min") or [temp])[0]
        return {
            "city": name,
            "temp": int(round(temp)),
            "feels": int(round(float(cur.get("apparent_temperature") or temp))),
            "humidity": int(round(float(cur.get("relative_humidity_2m") or 0))),
            "code": int(cur.get("weather_code") or 0),
            "desc": weather_desc(cur.get("weather_code") or 0),
            "tmax": int(round(float(tmax))),
            "tmin": int(round(float(tmin))),
            "wind": int(round(float(cur.get("wind_speed_10m") or 0))),
            "at": time.time(),
        }

    def _wttr(self, city, name_hint):
        """备用源：wttr.in，city 为空时按 IP 定位，中文天气描述直接给。"""
        path = urllib.parse.quote(city) if city else ""
        d = self._get_json(f"https://wttr.in/{path}?format=j1&lang=zh")
        cur = (d.get("current_condition") or [{}])[0]
        day = (d.get("weather") or [{}])[0]
        if "temp_C" not in cur:
            raise ValueError("天气数据不完整")
        desc = ""
        arr = cur.get("weatherDesc") or []
        if isinstance(arr, list) and arr:
            desc = str(arr[0].get("value") or "").strip()
        name = name_hint or ""
        if not name:
            area = (d.get("nearest_area") or [{}])[0].get("areaName") or []
            if isinstance(area, list) and area:
                name = str(area[0].get("value") or "").strip()
        return {
            "city": name or "本地",
            "temp": int(round(float(cur.get("temp_C") or 0))),
            "feels": int(round(float(cur.get("FeelsLikeC") or cur.get("temp_C") or 0))),
            "humidity": int(round(float(cur.get("humidity") or 0))),
            "code": -1,
            "desc": desc or "未知",
            "tmax": int(round(float(day.get("maxtempC") or cur.get("temp_C") or 0))),
            "tmin": int(round(float(day.get("mintempC") or cur.get("temp_C") or 0))),
            "wind": int(round(float(cur.get("windspeedKmph") or 0))),
            "at": time.time(),
        }

    def _locate(self):
        """先用 ip-api（国内可直连、返回中文城市名），失败退到 ipapi.co。"""
        try:
            d = self._get_json(
                "http://ip-api.com/json/?lang=zh-CN&fields=status,city,regionName,lat,lon"
            )
            if d.get("status") == "success" and d.get("lat") is not None:
                return float(d["lat"]), float(d["lon"]), str(d.get("city") or "本地")
        except Exception:
            pass
        d = self._get_json("https://ipapi.co/json/")
        lat, lon = d.get("latitude"), d.get("longitude")
        if lat is None or lon is None:
            raise ValueError("定位失败")
        return float(lat), float(lon), str(d.get("city") or "本地")

    def _geocode(self, city):
        """手填城市：转成经纬度，结果缓存，之后不再重复查。"""
        saved = str(self.settings.value("weather_city_name", "") or "")
        lat = self.settings.value("weather_city_lat", None)
        lon = self.settings.value("weather_city_lon", None)
        if saved == city and lat not in (None, "") and lon not in (None, ""):
            return float(lat), float(lon), city
        d = self._get_json(
            "https://geocoding-api.open-meteo.com/v1/search?name="
            + urllib.parse.quote(city) + "&count=1&language=zh&format=json"
        )
        results = d.get("results") or []
        if not results:
            raise ValueError(f"找不到城市：{city}")
        r = results[0]
        self.settings.setValue("weather_city_name", city)
        self.settings.setValue("weather_city_lat", r["latitude"])
        self.settings.setValue("weather_city_lon", r["longitude"])
        return float(r["latitude"]), float(r["longitude"]), str(r.get("name") or city)

    @staticmethod
    def _get_json(url):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=WEATHER_TIMEOUT) as resp:
                raw = resp.read()
        except urllib.error.URLError:
            # 只有系统里配了代理才值得再直连试一次，否则只是白等一个超时
            has_proxy = any(
                os.environ.get(k) for k in
                ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
            )
            if not has_proxy:
                raise
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=WEATHER_TIMEOUT) as resp:
                raw = resp.read()
        return json.loads(raw.decode("utf-8", "replace"))


def read_text_auto(path):
    """按常见中文编码依次尝试读取，返回 (文本, 编码)。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in NOVEL_ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def normalize_novel_text(text):
    """把换行统一成 \\n。QTextDocument 会把 \\r\\n / \\r 折成单个段落分隔，
    不先规范化的话，Python 里的字符下标和文档内位置会越差越远。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


_CHAPTER_PATTERNS = (
    # 第一章 / 第 12 回 / 第三卷：标题
    re.compile(r"^[ \t　]*第[ \t]*[0-9０-９零〇一二三四五六七八九十百千万两]+"
               r"[ \t]*[章节回卷部篇集](?:[^\n]{0,36})?$"),
    re.compile(r"^[ \t　]*卷[ \t]*[0-9０-９零〇一二三四五六七八九十百千万两]+"
               r"(?:[^\n]{0,36})?$"),
    re.compile(r"^[ \t　]*(?:序章|楔子|引子|前言|序言|尾声|后记|番外|终章|结局)"
               r"(?:[^\n]{0,36})?$"),
    re.compile(r"^[ \t　]*chapter[ \t]+[0-9ivxlc]+(?:[^\n]{0,36})?$", re.I),
)
# 章节标题不会以这些标点收尾，过滤掉正文里长得像标题的句子
_CHAPTER_TAIL = set("。，！？；：,.!?;:、…～~\"“”‘’」』》〉）)]}")


def parse_chapters(text):
    """从全文里挑出章节标题行，返回 [(字符位置, 标题)]。

    只认独立成行、长度 ≤ 40 的明确标题格式；重复标题（常见于前面的目录页）
    保留最后一次出现的位置，也就是正文里那一处。识别不到就返回空列表，
    由 NovelView 按固定字数虚拟分节。
    """
    text = normalize_novel_text(text)
    pos = 0
    last_of = {}
    for line in text.splitlines(keepends=True):
        raw_line = line.rstrip("\n")
        s = raw_line.strip()
        if s and len(s) <= 40 and s[-1] not in _CHAPTER_TAIL \
                and any(pat.match(raw_line) for pat in _CHAPTER_PATTERNS):
            last_of[s] = pos
        pos += len(line)
    out = sorted((p, t) for t, p in last_of.items())
    return out[:NOVEL_MAX_CHAPTERS]


class NovelShelf:
    """小说书架：书单 + 每本书的阅读位置（字符偏移），以 JSON 存进 QSettings。"""

    MAX_BOOKS = 12

    def __init__(self, settings):
        self.settings = settings
        self.books = []
        raw = settings.value("novel_shelf", "")
        if raw:
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                data = []
            if isinstance(data, list):
                for it in data:
                    if not isinstance(it, dict):
                        continue
                    p = str(it.get("path", ""))
                    if not p:
                        continue
                    chapters = []
                    for ch in (it.get("chapters") or []):
                        try:
                            chapters.append([int(ch[0]), str(ch[1])])
                        except (TypeError, ValueError, IndexError):
                            continue
                    self.books.append({
                        "path": p,
                        "title": str(it.get("title") or os.path.basename(p)),
                        "pos": int(it.get("pos", 0) or 0),
                        "total": int(it.get("total", 0) or 0),
                        "chapters": chapters,
                        "virtual": int(it.get("virtual", 0) or 0),
                        "last": int(it.get("last", 0) or 0),
                    })
        self.current = str(settings.value("novel_current", ""))
        self._ensure_builtin()

    def _ensure_builtin(self):
        """书架里始终留一本内置短篇：装好就有得读，不用先去找 txt。"""
        text = normalize_novel_text(BUILTIN_NOVEL_TEXT)
        old = self.get(BUILTIN_NOVEL_PATH)
        if old:
            # 从旧版本升级上来的条目没有章节表，文本在内存里，顺手补齐
            if not old.get("chapters") and not old.get("virtual"):
                old["chapters"] = [[p, t] for p, t in parse_chapters(text)]
                old["total"] = len(text)
                self.save()
            return
        self.books.append({
            "path": BUILTIN_NOVEL_PATH,
            "title": BUILTIN_NOVEL_TITLE,
            "pos": 0,
            "total": len(text),
            "chapters": [[p, t] for p, t in parse_chapters(text)],
            "virtual": 0,
            "last": 0,
        })
        self.save()

    def save(self):
        self.settings.setValue("novel_shelf", json.dumps(self.books, ensure_ascii=False))
        self.settings.setValue("novel_current", self.current)

    def add(self, path, text, total=None):
        """加入书架（同名路径则更新），顺手把章节目录解析好存下来。"""
        title = os.path.splitext(os.path.basename(path))[0] or path
        norm = normalize_novel_text(text)
        chapters = parse_chapters(norm)
        total = len(norm) if total is None else int(total)
        virtual = 0 if chapters else 1
        for b in self.books:
            if b["path"] == path:
                b["title"] = title
                b["total"] = total
                b["chapters"] = [[p, t] for p, t in chapters]
                b["virtual"] = virtual
                b["last"] = int(time.time())
                self.current = path
                self.save()
                return b
        book = {
            "path": path, "title": title, "pos": 0, "total": total,
            "chapters": [[p, t] for p, t in chapters],
            "virtual": virtual, "last": int(time.time()),
        }
        self.books.insert(0, book)
        del self.books[self.MAX_BOOKS:]
        self.current = path
        self.save()
        return book

    def ensure_chapters(self, book, text):
        """老版本书架里没有章节表，正文载入内存后补解析一次即可。"""
        if not book or book.get("chapters") or book.get("virtual"):
            return
        norm = normalize_novel_text(text)
        ch = parse_chapters(norm)
        book["chapters"] = [[p, t] for p, t in ch]
        book["total"] = len(norm)
        book["virtual"] = 0 if ch else 1
        self.save()

    def ensure_chapters_file(self, book):
        """旧书架条目没章节表时读一次文件补上；补过或确认无标题后不再重复读。"""
        if not book or book.get("chapters") or book.get("virtual"):
            return
        if book["path"] == BUILTIN_NOVEL_PATH:
            self.ensure_chapters(book, BUILTIN_NOVEL_TEXT)
            return
        try:
            if os.path.getsize(book["path"]) > NOVEL_MAX_BYTES:
                book["virtual"] = 1
                self.save()
                return
            text, _ = read_text_auto(book["path"])
        except OSError:
            book["virtual"] = 1
            self.save()
            return
        self.ensure_chapters(book, text)

    def chapters_for(self, path):
        """章节列表 [(字符位置, 标题)]；没有真实标题时按字数虚拟分节。"""
        b = self.get(path)
        if not b:
            return []
        self.ensure_chapters_file(b)
        ch = [[int(p), str(t)] for p, t in (b.get("chapters") or [])]
        if ch:
            return ch[:NOVEL_MAX_CHAPTERS]
        total = max(1, int(b.get("total") or 0))
        return [
            [p, f"第 {i} 段"]
            for i, p in enumerate(range(0, total, NOVEL_VIRTUAL_CHARS), 1)
        ][:NOVEL_MAX_CHAPTERS]

    def chapter_count(self, path):
        return len(self.chapters_for(path))

    def step_book(self, delta):
        """按书架顺序取上一本 / 下一本的路径（循环）。"""
        if not self.books:
            return None
        cur = self.current_book()
        idx = self.books.index(cur) if cur in self.books else 0
        return self.books[(idx + int(delta)) % len(self.books)]["path"]

    def touch(self, path):
        b = self.get(path)
        if b:
            b["last"] = int(time.time())
            self.save()

    def remove(self, path):
        self.books = [b for b in self.books if b["path"] != path]
        if self.current == path:
            self.current = self.books[0]["path"] if self.books else ""
        self.save()

    def get(self, path):
        for b in self.books:
            if b["path"] == path:
                return b
        return None

    def current_book(self):
        if not self.books:
            return None
        if self.current:
            b = self.get(self.current)
            if b:
                return b
        return self.books[0]

    def set_current(self, path):
        if self.get(path):
            self.current = path
            self.touch(path)

    def set_pos(self, path, pos, total=None):
        b = self.get(path)
        if not b:
            return
        b["pos"] = max(0, int(pos))
        if total:
            b["total"] = int(total)
        self.save()

    @staticmethod
    def percent(book):
        total = max(1, int(book.get("total") or 0))
        return min(100.0, 100.0 * book.get("pos", 0) / total)


# 提醒项默认配置：key, 显示名, 默认间隔(分钟), 标题, 正文, 默认开关
REMINDER_DEFAULTS = (
    ("water", "喝水", 60, "该喝水了", "站起来接杯水，补充一下水分。", True),
    ("move", "活动", 120, "该活动了", "离开座位走动走动，伸个懒腰。", True),
    ("eyes", "护眼", 45, "让眼睛歇歇", "看看远处或窗外，放松一下眼睛。", False),
)


def ui_palette():
    """Windows 10 settings palette. Flat, low contrast, Windows blue accent #0078D4."""
    if is_light_theme():
        return dict(
            bg="#F3F3F3", card="#FFFFFF", border="#E5E5E5",
            text="#1F1F1F", sub="#5C5C5C", faint="#8A8A8A",
            accent="#0078D4", accent_soft="#E1EFFD", accent_line="#0078D4",
            track="#E5E5E5", hover="#E9E9E9",
        )
    return dict(
        bg="#202020", card="#2D2D2D", border="#404040",
        text="#F5F5F5", sub="#B0B0B0", faint="#7A7A7A",
        accent="#0A84FF", accent_soft="#1A3A5C", accent_line="#0A84FF",
        track="#3A3A3A", hover="#353535",
    )
def dialog_style():
    """Dialog QSS - Windows 10 settings style. Flat, 4px radius, Segoe UI, Win10 blue accent.

    这条 QSS 是整个设置中心体系的**唯一权威样式来源**。所有对话框/面板都调它，
    绝对禁止在 toggle_theme 或其他地方对子控件逐个 setStyleSheet 覆盖 color/background，
    否则浅色模式会残留深色样式（白底白字）。
    """
    p = ui_palette()
    font = "'Segoe UI', 'Microsoft YaHei'"
    return f"""
        /* ===== 根层级：保证所有后代默认颜色正确 ===== */
        QDialog {{ background:{p['bg']}; color:{p['text']};
            font-family:{font}; font-size:13px; }}
        QWidget {{ color:{p['text']}; }}

        /* ===== 标签 ===== */
        QLabel {{ color:{p['text']}; background:transparent; }}
        QLabel#Hint {{ color:{p['sub']}; font-size:12px; }}
        QLabel#Subtitle {{ color:{p['sub']}; font-size:12px; }}
        QLabel#Title {{ font-size:22px; font-weight:600; color:{p['text']}; }}
        QLabel#CardTitle {{ font-size:15px; font-weight:600; color:{p['text']}; }}
        QLabel#Big {{ font-size:28px; font-weight:600; font-family:'Consolas'; color:{p['accent']}; }}

        /* ===== 卡片 / 分组 ===== */
        QFrame#Card {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:4px; }}
        QFrame#Hero {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:4px; }}
        QFrame#Nav {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:12px; color:{p['text']}; }}
        QGroupBox {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:4px;
            margin-top:14px; padding:16px 14px 14px 14px;
            font-weight:600; color:{p['text']}; }}
        QGroupBox::title {{ subcontrol-origin:margin; left:14px; padding:0 6px; color:{p['text']}; }}

        /* ===== 输入框 ===== */
        QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{
            background:{p['card']}; border:1px solid {p['border']}; border-radius:4px;
            padding:5px 10px; color:{p['text']}; selection-background-color:{p['accent']};
            selection-color:#ffffff; }}
        QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus, QComboBox:focus {{
            border:2px solid {p['accent']}; padding:4px 9px; }}
        QSpinBox QLineEdit, QDoubleSpinBox QLineEdit {{ border:none; background:transparent; padding:0; }}
        QComboBox::drop-down {{ border:none; width:20px; }}
        /* 时间选择：时和分装进同一个圆角框，看起来是一个控件而不是两个方框 */
        QFrame#TimeField {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:4px; }}
        QFrame#TimeField:hover {{ border-color:{p['accent']}; }}
        QFrame#TimeField QComboBox {{ border:none; background:transparent; padding:0 2px; }}
        QFrame#TimeField QComboBox:focus {{ border:none; padding:0 2px; }}
        QFrame#TimeField QComboBox::drop-down {{ width:12px; }}

        /* ===== 下拉弹框（这个极易漏！没覆盖的话深色主题下拉是白底黑字）===== */
        QComboBox QAbstractItemView, QAbstractItemView {{
            background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
            selection-background-color:{p['accent_soft']}; selection-color:{p['accent']};
            outline:none; }}

        /* ===== 复选框 ===== */
        QCheckBox {{ spacing:10px; color:{p['text']}; background:transparent; }}
        QCheckBox::indicator {{ width:16px; height:16px; border-radius:2px;
            border:1px solid {p['border']}; background:{p['card']}; }}
        QCheckBox::indicator:hover {{ border-color:{p['accent']}; }}
        QCheckBox::indicator:checked {{ background:{p['accent']}; border:1px solid {p['accent']}; }}

        /* ===== 按钮 ===== */
        QPushButton {{
            background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
            border-radius:4px; padding:6px 14px; font-weight:500; min-height:24px; }}
        QPushButton:hover {{ background:{p['hover']}; border-color:{p['border']}; }}
        QPushButton:pressed {{ background:{p['track']}; color:{p['text']}; }}
        QPushButton:disabled {{ color:{p['faint']}; background:{p['track']}; }}
        QPushButton#Primary {{ background:{p['accent']}; color:#ffffff;
            border:1px solid {p['accent']}; border-radius:4px; font-weight:500; }}
        QPushButton#Primary:hover {{ background:#106EBE; border:1px solid #106EBE; color:#ffffff; }}
        QPushButton#Primary:pressed {{ background:#005A9E; color:#ffffff; }}
        QPushButton#Ghost {{ background:transparent; border:1px solid transparent; color:{p['sub']}; }}
        QPushButton#Ghost:hover {{ background:{p['hover']}; color:{p['text']}; border-radius:4px; }}
        QPushButton#Nav {{ background:transparent; border:none; border-radius:4px;
            padding:10px 14px; text-align:left; color:{p['text']}; }}
        QPushButton#Nav:hover {{ background:{p['hover']}; color:{p['text']}; }}
        QPushButton#Nav:checked {{ background:{p['accent_soft']}; color:{p['accent']}; }}
        QPushButton#NavCard {{ background:transparent; border:none; border-radius:8px;
            padding:8px 10px; text-align:left; color:{p['text']}; }}
        QPushButton#NavCard:hover {{ background:{p['hover']}; color:{p['text']}; }}
        QPushButton#NavCard:checked {{ background:{p['accent_soft']}; color:{p['accent']}; }}

        /* ===== 列表 ===== */
        QListWidget {{ background:transparent; border:none; outline:none; color:{p['text']}; }}
        QListWidget::item {{ padding:8px 12px; border-radius:4px; margin:1px 0; color:{p['text']}; }}
        QListWidget::item:hover {{ background:{p['hover']}; color:{p['text']}; }}
        QListWidget::item:selected {{ background:{p['accent_soft']}; color:{p['accent']}; }}

        /* ===== 滚动条 ===== */
        QScrollBar:vertical {{ background:transparent; width:12px; margin:2px; }}
        QScrollBar::handle:vertical {{ background:{p['track']}; border-radius:2px; min-height:30px; }}
        QScrollBar::handle:vertical:hover {{ background:{p['sub']}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}

        /* ===== 滚动区域（viewport 必设！否则深色主题下 viewport 是系统默认白底）===== */
        QScrollArea {{ background:transparent; border:none; }}
        QScrollArea > QWidget > QWidget {{ background:transparent; }}
        QScrollArea > QWidget#qt_scrollarea_viewport {{ background:{p['bg']}; color:{p['text']}; }}

        /* ===== 工具提示 / 文件对话框 / 消息框 ===== */
        QToolTip {{ background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
            padding:4px 6px; border-radius:3px; }}
        QFileDialog {{ background:{p['bg']}; color:{p['text']}; }}
        QMessageBox {{ background:{p['bg']}; color:{p['text']}; }}
    """


def apply_dialog_theme(widget, extra_qss=""):
    """统一应用对话框主题：palette + QSS 双保险。

    QSS 一旦出现语法错误，Qt 会静默丢弃后续规则，导致"背景变深、文字还是黑的"。
    这里同时写 palette，保证即使 QSS 局部失效，文字仍然可读。
    """
    p = ui_palette()
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(p['bg']))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(p['text']))
    pal.setColor(QPalette.ColorRole.Base, QColor(p['card']))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(p['bg']))
    pal.setColor(QPalette.ColorRole.Text, QColor(p['text']))
    pal.setColor(QPalette.ColorRole.Button, QColor(p['card']))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(p['text']))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(p['accent']))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(p['card']))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(p['text']))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(p['faint']))
    widget.setPalette(pal)
    widget.setStyleSheet(dialog_style() + extra_qss)

def styled_message(parent, title, text, icon=QMessageBox.Icon.Information):
    """统一样式的消息弹窗。"""
    box = QMessageBox(icon, title, text, parent=parent)
    apply_dialog_theme(box)
    ok = box.addButton(QMessageBox.StandardButton.Ok)
    ok.setText("知道了")
    ok.setObjectName("Primary")
    ok.setMinimumHeight(32)
    box.exec()


def fmt_duration(seconds):
    seconds = int(max(0, seconds))
    if seconds >= 3600:
        h, m = divmod(seconds, 3600)
        return f"{h}小时{m // 60}分"
    if seconds >= 60:
        return f"{seconds // 60}分{seconds % 60}秒"
    return f"{seconds}秒"


class ReminderManager:
    """健康提醒：喝水 / 活动 / 护眼，走 Windows 系统通知。"""

    def __init__(self, settings, tray):
        self.settings = settings
        self.tray = tray
        self.items = []
        for key, name, minutes, title, body, default_on in REMINDER_DEFAULTS:
            self.items.append({
                "key": key,
                "name": name,
                "enabled": bool(int(settings.value(f"remind_{key}_on", int(default_on)))),
                "minutes": self._load_minutes(key, minutes),
                "title": str(settings.value(f"remind_{key}_title", title)),
                "body": str(settings.value(f"remind_{key}_body", body)),
                "last": time.time(),  # 启动后从零计时，避免刚开就弹通知
            })
        self.work_start = int(settings.value("remind_work_start", 9))
        self.work_end = int(settings.value("remind_work_end", 18))
        self.workdays_only = bool(int(settings.value("remind_workdays_only", 1)))
        self.duration = int(settings.value("remind_duration", 8))
        self.last_notified = None

    def _load_minutes(self, key, default_minutes):
        """读分钟数；兼容早期按小时保存的老配置（自动乘 60）。"""
        raw = self.settings.value(f"remind_{key}_minutes", None)
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
        old = self.settings.value(f"remind_{key}_hours", None)
        if old is not None:
            try:
                return float(old) * 60.0
            except (TypeError, ValueError):
                pass
        return float(default_minutes)

    def save(self):
        for it in self.items:
            k = it["key"]
            self.settings.setValue(f"remind_{k}_on", int(it["enabled"]))
            self.settings.setValue(f"remind_{k}_minutes", it["minutes"])
            self.settings.setValue(f"remind_{k}_title", it["title"])
            self.settings.setValue(f"remind_{k}_body", it["body"])
            self.settings.remove(f"remind_{k}_hours")
        self.settings.setValue("remind_work_start", self.work_start)
        self.settings.setValue("remind_work_end", self.work_end)
        self.settings.setValue("remind_workdays_only", int(self.workdays_only))
        self.settings.setValue("remind_duration", self.duration)

    def in_work_time(self, now=None):
        now = now or datetime.datetime.now()
        if self.workdays_only and now.weekday() >= 5:
            return False
        h = now.hour + now.minute / 60.0
        if self.work_start <= self.work_end:
            return self.work_start <= h < self.work_end
        return h >= self.work_start or h < self.work_end

    def notify(self, title, body):
        """调用 Windows 系统通知（托盘通知中心）。"""
        self.tray.showMessage(
            title, body,
            QSystemTrayIcon.MessageIcon.Information,
            self.duration * 1000,
        )

    def check(self):
        """每秒调用；到点则发通知。返回本次触发的提醒名列表。"""
        if not self.in_work_time():
            return []
        now = time.time()
        fired = []
        for it in self.items:
            if not it["enabled"]:
                continue
            if now - it["last"] >= it["minutes"] * 60:
                it["last"] = now
                self.notify(it["title"], it["body"])
                self.last_notified = it["name"]
                fired.append(it["name"])
        return fired

    def snooze(self, item, minutes=10):
        """某条提醒延后 N 分钟。"""
        item["last"] = time.time() - item["minutes"] * 60 + minutes * 60

    def test(self):
        self.notify("Niumer · 通知测试", "这条就是 Windows 系统通知，到点会这样提醒你活动、喝水。")

    def next_due(self):
        """返回 (剩余秒数, 提醒名)；无启用项返回 None。"""
        now = time.time()
        best = None
        for it in self.items:
            if not it["enabled"]:
                continue
            remain = it["minutes"] * 60 - (now - it["last"])
            if best is None or remain < best[0]:
                best = (remain, it["name"])
        return best


class _FlatStepper:
    """数字框的上下小三角自己画。

    原生按钮在深色主题下是一块浅灰底，跟卡片不是一个色；全部交给 QSS 又画不出箭头。
    所以关掉原生按钮，右侧自己画一对三角，点右半边就是加/减。
    """

    RIGHT_PAD = 20

    def _init_stepper(self):
        self.setButtonSymbols(self.ButtonSymbols.NoButtons)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 关掉原生按钮后，QSS 会把内部编辑框算成 1px 宽（Qt 的老毛病），
        # 这里按自己的尺寸摆一遍：左边留内边距，右边给箭头让位。
        le = self.lineEdit()
        if le is not None:
            le.setGeometry(
                9, 2, max(10, self.width() - 9 - self.RIGHT_PAD), self.height() - 4
            )

    def paintEvent(self, event):
        super().paintEvent(event)
        pal = ui_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() - 11.0
        cy = self.height() / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal["sub"]))
        painter.drawPolygon(QPolygonF([
            QPointF(cx - 3.4, cy - 3.0), QPointF(cx + 3.4, cy - 3.0),
            QPointF(cx, cy - 7.4),
        ]))
        painter.drawPolygon(QPolygonF([
            QPointF(cx - 3.4, cy + 3.0), QPointF(cx + 3.4, cy + 3.0),
            QPointF(cx, cy + 7.4),
        ]))
        painter.setPen(QPen(QColor(pal["border"]), 1))
        painter.drawLine(QPointF(cx - 6.5, cy), QPointF(cx + 6.5, cy))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().x() >= self.width() - 22:
            up = event.position().y() < self.height() / 2.0
            self.stepBy(1 if up else -1)
            return
        super().mousePressEvent(event)


class FlatSpin(_FlatStepper, QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_stepper()


class FlatDoubleSpin(_FlatStepper, QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_stepper()


class DropCombo(QComboBox):
    """右侧自己画小三角的下拉框。

    QSS 把原生下拉按钮的边框去掉后箭头也跟着没了，光看一个方框想不到能点；
    这里在右边补一个三角，深浅色都跟着主题走。
    """

    def paintEvent(self, event):
        super().paintEvent(event)
        pal = ui_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() - 6.0
        cy = self.height() / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal["sub"]))
        painter.drawPolygon(QPolygonF([
            QPointF(cx - 3.6, cy - 1.8), QPointF(cx + 3.6, cy - 1.8),
            QPointF(cx, cy + 2.6),
        ]))
        painter.end()


class TimeField(QFrame):
    """时间输入：一个圆角框里放「时:分」两个下拉，看起来像个整体控件。

    比一个框里塞可打字的 QTimeEdit 稳：只能从 00-23 / 00-59 里选，
    选不出 25:70 这种非法值，也不会因为输入法/光标搞出一堆怪状态。
    """

    changed = pyqtSignal()

    def __init__(self, value: QTime, parent=None):
        super().__init__(parent)
        self.setObjectName("TimeField")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 2, 5, 2)
        lay.setSpacing(2)

        self.hour = DropCombo()
        self.minute = DropCombo()
        clock_font = QFont("Consolas")
        clock_font.setPixelSize(14)
        for box, count in ((self.hour, 24), (self.minute, 60)):
            for i in range(count):
                box.addItem(f"{i:02d}", i)
            box.setFont(clock_font)
            box.setFixedWidth(40)
            box.setMinimumHeight(30)
            box.setCursor(Qt.CursorShape.PointingHandCursor)
            box.setMaxVisibleItems(10)
            box.currentIndexChanged.connect(lambda _: self.changed.emit())
        self.hour.setCurrentIndex(value.hour())
        self.minute.setCurrentIndex(value.minute())

        colon = QLabel(":")
        colon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        colon.setFixedWidth(8)
        colon.setFont(clock_font)

        lay.addWidget(self.hour)
        lay.addWidget(colon)
        lay.addWidget(self.minute)

    def time(self) -> QTime:
        return QTime(self.hour.currentData(), self.minute.currentData())

    def set_time(self, value: QTime):
        self.hour.setCurrentIndex(value.hour())
        self.minute.setCurrentIndex(value.minute())


class RatioBar(QWidget):
    """细进度条。

    原来用 QFrame 里塞个子 QFrame 并按当时的宽度算像素，窗口一拉宽就错位；
    这里改成自绘，比例存起来，随控件宽度自动重画。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ratio = 0.0
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_ratio(self, ratio):
        ratio = 0.0 if ratio is None else max(0.0, min(1.0, float(ratio)))
        if abs(ratio - self.ratio) > 1e-4:
            self.ratio = ratio
            self.update()

    def paintEvent(self, event):
        p = ui_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p["track"]))
        painter.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        if self.ratio > 0:
            painter.setBrush(QColor(p["accent"]))
            # 进度很低时（比如 2600 个词背了 2 个）也要留一节看得见的头
            painter.drawRoundedRect(
                QRectF(0, 0, max(h * 1.3, w * self.ratio), h), r, r)
        painter.end()


class _BookDelegate(QStyledItemDelegate):
    """书架行：书名靠左、进度靠右对齐，选中时整行高亮。

    原来用 setItemWidget 塞一行控件，列表算出来的行高只有 9px，
    文字被压成 0 高度整行看不见，所以改成自己画。
    """

    PCT_ROLE = int(Qt.ItemDataRole.UserRole) + 1
    CURRENT_ROLE = int(Qt.ItemDataRole.UserRole) + 2
    ARROW_W = 14  # 左侧固定预留「当前书」箭头的位置，所有行都缩进同样的量

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        pal = ui_palette()
        rect = option.rect.adjusted(10, 0, -10, 0)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        pct = str(index.data(self.PCT_ROLE) or "")
        current = bool(index.data(self.CURRENT_ROLE))

        font = QFont(option.font)
        font.setBold(current)
        pct_font = QFont(option.font)
        pct_w = QFontMetricsF(pct_font).horizontalAdvance(pct) + 10 if pct else 0.0
        text_left = rect.left() + self.ARROW_W
        text_w = max(20.0, rect.width() - pct_w - self.ARROW_W)

        painter.save()
        if current:
            painter.setPen(QColor(pal["accent"]))
            painter.drawText(
                QRectF(rect.left(), rect.top(), self.ARROW_W, rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "▸",
            )
        painter.setFont(font)
        painter.setPen(QColor(pal["text"] if enabled else pal["sub"]))
        painter.drawText(
            QRectF(text_left, rect.top(), text_w, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elide(font, title, text_w),
        )
        if pct:
            painter.setFont(pct_font)
            painter.setPen(QColor(pal["sub"]))
            painter.drawText(
                QRectF(rect.left(), rect.top(), rect.width(), rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                pct,
            )
        painter.restore()


class _BasePanel(QWidget):
    """设置面板基类：统一配色。"""

    def __init__(self, bar):
        super().__init__()
        self.bar = bar
        apply_dialog_theme(self)


class AppearancePanel(_BasePanel):
    """Appearance panel - Win10 style."""

    def __init__(self, bar):
        super().__init__(bar)
        s = bar.settings
        current = int(s.value("theme_override", 0) or 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title
        title = QLabel("选择主题")
        title.setObjectName("Title")
        title.setContentsMargins(24, 20, 24, 12)
        root.addWidget(title)

        # Theme picker row (like Win10 settings)
        row1 = QFrame()
        row1.setObjectName("Card")
        rl = QHBoxLayout(row1)
        rl.setContentsMargins(24, 14, 24, 14)
        rl.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(2)
        lbl = QLabel("主题模式")
        lbl.setObjectName("CardTitle")
        sub = QLabel("浅色、深色，或跟随系统")
        sub.setObjectName("Hint")
        left_col.addWidget(lbl)
        left_col.addWidget(sub)
        rl.addLayout(left_col, 1)

        self.combo = QComboBox()
        self.combo.addItem("跟随系统", 0)
        self.combo.addItem("浅色", 1)
        self.combo.addItem("深色", 2)
        self.combo.setCurrentIndex(current)
        self.combo.setFixedWidth(180)
        rl.addWidget(self.combo, 0, Qt.AlignmentFlag.AlignRight)
        root.addWidget(row1)

        root.addStretch(1)

    def apply(self):
        self.bar.settings.setValue("theme_override", self.combo.currentData())
        self.bar.settings.sync()
        self.bar.update_tip()


class SalaryPanel(_BasePanel):
    """工资面板：月薪、上下班时间、每月工作日、快捷预设、计时操作。"""

    def __init__(self, bar):
        super().__init__(bar)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("Hero")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(1)
        cap = QLabel("每秒进账")
        cap.setObjectName("Hint")
        self.preview = QLabel()
        self.preview.setObjectName("Big")
        self.detail = QLabel()
        self.detail.setObjectName("Hint")
        hl.addWidget(cap)
        hl.addWidget(self.preview)
        hl.addWidget(self.detail)
        root.addWidget(hero)

        card = QFrame()
        card.setObjectName("Card")
        cl = QFormLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)
        self.spin = FlatDoubleSpin()
        self.spin.setDecimals(2)
        self.spin.setRange(0.0, 10_000_000.0)
        self.spin.setPrefix("¥ ")
        self.spin.setValue(bar.monthly)
        self.spin.setMinimumHeight(34)
        # 数字框不需要占满整行，铺到 490px 宽看着空
        self.spin.setMaximumWidth(190)
        self.spin.valueChanged.connect(self.update_preview)
        cl.addRow("月薪：", self.spin)
        presets = QFrame()
        pl = QHBoxLayout(presets)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        for value in (3000, 5000, 8000, 12000, 20000):
            btn = QPushButton(f"¥{value:,}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, v=value: self.spin.setValue(v))
            pl.addWidget(btn)
        cl.addRow("快捷预设：", presets)
        root.addWidget(card)

        # 时间口径：上下班时间 + 每月工作日，工资按今天已过去的上班时间折算
        work = QFrame()
        work.setObjectName("Card")
        wl = QHBoxLayout(work)
        wl.setContentsMargins(16, 10, 16, 10)
        wl.setSpacing(6)
        self.start_field = TimeField(bar.work_start)
        self.end_field = TimeField(bar.work_end)
        self.days_spin = FlatSpin()
        self.days_spin.setRange(1, 31)
        self.days_spin.setValue(bar.work_days)
        self.days_spin.setFixedWidth(78)
        self.days_spin.setMinimumHeight(34)
        self.days_spin.valueChanged.connect(self.update_preview)
        self.start_field.changed.connect(self.update_preview)
        self.end_field.changed.connect(self.update_preview)
        wl.addWidget(QLabel("上班"))
        wl.addWidget(self.start_field)
        wl.addSpacing(10)
        wl.addWidget(QLabel("下班"))
        wl.addWidget(self.end_field)
        wl.addSpacing(12)
        wl.addWidget(QLabel("每月工作日"))
        wl.addWidget(self.days_spin)
        wl.addWidget(QLabel("天"))
        wl.addStretch(1)
        root.addWidget(work)

        self.warn = QLabel()
        self.warn.setStyleSheet("color:#d13438; font-size:12px;")
        self.warn.hide()
        root.addWidget(self.warn)

        ops = QFrame()
        ops.setObjectName("Card")
        ol = QHBoxLayout(ops)
        ol.setContentsMargins(14, 12, 14, 12)
        ol.setSpacing(10)
        self.pause_btn = QPushButton()
        self.view_btn = QPushButton()
        reset_btn = QPushButton("重置累计金额")
        for b in (self.pause_btn, self.view_btn, reset_btn):
            b.setMinimumHeight(34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            ol.addWidget(b)
        self.pause_btn.clicked.connect(self.on_pause)
        self.view_btn.clicked.connect(self.on_view)
        reset_btn.clicked.connect(bar.reset_earned)
        root.addWidget(ops)
        root.addStretch(1)

        self.refresh_ops()
        self.update_preview()

    def start_time(self) -> QTime:
        return self.start_field.time()

    def end_time(self) -> QTime:
        return self.end_field.time()

    def update_preview(self):
        day_seconds = self.day_seconds()
        if day_seconds <= 0:
            self.preview.setText("¥0.0000")
            self.detail.setText("下班时间要晚于上班时间")
            self.warn.setText("下班时间必须晚于上班时间，调整后才能保存。")
            self.warn.show()
            return
        self.warn.hide()
        rate = self.preview_rate()
        self.preview.setText(f"¥{rate:.4f}")
        hours = f"{day_seconds / 3600:g}"
        self.detail.setText(
            f"按 {self.days_spin.value()}天 × {hours}小时算 · "
            f"一天约 ¥{rate * day_seconds:,.0f}"
        )

    def day_seconds(self) -> int:
        return max(0, self.start_time().secsTo(self.end_time()))

    def preview_rate(self) -> float:
        month_seconds = self.day_seconds() * self.days_spin.value()
        return self.spin.value() / month_seconds if month_seconds else 0.0

    def refresh_ops(self):
        self.pause_btn.setText("继续计时" if self.bar.paused else "暂停计时")
        self.view_btn.setText("显示每秒" if self.bar.show_total else "显示累计")

    def on_pause(self):
        self.bar.toggle_pause()
        self.refresh_ops()

    def on_view(self):
        self.bar.toggle_view()
        self.refresh_ops()

    def apply(self):
        bar = self.bar
        monthly = self.spin.value()
        start = self.start_time()
        end = self.end_time()
        days = self.days_spin.value()
        if start.secsTo(end) <= 0:
            # 下班早于上班，折算不出工时：挡住保存，把原因标出来
            self.update_preview()
            return False
        changed = (
            abs(monthly - bar.monthly) > 1e-9
            or start != bar.work_start
            or end != bar.work_end
            or days != bar.work_days
        )
        if not changed:
            return True
        bar.monthly = monthly
        bar.work_start = start
        bar.work_end = end
        bar.work_days = days
        bar.settings.setValue("monthly_salary", monthly)
        bar.settings.setValue("work_start", start.toString("HH:mm"))
        bar.settings.setValue("work_end", end.toString("HH:mm"))
        bar.settings.setValue("work_days", days)
        bar.reset_day = None   # 口径变了，之前的清零基准作废
        bar.shown_earned = bar.earned
        bar.shown_rate = bar.rate
        bar.update_tip()
        return True


class WordsPanel(_BasePanel):
    """单词卡面板：词库选择、学习进度与续背。"""

    def __init__(self, bar):
        super().__init__(bar)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        head = QLabel("偷偷背单词，进度实时保存，下次接着背")
        head.setObjectName("Title")
        root.addWidget(head)

        # 词库选择卡
        pick = QFrame()
        pick.setObjectName("Card")
        pl = QVBoxLayout(pick)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setSpacing(10)
        pl.addWidget(QLabel("选择词库"))
        self.deck_buttons = {}
        row = QHBoxLayout()
        row.setSpacing(10)
        for did, label in (
            ("cet4", "四级词汇"),
            ("cet6", "六级词汇"),
            ("kaoyan", "考研英语"),
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, d=did: self.on_deck(d))
            row.addWidget(btn)
            self.deck_buttons[did] = btn
        pl.addLayout(row)
        self.deck_hint = QLabel()
        self.deck_hint.setObjectName("Hint")
        pl.addWidget(self.deck_hint)
        root.addWidget(pick)

        # 学习进度卡
        prog = QFrame()
        prog.setObjectName("Card")
        gl = QVBoxLayout(prog)
        gl.setContentsMargins(16, 14, 16, 14)
        gl.setSpacing(10)
        self.stat = QLabel()
        self.stat.setObjectName("CardTitle")
        gl.addWidget(self.stat)
        self.progress_bar = RatioBar()
        gl.addWidget(self.progress_bar)
        self.detail = QLabel()
        self.detail.setObjectName("Hint")
        gl.addWidget(self.detail)
        nav = QHBoxLayout()
        nav.setSpacing(10)
        b_continue = QPushButton("从上次继续")
        b_next = QPushButton("跳到未掌握")
        b_reset = QPushButton("重置进度")
        b_continue.clicked.connect(self.on_continue)
        b_next.clicked.connect(self.on_next_unmastered)
        b_reset.clicked.connect(self.on_reset_progress)
        for b in (b_continue, b_next, b_reset):
            b.setMinimumHeight(34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            nav.addWidget(b)
        gl.addLayout(nav)
        root.addWidget(prog)
        root.addStretch(1)

        self.refresh()

    def refresh(self):
        deck = self.bar.deck
        learned, total = deck.progress()
        pct = round(learned * 100 / total) if total else 0
        self.stat.setText(f"{deck.deck_name} · 第 {deck.index + 1}/{total} 词 · 已学 {pct}%")
        self.progress_bar.set_ratio(learned / total if total else 0.0)
        self.detail.setText(
            f"已学 {learned} · 已掌握 {deck.mastered_count} · 待巩固 {deck.fuzzy_count} · "
            f"未学 {total - learned}"
        )
        for did, btn in self.deck_buttons.items():
            active = did == deck.deck_id
            btn.setChecked(active)
            if active:
                btn.setObjectName("Primary")
            else:
                btn.setObjectName("")
            btn.setStyleSheet("")
            btn.style().polish(btn)
        if deck.deck_id == "kaoyan":
            self.deck_hint.setText(f"考研英语 {len(deck.words)} 词，按字母序排列，进度独立保存")
        elif deck.deck_id == "cet6":
            self.deck_hint.setText(f"六级词汇 {len(deck.words)} 词，按字母序排列，进度独立保存")
        else:
            self.deck_hint.setText(f"四级词汇 {len(deck.words)} 词，按字母序排列，进度独立保存")

    def on_deck(self, deck_id):
        self.bar.deck.select_deck(deck_id)
        self.bar.reset_spelling_state()
        self.bar.update_tip()
        self.bar.update()
        self.refresh()

    def on_continue(self):
        self.bar.goto_page(PAGE_WORD)
        self.bar.update_tip()
        styled_message(self, "Niumer", f"已定位到第 {self.bar.deck.index + 1} 词，接着背。")

    def on_next_unmastered(self):
        found = self.bar.deck.goto_unlearned()
        self.bar.reset_spelling_state()
        self.bar.goto_page(PAGE_WORD)
        self.bar.update_tip()
        self.bar.update()
        self.refresh()
        msg = f"跳到第 {self.bar.deck.index + 1} 词（未掌握）。" if found else "全部已掌握，已回到开头。"
        styled_message(self, "Niumer", msg)

    def on_reset_progress(self):
        self.bar.deck.reset_progress()
        self.bar.reset_spelling_state()
        self.bar.update_tip()
        self.bar.update()
        self.refresh()
        styled_message(self, "Niumer", "当前词库学习进度已清空。")

    def apply(self):
        self.refresh()


class ReminderPanel(_BasePanel):
    """健康提醒面板。"""

    THEMES = {
        "water": ("#2b9fff", "水"),
        "move": ("#16b981", "动"),
        "eyes": ("#8b5cf6", "眼"),
    }

    def __init__(self, bar):
        super().__init__(bar)
        self.manager = bar.reminders
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        head = QLabel("定时提醒你活动、喝水，别一直坐着")
        head.setObjectName("Title")
        root.addWidget(head)

        self.checks = {}
        self.spins = {}
        self.title_edits = {}
        self.body_edits = {}
        for it in self.manager.items:
            color, glyph = self.THEMES.get(it["key"], ("#2b7fff", "•"))
            qc = QColor(color)
            card = QFrame()
            card.setObjectName("Card")
            outer = QVBoxLayout(card)
            outer.setContentsMargins(14, 8, 14, 10)
            outer.setSpacing(6)

            top = QHBoxLayout()
            top.setSpacing(9)
            badge = QLabel(glyph)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(24, 24)
            badge.setStyleSheet(
                "background:rgba(%d,%d,%d,42); color:%s; border-radius:7px;"
                " font-size:12px; font-weight:bold;"
                % (qc.red(), qc.green(), qc.blue(), color)
            )
            name = QLabel(it["name"])
            name.setObjectName("CardTitle")
            check = QCheckBox("启用")
            check.setChecked(it["enabled"])
            check.setCursor(Qt.CursorShape.PointingHandCursor)
            top.addWidget(badge)
            top.addWidget(name)
            top.addStretch(1)
            top.addWidget(check)
            outer.addLayout(top)

            form = QFormLayout()
            form.setSpacing(5)
            form.setLabelAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
            )

            spin = FlatSpin()
            spin.setRange(1, 720)
            spin.setSingleStep(5)
            spin.setSuffix(" 分钟")
            spin.setValue(int(round(it["minutes"])))
            spin.setFixedWidth(100)
            spin.setMinimumHeight(30)
            interval = QWidget()
            il = QHBoxLayout(interval)
            il.setContentsMargins(0, 0, 0, 0)
            il.setSpacing(8)
            unit = QLabel("1～720 分钟")
            unit.setObjectName("Hint")
            il.addWidget(spin)
            il.addWidget(unit)
            il.addStretch(1)

            title = QLineEdit(it["title"])
            body = QLineEdit(it["body"])
            for w in (title, body):
                w.setMinimumHeight(30)
            form.addRow("间隔", interval)
            form.addRow("标题", title)
            form.addRow("内容", body)
            outer.addLayout(form)
            root.addWidget(card)

            self.checks[it["key"]] = check
            self.spins[it["key"]] = spin
            self.title_edits[it["key"]] = title
            self.body_edits[it["key"]] = body

        work_box = QGroupBox("提醒时段")
        work = QGridLayout(work_box)
        work.setContentsMargins(14, 20, 14, 14)
        work.setHorizontalSpacing(10)
        work.setVerticalSpacing(9)
        self.workdays = QCheckBox("仅工作日提醒（周一至周五）")
        self.workdays.setChecked(self.manager.workdays_only)
        self.work_start = FlatSpin()
        self.work_start.setRange(0, 23)
        self.work_start.setSuffix(" 时")
        self.work_start.setValue(self.manager.work_start)
        self.work_end = FlatSpin()
        self.work_end.setRange(1, 24)
        self.work_end.setSuffix(" 时")
        self.work_end.setValue(self.manager.work_end)
        self.duration = FlatSpin()
        self.duration.setRange(2, 30)
        self.duration.setSuffix(" 秒")
        self.duration.setValue(self.manager.duration)
        for sp in (self.work_start, self.work_end, self.duration):
            sp.setFixedWidth(96)
            sp.setMinimumHeight(30)
        work.addWidget(self.workdays, 0, 0, 1, 6)
        # 三组横排一行：开始 / 结束 / 停留，长度一致才对得齐
        work.addWidget(QLabel("开始"), 1, 0)
        work.addWidget(self.work_start, 1, 1)
        work.addWidget(QLabel("结束"), 1, 2)
        work.addWidget(self.work_end, 1, 3)
        work.addWidget(QLabel("通知停留"), 1, 4)
        work.addWidget(self.duration, 1, 5)
        work.setColumnStretch(6, 1)
        root.addWidget(work_box)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        note = QLabel("通知走 Windows 系统通知中心；被“专注助手/免打扰”拦下就收不到。")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        test_btn = QPushButton("发送测试通知")
        test_btn.setObjectName("Test")
        test_btn.setMinimumHeight(34)
        test_btn.setMinimumWidth(120)
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.clicked.connect(self.manager.test)
        bottom.addWidget(note, 1)
        bottom.addWidget(test_btn)
        root.addLayout(bottom)
        root.addStretch(1)

    def apply(self):
        for it in self.manager.items:
            k = it["key"]
            it["enabled"] = self.checks[k].isChecked()
            it["minutes"] = float(self.spins[k].value())
            it["title"] = self.title_edits[k].text().strip() or it["title"]
            it["body"] = self.body_edits[k].text().strip() or it["body"]
        self.manager.workdays_only = self.workdays.isChecked()
        self.manager.work_start = self.work_start.value()
        self.manager.work_end = self.work_end.value()
        self.manager.duration = self.duration.value()
        self.manager.save()


class NovelView:
    """条内阅读：把小说排进 QTextDocument，按像素偏移在任务栏小条里滚动。

    不做独立窗口，只在小条这一小块区域里显示两三行文字，鼠标停在条上才走。
    """

    def __init__(self, settings, shelf):
        self.settings = settings
        self.shelf = shelf
        self.doc = QTextDocument()
        self.doc.setDocumentMargin(0)
        self.doc.setUndoRedoEnabled(False)
        self.book = None
        self.offset = 0.0
        self.view_w = 150.0
        self.view_h = 28.0
        # 老版本存过 16px 这种大字号，那种值只能显示一行，直接回落到舒适的默认值；
        # 回落完顺手写回设置，下次打开就一致了
        stored_font = int(settings.value("novel_font", NOVEL_FONT_DEFAULT))
        if stored_font < NOVEL_FONT_MIN or stored_font > NOVEL_FONT_MAX:
            stored_font = NOVEL_FONT_DEFAULT
            settings.setValue("novel_font", stored_font)
        self.font_size = stored_font
        self.speed = float(settings.value("novel_speed", 14))
        self.chapters = []      # [(文档内字符位置, 标题)]，已按位置排好
        self.chapter_ys = None  # 对应的排版 Y 坐标，排版变化时置空重算

    # ---- 排版 ----
    def line_height(self):
        """两行正好铺满可视区：每行高度取可视高度的一半。"""
        return max(11.0, self.view_h / 2.0)

    def render_font_size(self):
        """实际下笔的字号：不超过行高的八成，字才不会被行框裁掉。"""
        line_h = self.line_height()
        return max(NOVEL_FONT_MIN, min(int(self.font_size), int(line_h * 0.78)))

    def set_viewport(self, width, height):
        """正文区域尺寸变化时重排；行高依赖可视高度，所以高度变了也要重排。"""
        width = max(40.0, float(width))
        height = max(12.0, float(height))
        if abs(width - self.view_w) <= 0.5 and abs(height - self.view_h) <= 0.5:
            return
        pos = self.char_pos() if self.book else 0
        self.view_h = height
        if abs(width - self.view_w) > 0.5:
            self.view_w = width
            self.doc.setTextWidth(width)
        self.chapter_ys = None
        if self.book:
            self.apply_font()
            self.offset = min(self._y_for_pos(pos), self.max_offset())

    def apply_font(self):
        size = self.render_font_size()
        line_h = self.line_height()
        font = QFont("Microsoft YaHei")
        font.setPixelSize(size)
        self.doc.setDefaultFont(font)
        cursor = QTextCursor(self.doc)
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextBlockFormat()
        # 行高锁成固定像素：两行合计正好等于可视高度，不会因为字体行距多出一截
        fmt.setLineHeight(line_h, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        fmt.setTopMargin(0)
        fmt.setBottomMargin(0)
        fmt.setLeftMargin(0)
        fmt.setRightMargin(0)
        cursor.mergeBlockFormat(fmt)
        cursor.clearSelection()

    def load(self, book, text=None):
        builtin = book["path"] == BUILTIN_NOVEL_PATH
        if not builtin and not os.path.exists(book["path"]):
            return False
        try:
            if builtin:
                text = BUILTIN_NOVEL_TEXT
            elif text is None:
                text, _ = read_text_auto(book["path"])
        except OSError:
            return False
        text = normalize_novel_text(text)
        self.book = book
        self.doc.setPlainText(text)
        self.doc.setTextWidth(self.view_w)
        self.apply_font()
        # 老版本书架没有章节表，正文已在内存里，顺手补一次
        self.shelf.ensure_chapters(book, text)
        # 以文档实际字数为准，进度百分比才和书架里的数字对得上
        book["total"] = self.doc.characterCount() - 1
        self.shelf.set_pos(book["path"], int(book.get("pos", 0) or 0), book["total"])
        self._build_chapters(book)
        self.offset = min(self._y_for_pos(int(book.get("pos", 0) or 0)), self.max_offset())
        return True

    def _build_chapters(self, book):
        """把书架里存的章节位置换算成文档内坐标。

        虚拟分节的位置本来就是按字符数切的，直接用；真实标题则用 doc.find
        从提示位置往后精确找一遍，避开换行规范化带来的下标漂移。
        """
        self.chapter_ys = None
        raw = self.shelf.chapters_for(book["path"])
        if not raw:
            self.chapters = []
            return
        if book.get("virtual"):
            last = max(1, self.doc.characterCount() - 1)
            self.chapters = [(min(int(p), last), str(t)) for p, t in raw]
            return
        out = []
        last = max(1, self.doc.characterCount() - 1)
        for p, title in raw:
            hint = max(0, min(int(p), last))
            start = QTextCursor(self.doc)
            start.setPosition(hint)
            found = self.doc.find(title, start)
            if found.isNull():
                found = self.doc.find(title, QTextCursor(self.doc))
            out.append((found.selectionStart() if not found.isNull() else hint,
                        str(title)))
        out.sort(key=lambda x: x[0])
        dedup = []
        for pos, title in out:
            if dedup and pos <= dedup[-1][0]:
                continue
            dedup.append((pos, title))
        self.chapters = dedup
        self.chapter_ys = None

    def unload(self):
        self.book = None
        self.offset = 0.0
        self.chapters = []
        self.chapter_ys = None
        self.doc.clear()

    # ---- 位置换算 ----
    def max_offset(self):
        return max(0.0, self.doc.size().height() - self.view_h)

    def _y_for_pos(self, pos):
        if self.doc.characterCount() <= 1:
            return 0.0
        pos = max(0, min(int(pos), self.doc.characterCount() - 1))
        cursor = QTextCursor(self.doc)
        cursor.setPosition(pos)
        block = cursor.block()
        top = self.doc.documentLayout().blockBoundingRect(block).top()
        layout = block.layout()
        if layout is not None:
            line = layout.lineForTextPosition(pos - block.position())
            if line.isValid():
                return top + line.y()
        return top

    def char_pos(self):
        if not self.book:
            return 0
        y = min(self.max_offset(), self.offset) + max(1.0, self.view_h * 0.45)
        pos = self.doc.documentLayout().hitTest(QPointF(3.0, y), Qt.HitTestAccuracy.FuzzyHit)
        return max(0, int(pos))

    def percent(self):
        total = self.doc.characterCount() - 1
        if total <= 0:
            return 0.0
        return min(100.0, 100.0 * self.char_pos() / total)

    def at_end(self):
        limit = self.max_offset()
        return limit <= 0 or self.offset >= limit - 0.4

    # ---- 滚动 ----
    def advance(self, dt):
        limit = self.max_offset()
        if self.offset >= limit - 0.4:
            self.offset = limit
            return False
        self.offset = min(limit, self.offset + self.speed * dt)
        return True

    def scroll_by(self, dy):
        self.offset = max(0.0, min(self.max_offset(), self.offset + dy))

    # ---- 跳转：章节 / 百分比 / 头尾 / 翻页 ----
    def chapter_list(self):
        return list(self.chapters)

    def _chapter_y_list(self):
        """章节起始的排版 Y 坐标。用 Y 比而不用字符位置，跳转和判定才是同一把尺子：
        字号、宽度一变字符位置不变，但屏幕上的行会重排。"""
        if self.chapter_ys is None:
            self.chapter_ys = [self._y_for_pos(p) for p, _ in self.chapters]
        return self.chapter_ys

    def chapter_index(self):
        """当前读到第几节（0 起）。"""
        if not self.chapters:
            return -1
        ys = self._chapter_y_list()
        idx = bisect.bisect_right(ys, self.offset + 0.5) - 1
        return max(0, idx)

    def chapter_label(self):
        if not self.chapters:
            return ""
        return self.chapters[self.chapter_index()][1]

    def goto_pos(self, pos, save=True):
        if not self.book:
            return
        self.offset = min(self._y_for_pos(pos), self.max_offset())
        if save:
            self.save()

    def goto_percent(self, pct, save=True):
        if not self.book:
            return
        total = max(1, self.doc.characterCount() - 1)
        self.goto_pos(int(total * max(0.0, min(100.0, float(pct))) / 100.0),
                      save=save)

    def goto_chapter(self, index):
        if not self.book or not self.chapters:
            return False
        i = max(0, min(len(self.chapters) - 1, int(index)))
        self.goto_pos(self.chapters[i][0])
        return True

    def step_chapter(self, delta):
        if not self.chapters:
            return False
        cur = self.chapter_index()
        nxt = cur + int(delta)
        if nxt < 0:
            self.goto_pos(0)
            return True
        return self.goto_chapter(nxt)

    def goto_start(self):
        self.goto_pos(0)

    def goto_end(self):
        self.goto_pos(max(0, self.doc.characterCount() - 1))

    def page_scroll(self, sign):
        if not self.book:
            return
        self.scroll_by(int(sign) * max(8.0, self.view_h - 6.0))
        self.save()

    def save(self):
        if not self.book:
            return
        pos = self.char_pos()
        self.book["pos"] = pos
        self.shelf.set_pos(self.book["path"], pos, self.doc.characterCount() - 1)

    def set_font_size(self, size):
        size = max(NOVEL_FONT_MIN, min(NOVEL_FONT_MAX, int(size)))
        if size == self.font_size:
            return
        pos = self.char_pos() if self.book else 0
        self.font_size = size
        self.settings.setValue("novel_font", size)
        if self.book:
            self.apply_font()
            self.chapter_ys = None
            self.offset = min(self._y_for_pos(pos), self.max_offset())

    # ---- 绘制 ----
    def draw(self, painter, rect, color):
        if self.book is None:
            return
        painter.save()
        painter.setClipRect(rect)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Text, color)
        ctx.palette = palette
        ctx.clip = QRectF(0, self.offset, rect.width(), rect.height())
        painter.translate(rect.left(), rect.top() - self.offset)
        self.doc.documentLayout().draw(painter, ctx)
        painter.restore()

class NovelPanel(_BasePanel):
    """摸鱼阅读：书架 / 章节目录 / 跳转进度 / 手感，四页收在一个面板里。

    阅读页面（小条上的绘制）一行不动，这里只补使用上的便利。
    """

    TAB_SHELF, TAB_CHAPTER, TAB_SEEK, TAB_FEEL = 0, 1, 2, 3

    def __init__(self, bar):
        super().__init__(bar)
        self.shelf = bar.shelf
        self._syncing = False
        self._chapter_path = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        head = QLabel("小说在小条里滚动；这里管书架、章节、进度和手感，改完立即生效")
        head.setObjectName("Title")
        head.setWordWrap(True)
        root.addWidget(head)

        self.tabs = QTabWidget()
        p = ui_palette()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border:1px solid {p['border']}; border-radius:8px;"
            f" background:{p['card']}; }}"
            f" QTabBar::tab {{ background:transparent; color:{p['sub']};"
            f" padding:7px 16px; }}"
            f" QTabBar::tab:selected {{ color:{p['accent']};"
            f" border-bottom:2px solid {p['accent']}; }}"
        )
        root.addWidget(self.tabs)
        self.tabs.addTab(self._build_shelf_tab(), "书架")
        self.tabs.addTab(self._build_chapter_tab(), "章节目录")
        self.tabs.addTab(self._build_seek_tab(), "跳转进度")
        self.tabs.addTab(self._build_feel_tab(), "手感与伪装")

        self.bar.weather.ready.connect(self.on_weather_signal)
        self.bar.weather.failed.connect(self.on_weather_signal)
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self.commit_seek)

        self.refresh_weather_state()
        self.refresh_list()
        self.refresh_chapters()
        self.refresh_seek()
        self.tabs.currentChanged.connect(self.on_tab_changed)

    def _buttons(self, *specs):
        """一行按钮：[(文字, 回调, 是否主按钮)]。"""
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, slot, primary in specs:
            btn = QPushButton(text)
            if primary:
                btn.setObjectName("Primary")
            btn.setMinimumHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        return row

    @staticmethod
    def _hint(text):
        lab = QLabel(text)
        lab.setObjectName("Hint")
        lab.setWordWrap(True)
        return lab

    def _build_shelf_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(9)
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(8)
        self.list = QListWidget()
        self.list.setMinimumHeight(168)
        self.list.setItemDelegate(_BookDelegate(self.list))
        self.list.itemDoubleClicked.connect(lambda *_: self.read_selected())
        self.list.currentItemChanged.connect(lambda *_: self.on_book_selection())
        cl.addWidget(self.list)
        lay.addWidget(card)
        lay.addLayout(self._buttons(
            ("导入 txt", self.import_txt, True),
            ("读这本", self.read_selected, False),
            ("移出书架", self.remove_selected, False),
            ("打开所在目录", self.open_dir_selected, False),
        ))
        lay.addLayout(self._buttons(
            ("← 上一本", lambda: self.step_book(-1), False),
            ("下一本 →", lambda: self.step_book(1), False),
            ("从头读", self.reset_selected, False),
        ))
        lay.addWidget(self._hint(
            "双击书名或点「读这本」开始看；每本书的进度、章节各自保存，切书不会串。"
        ))
        lay.addStretch(1)
        return page

    def _build_chapter_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(9)
        self.chapter_search = QLineEdit()
        self.chapter_search.setPlaceholderText("输入标题关键字过滤")
        self.chapter_search.setMinimumHeight(30)
        self.chapter_search.textChanged.connect(self.filter_chapters)
        lay.addWidget(self.chapter_search)
        self.chapter_list = QListWidget()
        self.chapter_list.setMinimumHeight(158)
        self.chapter_list.setMaximumHeight(196)
        self.chapter_list.itemDoubleClicked.connect(
            lambda *_: self.goto_chapter_selected()
        )
        lay.addWidget(self.chapter_list)
        lay.addLayout(self._buttons(
            ("← 上一节", lambda: self.step_chapter(-1), False),
            ("下一节 →", lambda: self.step_chapter(1), False),
            ("跳到选中节", self.goto_chapter_selected, True),
        ))
        self.chapter_hint = self._hint("")
        lay.addWidget(self.chapter_hint)
        lay.addStretch(1)
        return page

    def _build_seek_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(12)
        self.seek_label = QLabel("—")
        self.seek_label.setObjectName("Title")
        self.seek_label.setWordWrap(True)
        lay.addWidget(self.seek_label)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setSingleStep(10)
        self.seek_slider.setPageStep(50)
        self.seek_slider.setMinimumHeight(26)
        self.seek_slider.valueChanged.connect(self.on_seek_value)
        self.seek_slider.sliderReleased.connect(self.commit_seek)
        lay.addWidget(self.seek_slider)
        ticks = QHBoxLayout()
        for t in ("0%", "25%", "50%", "75%", "100%"):
            ticks.addWidget(QLabel(t))
            if t != "100%":
                ticks.addStretch(1)
        lay.addLayout(ticks)
        lay.addLayout(self._buttons(
            ("回到开头", lambda: self.quick_seek(0), False),
            ("−10%", lambda: self.quick_seek(-10, True), False),
            ("+10%", lambda: self.quick_seek(10, True), False),
            ("跳到末尾", lambda: self.quick_seek(100), False),
        ))
        lay.addWidget(self._hint(
            "拖动滑块立即跳，松手保存。小条上也能用：轻点取焦点后 "
            "Home / End 到头尾，PgUp / PgDn 翻页，[ ] 上下节，空格暂停。"
        ))
        lay.addStretch(1)
        return page

    def _build_feel_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)
        feel = QGroupBox("阅读手感")
        form = QFormLayout(feel)
        form.setSpacing(8)
        self.font_spin = FlatSpin()
        self.font_spin.setRange(NOVEL_FONT_MIN, NOVEL_FONT_MAX)
        self.font_spin.setSuffix(" px")
        self.font_spin.setValue(int(self.bar.novel.font_size))
        self.speed_spin = FlatSpin()
        self.speed_spin.setRange(NOVEL_SPEED_MIN, NOVEL_SPEED_MAX)
        self.speed_spin.setSingleStep(2)
        self.speed_spin.setSuffix(" px/秒")
        self.speed_spin.setValue(int(float(self.bar.settings.value("novel_speed", 14))))
        for sp in (self.font_spin, self.speed_spin):
            sp.setMinimumHeight(30)
            sp.setMaximumWidth(150)
        self.font_spin.valueChanged.connect(self.on_font_changed)
        self.speed_spin.valueChanged.connect(self.on_speed_changed)
        form.addRow("正文字号：", self.font_spin)
        form.addRow("滚动速度：", self.speed_spin)
        lay.addWidget(feel)
        lay.addWidget(self._hint(
            "小条高度固定，字号 8～11px 都能完整显示两行，再大就只剩一行了，"
            "所以上限卡在 11。鼠标停在条上才开始爬，移开立刻停。"
            "阅读位置按字序记录，重启接着读。"
        ))

        mask = QGroupBox("鼠标移开时（伪装成天气）")
        mv = QVBoxLayout(mask)
        mv.setContentsMargins(14, 18, 14, 12)
        mv.setSpacing(8)
        self.weather_check = QCheckBox("鼠标不在条上时，小说页显示当地天气")
        self.weather_check.setChecked(bool(int(self.bar.settings.value("weather_on", 1))))
        self.weather_check.toggled.connect(self.on_weather_toggle)
        mv.addWidget(self.weather_check)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.city_edit = QLineEdit(str(self.bar.settings.value("weather_city", "") or ""))
        self.city_edit.setPlaceholderText("留空＝按 IP 自动定位")
        self.city_edit.setMinimumHeight(30)
        self.city_edit.editingFinished.connect(self.on_city_changed)
        refresh_btn = QPushButton("立即刷新")
        refresh_btn.setMinimumHeight(30)
        refresh_btn.clicked.connect(self.on_weather_refresh)
        row.addWidget(QLabel("城市"))
        row.addWidget(self.city_edit, 1)
        row.addWidget(refresh_btn)
        mv.addLayout(row)
        self.weather_state = QLabel()
        self.weather_state.setObjectName("Hint")
        self.weather_state.setWordWrap(True)
        mv.addWidget(self.weather_state)
        lay.addWidget(mask)
        lay.addStretch(1)
        return page

    def on_weather_toggle(self, on):
        self.bar.weather_on = bool(on)
        self.bar.settings.setValue("weather_on", int(bool(on)))
        self.bar.update()
        if on:
            self.bar.request_weather()
        self.refresh_weather_state()

    def on_city_changed(self):
        city = self.city_edit.text().strip()
        if city == self.bar.weather_city:
            return
        self.bar.weather_city = city
        self.bar.settings.setValue("weather_city", city)
        self.bar.settings.remove("weather_city_name")
        self.bar.request_weather(force=True)
        self.refresh_weather_state()

    def on_weather_refresh(self):
        self.bar.request_weather(force=True)
        self.refresh_weather_state()

    def on_weather_signal(self, *_):
        self.refresh_weather_state()

    def refresh_weather_state(self):
        bar = self.bar
        data = bar.weather_data or {}
        if bar.weather_busy:
            self.weather_state.setText("正在获取天气…")
        elif data:
            at = time.strftime("%H:%M", time.localtime(float(data.get("at", 0) or 0)))
            self.weather_state.setText(
                f"上次 {at} · {data.get('city', '本地')} "
                f"{data.get('desc') or weather_desc(data.get('code', -1))} {data.get('temp', 0)}°"
                f" · 每 {bar.weather_interval} 分钟自动更新"
            )
        elif bar.weather_error:
            self.weather_state.setText("获取失败：" + bar.weather_error[:48])
        else:
            self.weather_state.setText("还没取过天气，切到小说页会自动请求")

    def refresh_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        current = self.shelf.current
        if not self.shelf.books:
            empty = QListWidgetItem("还没导入小说 —— 点下面「导入 txt」")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setForeground(QColor(ui_palette()["faint"]))
            empty.setSizeHint(QSize(0, 34))
            self.list.addItem(empty)
        else:
            for b in self.shelf.books:
                is_current = b["path"] == current
                item = QListWidgetItem(f"《{b['title']}》")
                item.setData(Qt.ItemDataRole.UserRole, b["path"])
                item.setData(_BookDelegate.PCT_ROLE, f"{NovelShelf.percent(b):.1f}%")
                item.setData(_BookDelegate.CURRENT_ROLE, is_current)
                n = len(b.get("chapters") or [])
                info = f"{int(b.get('total') or 0):,} 字"
                info += f" · {n} 节" if n else " · 自动分节"
                if b.get("last"):
                    info += " · 上次 " + time.strftime(
                        "%m-%d %H:%M", time.localtime(int(b["last"])))
                if b["path"] == BUILTIN_NOVEL_PATH:
                    tip = "内置短篇 · 随软件打包，点「读这本」直接看\n" + info
                else:
                    tip = b["path"] + "\n" + info
                item.setToolTip(tip)
                item.setSizeHint(QSize(0, 30))
                self.list.addItem(item)
            # 当前书默认选中，章节目录跟着它走
            row = next((i for i in range(self.list.count())
                        if self.list.item(i).data(Qt.ItemDataRole.UserRole) == current), 0)
            self.list.setCurrentRow(row)
        self.list.blockSignals(False)

    def selected_path(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def import_txt(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择小说文件", "", "文本文件 (*.txt);;所有文件 (*)"
        )
        if not paths:
            return
        last = None
        skipped = []
        big = []
        for path in paths:
            try:
                size = os.path.getsize(path)
                if size > NOVEL_MAX_BYTES:
                    skipped.append(f"{os.path.basename(path)}（超过 8MB）")
                    continue
                text, _ = read_text_auto(path)
            except OSError as e:
                skipped.append(f"{os.path.basename(path)}（{e}）")
                continue
            if not text.strip():
                skipped.append(f"{os.path.basename(path)}（空文件）")
                continue
            last = self.shelf.add(path, text)
            if len(text) > 600000:
                big.append(os.path.basename(path))
        self.refresh_list()
        self.refresh_chapters()
        self.refresh_seek()
        if last:
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == last["path"]:
                    self.list.setCurrentRow(i)
                    break
            n = self.shelf.chapter_count(last["path"])
            kind = f"识别到 {n} 节" if n and last.get("chapters") else "按字数自动分节"
            msg = (f"已加入书架：《{last['title']}》，共 {last['total']:,} 字，{kind}。"
                   "点“读这本”开始。")
            if big:
                msg += "\n\n" + "、".join(big) + " 篇幅较长，首次打开要等 1~3 秒。"
        else:
            msg = "没有可导入的文件。"
        if skipped:
            msg += "\n\n跳过：\n" + "\n".join(skipped)
        styled_message(self, "Niumer · 摸鱼阅读", msg)

    def read_selected(self):
        path = self.selected_path() or self.shelf.current
        if not path:
            styled_message(self, "Niumer · 摸鱼阅读", "书架还是空的，先导入一本 txt。")
            return
        self.shelf.set_current(path)
        self.refresh_list()
        self.bar.load_novel_book()
        self.bar.goto_page(PAGE_NOVEL)
        self.window().accept()

    def remove_selected(self):
        path = self.selected_path()
        if not path:
            return
        if path == BUILTIN_NOVEL_PATH:
            # 内置示例是随包带的，删了没处恢复；真想清空就用「从头读」
            styled_message(
                self, "Niumer · 摸鱼阅读",
                f"《{BUILTIN_NOVEL_TITLE}》是内置示例，不能移出书架。"
                "想重看可以点「从头读」。",
            )
            return
        self.shelf.remove(path)
        self.refresh_list()
        self.refresh_chapters()
        self.refresh_seek()
        if self.bar.novel.book and self.bar.novel.book["path"] == path:
            self.bar.novel.unload()
        self.bar.update_tip()
        self.bar.update()

    def reset_selected(self):
        path = self.selected_path()
        if not path:
            return
        self.shelf.set_pos(path, 0)
        self.refresh_list()
        novel = self.bar.novel
        if novel.book and novel.book["path"] == path:
            novel.book["pos"] = 0
            novel.offset = 0.0
        self.refresh_chapters()
        self.refresh_seek()
        self.bar.update_tip()
        self.bar.update()

    # ---- 标签页联动 ----
    def set_tab(self, index):
        self.tabs.setCurrentIndex(max(0, min(3, int(index))))

    def on_tab_changed(self, index):
        if index == self.TAB_CHAPTER:
            self.refresh_chapters()
        elif index == self.TAB_SEEK:
            self.refresh_seek()

    def on_book_selection(self):
        self.refresh_chapters()

    def _ensure_book(self):
        """章节 / 进度操作前，保证目标书已经载入小条。"""
        path = self._chapter_path or self.shelf.current
        if path and path != self.shelf.current:
            self.bar.novel_switch_book(path)
        elif self.bar.novel.book is None:
            self.bar.load_novel_book()
        return path

    # ---- 书架：快速换书 / 打开目录 ----
    def step_book(self, delta):
        path = self.shelf.step_book(delta)
        if not path:
            return
        self.bar.novel_switch_book(path)
        self.refresh_list()
        self.refresh_chapters()
        self.refresh_seek()

    def open_dir_selected(self):
        path = self.selected_path() or self.shelf.current
        if not path:
            return
        if path == BUILTIN_NOVEL_PATH:
            styled_message(self, "Niumer · 摸鱼阅读",
                           "内置短篇随软件打包，没有本地文件。")
            return
        folder = os.path.dirname(os.path.abspath(path))
        if os.path.isdir(folder):
            try:
                os.startfile(folder)
            except OSError:
                pass

    # ---- 章节目录 ----
    def refresh_chapters(self):
        path = self.selected_path() or self.shelf.current
        self._chapter_path = path or ""
        self.chapter_list.clear()
        b = self.shelf.get(path) if path else None
        if not b:
            self.chapter_hint.setText("书架里还没有书，先去「书架」导入一本。")
            return
        chapters = self.shelf.chapters_for(path)
        for i, (_, title) in enumerate(chapters):
            item = QListWidgetItem(f"{i + 1:>3}   {title}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.chapter_list.addItem(item)
        cur = -1
        if path == self.shelf.current and self.bar.novel.book \
                and self.bar.novel.book["path"] == path:
            cur = self.bar.novel.chapter_index()
        if 0 <= cur < self.chapter_list.count():
            item = self.chapter_list.item(cur)
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            item.setForeground(QColor(ui_palette()["accent"]))
            self.chapter_list.setCurrentRow(cur)
            self.chapter_list.scrollToItem(item)
        kind = "按原文标题识别" if b.get("chapters") else "没识别到标题，按字数自动分节"
        tail = f" · 当前：{chapters[cur][1]}" if 0 <= cur < len(chapters) else ""
        self.chapter_hint.setText(f"共 {len(chapters)} 节（{kind}）{tail}")
        self.filter_chapters(self.chapter_search.text())

    def filter_chapters(self, keyword):
        kw = str(keyword or "").strip()
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            self.chapter_list.setRowHidden(i, bool(kw) and kw not in item.text())

    def goto_chapter_selected(self):
        item = self.chapter_list.currentItem()
        if not item:
            return
        self.goto_chapter(int(item.data(Qt.ItemDataRole.UserRole)))

    def goto_chapter(self, index):
        self._ensure_book()
        self.bar.novel_goto_chapter(index)
        self.refresh_chapters()
        self.refresh_seek()

    def step_chapter(self, delta):
        self._ensure_book()
        self.bar.novel_step_chapter(delta)
        self.refresh_chapters()
        self.refresh_seek()

    # ---- 跳转进度 ----
    def refresh_seek(self):
        book = self.shelf.current_book()
        if not book:
            self.seek_label.setText("书架里还没有书")
            return
        novel = self.bar.novel
        if novel.book and novel.book["path"] == book["path"]:
            pct, ch = novel.percent(), novel.chapter_label()
        else:
            pct, ch = NovelShelf.percent(book), ""
        self._syncing = True
        self.seek_slider.setValue(int(pct * 10))
        self._syncing = False
        self.seek_label.setText(
            f"《{book['title']}》　已读 {pct:.1f}%"
            + (f"　·　{ch}" if ch else "")
        )

    def on_seek_value(self, value):
        if self._syncing:
            return
        pct = value / 10.0
        self.seek_label.setText(f"跳到 {pct:.1f}% …")
        novel = self.bar.novel
        if novel.book is None:
            self.bar.load_novel_book()
        if novel.book:
            novel.goto_percent(pct, save=False)
            self.bar.update()
            self._seek_timer.start(300)

    def commit_seek(self):
        self._seek_timer.stop()
        novel = self.bar.novel
        if novel.book:
            novel.save()
            self.shelf.touch(novel.book["path"])
        self.refresh_seek()
        self.refresh_chapters()
        self.bar.novel_refresh()

    def quick_seek(self, pct, relative=False):
        novel = self.bar.novel
        if novel.book is None:
            self.bar.load_novel_book()
        if novel.book is None:
            return
        target = novel.percent() + pct if relative else pct
        self.bar.novel_seek_percent(target)
        self.refresh_seek()
        self.refresh_chapters()

    def on_font_changed(self, value):
        self.bar.novel.set_font_size(int(value))
        self.bar.update()

    def on_speed_changed(self, value):
        self.bar.novel.speed = float(value)
        self.bar.settings.setValue("novel_speed", float(value))
        self.bar.update()

    def apply(self):
        self.shelf.save()
        self.bar.settings.setValue("novel_font", int(self.font_spin.value()))
        self.bar.settings.setValue("novel_speed", float(self.speed_spin.value()))
        self.bar.novel.font_size = int(self.font_spin.value())
        self.bar.novel.speed = float(self.speed_spin.value())
        self.bar.novel.apply_font()
        self.bar.novel.chapter_ys = None


class MuyuPanel(_BasePanel):
    """电子木鱼面板：看累计、清零，外加一句敲击说明。"""

    def __init__(self, bar):
        super().__init__(bar)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        head = QLabel("敲一下积一分功德，纯本地保存，不会上传，也没有联网请求。")
        head.setObjectName("Title")
        head.setWordWrap(True)
        root.addWidget(head)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)
        cl.addWidget(QLabel("累计功德"))
        self.count = QLabel(f"{bar.muyu.total:,}")
        self.count.setObjectName("Title")
        self.count.setStyleSheet("font-size:30px;")
        cl.addWidget(self.count)
        cl.addWidget(QLabel("功德只在点「清零」时消失，重启、换主题都不影响。"))
        root.addWidget(card)

        how = QGroupBox("怎么敲")
        hl = QVBoxLayout(how)
        hl.setContentsMargins(14, 18, 14, 14)
        hl.setSpacing(6)
        for line in (
            "点一下小条让它获得焦点，然后按空格 —— 每按一下 +1",
            "按住空格不放会连续敲击（用系统按键重复，不是计时机）",
            "鼠标按住小条超过 250ms 也会开始连击，轻点不敲",
        ):
            lab = QLabel("· " + line)
            lab.setWordWrap(True)
            hl.addWidget(lab)
        root.addWidget(how)

        clear_row = QHBoxLayout()
        clear_row.setSpacing(8)
        clear = QPushButton("功德清零")
        clear.setObjectName("Ghost")
        clear.setMinimumHeight(34)
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.clicked.connect(self.on_clear)
        goto = QPushButton("去木鱼页")
        goto.setObjectName("Primary")
        goto.setMinimumHeight(34)
        goto.setCursor(Qt.CursorShape.PointingHandCursor)
        goto.clicked.connect(lambda: (self.bar.goto_page(PAGE_MUYU), self.window().accept()))
        clear_row.addWidget(clear)
        clear_row.addWidget(goto)
        clear_row.addStretch(1)
        root.addLayout(clear_row)
        root.addStretch(1)

    def on_clear(self):
        if self.bar.muyu.total == 0:
            return
        box = QMessageBox(self)
        apply_dialog_theme(box)
        box.setWindowTitle("Niumer · 电子木鱼")
        box.setText(f"确定把累计功德 {self.bar.muyu.total:,} 清零？此操作不可恢复。")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.bar.muyu.reset()
            self.count.setText("0")

    def apply(self):
        self.bar.update_tip()
        self.bar.update()


PREVIEW_SCALE = 2.15


def render_bar_image(bar, page, weather=False, spelling=False, typed="",
                     scale=PREVIEW_SCALE, weather_data=None):
    """把某一页渲染成放大的位图，给帮助页当截图用。

    直接调真实的绘制方法，所以帮助里的图和界面上看到的一模一样，
    连深浅主题都跟着走；不依赖任何外部图片文件，单文件 exe 也能带图。
    """
    w, h = bar.width(), bar.height()
    image = QImage(int(w * scale), int(h * scale),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.scale(scale, scale)

    c = bar.colors()
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 7, 7)
    gradient = QLinearGradient(0, 0, 0, h)
    gradient.setColorAt(0, c["top"])
    gradient.setColorAt(1, c["bottom"])
    painter.fillPath(path, gradient)
    painter.setPen(QPen(c["border"], 1))
    painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)

    saved = (bar.view, bar.spelling, bar.spell_input, bar.spell_result,
             bar.weather_data, bar.hover_inside)
    try:
        bar.view = float(page)
        bar.spelling = spelling
        bar.spell_input = typed
        bar.spell_result = None
        bar.hover_inside = not weather
        if weather and weather_data is not None:
            bar.weather_data = weather_data
        if page == PAGE_SALARY:
            bar.draw_salary(painter, c)
        elif page == PAGE_WORD:
            bar.draw_word_page(painter, c)
        elif page == PAGE_NOVEL:
            if weather:
                bar.draw_weather_page(painter, c)
            else:
                bar.draw_novel_page(painter, c)
        elif page == PAGE_MUYU:
            bar.draw_muyu_page(painter, c)
        bar.draw_page_dots(bar, painter, c)
    finally:
        (bar.view, bar.spelling, bar.spell_input, bar.spell_result,
         bar.weather_data, bar.hover_inside) = saved
        painter.end()
    return image


def render_taskbar_scene(bar, scale=PREVIEW_SCALE):
    """任务栏 + 托盘 + 小条 的位置示意图。"""
    scene_w, scene_h = 300, 40
    light = is_light_theme()
    image = QImage(int(scene_w * scale), int(scene_h * scale),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#e6e9ef") if light else QColor("#2a2f37"))
    painter.drawRoundedRect(QRectF(0.5, 0.5, scene_w - 1, scene_h - 1), 9, 9)
    painter.setPen(QPen(QColor("#c9ced8") if light else QColor("#3d444e"), 1))
    painter.drawRoundedRect(QRectF(0.5, 0.5, scene_w - 1, scene_h - 1), 9, 9)
    painter.setPen(Qt.PenStyle.NoPen)

    # 右侧托盘：几个灰块 + 时间
    icon_color = QColor("#b7bfcc") if light else QColor("#4a505a")
    for x in (scene_w - 26, scene_w - 42, scene_w - 58):
        painter.setBrush(icon_color)
        painter.drawRoundedRect(QRectF(x, scene_h / 2 - 5, 10, 10), 2.5, 2.5)
    clock = QFont("Microsoft YaHei")
    clock.setPixelSize(9)
    painter.setFont(clock)
    painter.setPen(QColor("#6b7280") if light else QColor("#9aa3b2"))
    painter.drawText(QRectF(scene_w - 88, scene_h / 2 - 8, 26, 16),
                     Qt.AlignmentFlag.AlignCenter, "10:30")

    # 小条贴到托盘左侧
    bar_img = render_bar_image(bar, PAGE_SALARY, scale=scale)
    bx = scene_w - 96 - bar.width()
    by = (scene_h - bar.height()) / 2
    painter.drawImage(QRectF(bx, by, bar.width(), bar.height()), bar_img)
    painter.end()
    return image


def render_settings_image(bar, panel="salary"):
    """设置中心整窗截图：离屏渲染，不真的弹一个窗口出来。"""
    try:
        dlg = SettingsCenter(bar)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dlg.resize(880, 600)
        dlg.show_panel(panel)
        dlg.show()
        for _ in range(4):
            QApplication.processEvents()
        pixmap = dlg.grab()
        dlg.hide()
        dlg.deleteLater()
        shot = pixmap.toImage()
        # 加一圈细边框：截图和帮助页背景色接近，不描边会糊成一片
        pal = ui_palette()
        framed = QImage(shot.width() + 2, shot.height() + 2,
                        QImage.Format.Format_ARGB32_Premultiplied)
        framed.fill(QColor(pal["border"]))
        painter = QPainter(framed)
        painter.drawImage(1, 1, shot)
        painter.end()
        return framed
    except Exception:
        return None


def demo_weather():
    """帮助页里的天气示意数据（本机还没取到天气时用）。"""
    return {
        "city": "济南", "desc": "多云", "temp": 23, "tmax": 27, "tmin": 18,
        "humidity": 56, "at": time.time(),
    }


def help_pages():
    """使用说明：每节都写清楚“这是什么 / 怎么用 / 注意什么”，能配图就配图。"""
    pal = ui_palette()
    text, sub, accent = pal["text"], pal["sub"], pal["accent"]
    soft, line = pal["accent_soft"], pal["accent_line"]

    def h(t):
        return (
            f"<p style='color:{text}; font-size:15px; font-weight:bold;"
            f" margin:17px 0 4px 0;'>{t}</p>"
        )

    def p(t):
        return f"<p style='color:{text}; font-size:13px; margin:4px 0;'>{t}</p>"

    def note(t):
        return (
            f"<p style='color:{sub}; font-size:12px; margin:8px 0;"
            f" border-left:3px solid {line}; padding:2px 0 2px 9px;'>{t}</p>"
        )

    def ol(items):
        lis = "".join(f"<li style='margin:3px 0;'>{i}</li>" for i in items)
        return f"<ol style='margin:4px 0 4px 20px; color:{text}; font-size:13px;'>{lis}</ol>"

    def k(t):
        return (
            f"<span style='color:{accent}; background:{soft}; font-family:Consolas;"
            f" font-size:12px;'>&nbsp;{t}&nbsp;</span>"
        )

    def img(name, caption, width=400):
        return (
            f"<p style='margin:10px 0 2px 0;'><img src='preview/{name}.png'"
            f" width='{width}'></p>"
            f"<p style='color:{sub}; font-size:11px; margin:0 0 10px 0;'>{caption}</p>"
        )

    def table(rows):
        body = ""
        for left, right in rows:
            body += (
                "<tr>"
                f"<td width='104' align='left' style='padding:5px 14px 5px 0;"
                f" color:{text}; font-size:12px;'>{left}</td>"
                f"<td align='left' style='padding:5px 0; color:{sub};"
                f" font-size:12px;'>{right}</td>"
                "</tr>"
            )
        return f"<table cellspacing='0' cellpadding='0'>{body}</table>"

    quick = (
        h("它是什么")
        + p("一块 186×32 的小条，贴在任务栏右下角、托盘图标左边。工资条、单词卡、"
            "摸鱼阅读、电子木鱼四页都在这同一条里切换，不会另开窗口，也不会越变越大。")
        + img("taskbar", "位置示意：小条就挨着托盘图标，和时钟、音量排在一起。", 440)
        + h("三个入口")
        + ol([
            "左键按住小条左右拖 —— 四页之间切换，松手自动吸附",
            "右键小条 —— 菜单：切页、设置中心、使用帮助、隐藏窗口、退出",
            f"隐藏之后按 {k('Ctrl+Q')}，或点托盘图标，就能叫回来",
        ])
        + note("第一次用，先右键 → 设置中心 → 工资条，把月薪填上；其余默认设置就能跑起来。")
        + h("四页分别是什么")
        + table([
            ("第一页", "工资条：每秒都在涨的“工钱”，一眼看到今天赚了多少"),
            ("第二页", "单词卡：一个单词 + 音标释义，轻点后按空格可以默写"),
            ("第三页", "摸鱼阅读：小说正文在条里慢慢滚，鼠标移开自动变天气"),
            ("第四页", "电子木鱼：按空格敲一下，攒点功德，纯本地保存"),
        ])
    )

    salary = (
        h("它在算什么")
        + p("把月薪折算到秒：月薪 ÷ 每月工作日 ÷ 每天工时（上班到下班的小时数）÷ 3600 秒。"
            "显示的是「今天从上班到现在」已经过去的那些时间换来的钱 —— 中午才开机，"
            "也会把上午的部分一起算上；过了下班时间就停在整天的金额。")
        + img("salary", "第一页：左边绿点表示正在计时，右边是每秒进账速率。")
        + h("怎么设置")
        + ol([
            "右键 → 设置中心 → 工资条",
            "填月薪（也可以直接点 ¥5000 这类预设按钮）",
            "设上班、下班时间（默认 09:00 – 18:00）和每月工作日（默认 22 天）",
            "点「保存并关闭」；改完口径，屏幕上的数字立即按新口径重算",
        ])
        + h("两个常用操作")
        + ol([
            "去开会、午休：点「暂停计时」，绿点变灰，数字停住；回来点「继续计时」",
            "想只看每秒：点「显示每秒」，大数字变成速率，右边显示月薪；再点一次切回累计",
        ])
        + note("「重置累计金额」只是把今天累计的数字清零，之后从 0 接着涨，第二天自动恢复成整天口径。")
    )

    word = (
        h("平时看什么")
        + p(f"第一行是单词，第二行是音标和释义，右下角浅灰的 12/{len(CET4_WORDS)} 是学习进度。"
            f"内置四级 {len(CET4_WORDS)} 词、六级 {len(CET6_WORDS)} 词、"
            f"考研 {len(KAOYAN_WORDS)} 词，在设置里点一下就能换。")
        + img("word", "第二页：单词 + 音标释义 + 右下角进度。")
        + h("默写：把单词盖住自己拼一遍")
        + ol([
            "左键轻点一下小条，让它拿到键盘焦点",
            f"按 {k('空格')} 开始 —— 上面出现中文释义，下面按字母个数出现下划线",
            "直接敲字母，敲对的部分会变蓝",
            f"敲满自动判定：整条变绿＝对，变红＝错并给出正确拼写；{k('Backspace')} 可以回删",
            f"判定后 1.4 秒自动跳到下一个词；中途不想背了按 {k('Esc')}",
        ])
        + img("word-spell", "默写中：上行中文释义，下行逐字母下划线。")
        + note("对错都会记进学习档案：答错的词记成「待巩固」，之后在设置里点「跳到未掌握」会优先带你去这些词。")
        + h("换词库")
        + table([
            ("四级词汇", f"{len(CET4_WORDS)} 词，按字母序排列"),
            ("六级词汇", f"{len(CET6_WORDS)} 词，按字母序排列"),
            ("考研英语", f"{len(KAOYAN_WORDS)} 词，按字母序排列"),
        ])
        + note("三套词库的学习进度分别保存，切换不会互相覆盖。")
    )

    novel = (
        h("导入小说")
        + ol([
            "右键 → 设置中心 → 摸鱼阅读 → 书架",
            f"内置一本短篇《{BUILTIN_NOVEL_TITLE}》，选中后点「读这本」直接看，不用导入",
            "点「导入 txt」，可以一次选多个文件；单个文件 8MB 以内（约 400 万字）",
            "书架里双击书名、点「读这本」，都会自动切到第三页开始读",
            "「打开所在目录」能直接跳到 txt 文件所在的文件夹",
        ])
        + h("换书")
        + p("阅读面板分成四页：书架、章节目录、跳转进度、手感与伪装。换书有三种走法，"
            "不用每次都回到列表里挑。")
        + ol([
            "书架上的「← 上一本 / 下一本 →」：按书架顺序循环换，不动当前页",
            "在书架列表里双击书名，或选中后点「读这本」：切换并跳到第三页",
            f"小条上按 {k('Ctrl+←')} / {k('Ctrl+→')}：换上一本 / 下一本",
        ])
        + note("每本书的阅读位置和章节各自保存，切来切去不会串；书架行右侧是各自的进度。")
        + h("章节目录")
        + ol([
            "导入时自动识别独立成行的「第X章 / 第X回 / 卷X / Chapter X」这类标题",
            "没写章节标题的 txt，会按每 3000 字自动分节，一样能一节节跳",
            "章节目录页可以搜标题、双击跳到那一节，也能点「上一节 / 下一节」",
            f"小条上按 {k('[')} / {k(']')} 直接跳上/下一节；托盘提示里能看到当前节名",
        ])
        + h("跳转进度")
        + ol([
            "跳转进度页拖滑块，松手就保存；下面还有回到开头 / ±10% / 跳到末尾四个按钮",
            f"小条上 {k('Home')} 回开头、{k('End')} 到末尾、{k('PgUp')} / {k('PgDn')} 翻一屏",
        ])
        + h("怎么读")
        + p("把它拖到第三页，正文就在条里慢慢往上爬。鼠标停在条上才滚，一移开立刻停 —— "
            "有人走过来时手一挪，看着就是一条普通的桌面小工具。")
        + img("novel", "第三页：两行正文，底部细线是全书进度。")
        + ol([
            "轻点小条：暂停 / 继续滚动，同时让小条取得键盘焦点（快捷键才接得到）",
            f"按 {k('空格')}：暂停 / 继续；滚轮停在条上：手动往下翻一点",
            "底部细线：整本书读到哪了；右边圆环的绿色段：当前在第几页",
        ])
        + note("阅读位置按字序保存，换字号、重启、切到别的书再切回来，都能接着上次的地方读。"
               "字号 8～11px（小条高度固定，这个区间才能完整显示两行）、速度 4～80px/秒，在「手感与伪装」里调。")
    )

    muyu = (
        h("敲一下，积一分功德")
        + p("第四页是个电子木鱼。小条左边一只单线简笔木鱼，右边是累计功德。"
            "敲一下木鱼轻轻左右一颤，旁边飘出一句吉利话，计数 +1。"
            "没有联网、没有账号、没有排行榜，纯本地存一个数。")
        + img("muyu", "第四页：左边简笔木鱼，右边累计数；敲下去木鱼微颤、飘出文案。")
        + h("怎么敲")
        + ol([
            "把它拖到第四页，轻点小条让它得到键盘焦点",
            f"按 {k('空格')}：敲一下；按住不放会自动连击",
            "鼠标按住小条超过 250ms：开始连击，每 160ms 一下；轻点不算敲",
            "想停就松手；切到别的页时连击自动停",
        ])
        + note("飘出来的文案从「功德+1 / 财富+1 / 好运+1 / 开心+1 / 摸鱼+1」里随机取，"
               "最多同时飘 4 条，半秒左右淡出，颜色都很淡，不会晃眼。")
        + h("功德数")
        + p("只显示一个累计值，跨天、重启、换主题都不清零。"
            "设置中心 → 电子木鱼里能看到当前数字，也可以清零（会先问一句）。")
        + note("数字只存在本机注册表里，卸载软件不会自动删除，重装回来还在。")
    )

    weather = (
        h("鼠标一移开，它就变成天气")
        + p("停在第三页时，鼠标离开小条，这一页会自动换成当地天气：城市、天气现象、当前气温，"
            "第二行是高低温与湿度。鼠标一移回来，立刻变回正文。")
        + img("weather", "天气态：左城市 + 天气现象，右边气温，第二行高低温与湿度。")
        + h("怎么配")
        + ol([
            "城市留空：按 IP 自动定位（公司网络定位到机房所在城市也算正常）",
            "想固定城市：设置中心 → 摸鱼阅读 → 城市里填「济南」→ 点「立即刷新」",
            "不想要这个效果：取消勾选「鼠标不在条上时，小说页显示当地天气」",
        ])
        + note("取数先走 open-meteo，失败自动换 wttr.in；两个都连不上就显示「天气暂无数据」，"
               "并继续沿用上一次取到的结果。正常情况下每 30 分钟刷新一次。")
    )

    remind = (
        h("三类提醒，按你设的间隔弹")
        + table([
            ("喝水", "默认每 60 分钟，默认开启"),
            ("活动", "默认每 120 分钟，默认开启"),
            ("护眼", "默认每 45 分钟，默认关闭"),
        ])
        + h("怎么改")
        + ol([
            "设置中心 → 健康提醒",
            "每行都能单独改「间隔」（1～720 分钟）、标题、内容；勾上「启用」才生效",
            "下面的「提醒时段」设上班和下班时间，勾「仅工作日」就只在周一到周五提醒",
            "点「发送测试通知」可以立刻验一次通不通",
        ])
        + note("通知走 Windows 系统通知中心。点一下通知会把这条延后 10 分钟。"
               "收不到就去 系统设置 → 系统 → 通知 里确认「Niumer」没被拦，也没开专注助手。")
    )

    settings = (
        h("六个面板")
        + p("右键小条 → 设置中心。左边六张卡选功能，右边改参数，底部两个按钮。")
        + img("settings", "设置中心：左侧选功能，右侧改参数，右下角「保存并关闭」。", 700)
        + table([
            ("工资条", "月薪、上下班时间、每月工作日、暂停/继续、显示累计或每秒、重置累计"),
            ("单词卡", "换词库（四级/六级/考研）、看进度、续背/跳到未掌握/重置"),
            ("健康提醒", "三类提醒的开关、间隔、文案，以及提醒时段"),
            ("摸鱼阅读", "书架与换书、章节目录、进度滑块、字号/速度、天气伪装（四页）"),
            ("电子木鱼", "累计功德、清零、敲击方式说明"),
            ("外观", "深色 / 浅色主题，切换后立即生效"),
        ])
        + note("改完一定要点右下角「保存并关闭」。直接点窗口右上角的 × 关闭不会保存。")
        + note("设置中心左下角还有「使用帮助」，随时能翻到这里。")
    )

    keypage = (
        h("鼠标")
        + table([
            (k("左键拖动"), "切换四页，松手自动吸附到最近一页"),
            (k("左键轻点"), "单词页：取得键盘焦点；小说页：暂停 / 继续并取焦点；木鱼页：取焦点，不敲"),
            (k("鼠标长按"), "木鱼页：按住 250ms 后连击，每 160ms 一下"),
            (k("右键"), "弹出菜单：切换页面、设置中心、使用帮助、隐藏 / 显示、退出"),
            (k("滚轮"), "小说页：手动滚动正文"),
        ])
        + h("键盘")
        + table([
            (k("空格"), "单词页：开始默写；小说页：暂停 / 继续；木鱼页：敲一下，按住连击"),
            (k("Home / End"), "小说页：回到开头 / 跳到末尾"),
            (k("PgUp / PgDn"), "小说页：向上 / 向下翻一屏"),
            (k("[ / ]"), "小说页：上一节 / 下一节"),
            (k("Ctrl+← / →"), "小说页：换上一本 / 下一本"),
            (k("Backspace"), "默写时删掉一个字母"),
            (k("Esc"), "退出默写"),
            (k("Ctrl+Q"), "全局热键：隐藏 / 显示小条"),
        ])
        + note("Ctrl+Q 如果被别的软件占了同一个热键，会静默失效；"
               "用右键菜单里的「隐藏窗口 / 显示窗口」一样管用。")
        + h("托盘图标")
        + p("右键托盘图标同样是那个菜单；左键点一下，隐藏的小条会重新出现。"
            "鼠标悬停在图标上能看到当前状态：累计金额、单词进度，"
            "读到小说时会显示书名、百分比和当前节名，以及下次提醒还有多久。")
    )

    data = (
        h("配置存在哪")
        + p("全部配置都在注册表里：")
        + p(k("HKEY_CURRENT_USER\\Software\\Niumer\\Niumer"))
        + p("月薪、词库进度、书架与阅读位置、提醒设置、天气城市，都存在这一个键下面。")
        + h("备份与换电脑")
        + ol([
            "Win+R 输入 regedit 回车，定位到上面那个键",
            "右键 → 导出，存成 .reg 文件",
            "新电脑上先运行一次程序，再双击那个 .reg 导入，重启程序即可",
        ])
        + note("想恢复出厂：退出程序后删掉这个键，下次启动就是全新状态（词库进度、书架都会清空）。")
        + h("程序文件")
        + table([
            ("Niumer.exe", "单文件，双击即用，不需要装 Python 或 Qt"),
            ("main.py", "全部源码，改完用 build.bat 重新打包"),
            ("换机说明.txt", "换电脑、重新打包的步骤"),
        ])
    )

    faq = (
        h("小条突然不见了？")
        + p("先按 Ctrl+Q 试试。还不行就看任务管理器里有没有「Niumer」进程 —— "
            "没有就是退出了，重新双击 exe。")
        + h("点一下任务栏，小条就没影了？")
        + p("小条贴在任务栏上，而任务栏被点击时会把自己顶到最前面，把小条整块盖住，看起来就像消失了。"
            "程序每 200ms 检查一次，被任务栏盖住就自动顶回来，最多闪一下。"
            "万一没回来，Ctrl+Q 连按两次即可。")
        + h("双击图标提示「已经在运行了」？")
        + p("程序只允许开一个。多开会画出两条重叠的小条、提醒重复弹、还会抢同一份阅读进度，"
            "所以第二个直接拦下了。看任务栏右下角那条就行。")
        + h("Ctrl+Q 按了没反应？")
        + p("可能被别的软件占了同一个热键，或者程序没在跑。用右键菜单里的「隐藏窗口 / 显示窗口」一样管用。")
        + h("到点了不弹通知？")
        + p("Windows 设置 → 系统 → 通知，确认「Niumer」是开着的，并且没开专注助手 / 免打扰。"
            "设置里点「发送测试通知」能快速验证。")
        + h("小说不滚？")
        + p("按顺序查三件事：鼠标是不是停在条上（移开就停是故意的）、是不是轻点过暂停、"
            "是不是已经读到末尾了。")
        + h("单词页敲字母没反应？")
        + p("窗口要先拿到键盘焦点：左键轻点一下小条，再按空格。")
        + h("小条位置跑了？")
        + p("任务栏换了位置、改了缩放、或插拔显示器之后，重启一次程序，它会重新贴到托盘左边。")
        + h("小说页怎么变成天气了？")
        + p("鼠标不在条上时就是这么显示（伪装）。鼠标移回条上立刻恢复正文；"
            "不想要这个效果，在设置里取消「鼠标不在条上时，小说页显示当地天气」。")
        + h("天气一直显示「暂无数据」？")
        + p("多半是网络挡了外网或代理不通。可以换热点试一次，或在设置里手填城市名再点「立即刷新」。"
            "断网时会继续用上一次取到的天气。")
        + h("支持什么系统？占多少资源？")
        + p("Windows 10（1809 及以上）和 Windows 11，64 位；不支持 Win7/8、32 位、ARM 版。"
            "exe 约 27MB，常驻内存六七十兆；平时每秒刷一次数字，小说滚动时才跑 33ms 一帧。")
    )

    about = (
        h("版本")
        + p(f"Niumer {VERSION}　by {AUTHOR}")
        + h("联系我")
        + p(f"邮箱：{CONTACT_EMAIL}")
        + p("用着有问题、想加功能，或者只是想吐槽，都可以发邮件给我，看到就会回。")
        + h("关于词库")
        + p("四级 / 六级 / 考研三套词表来自 qwerty-learner 开源词库，"
            "已过滤短语、统一音标格式并按字母序排列。")
        + h("关于数据")
        + p("设置、单词进度、书架都只存在本机，不联网上传（天气查询除外）。")
    )

    pages = (
        ("30 秒上手", quick),
        ("工资条", salary),
        ("单词卡", word),
        ("摸鱼阅读", novel),
        ("电子木鱼", muyu),
        ("天气伪装", weather),
        ("健康提醒", remind),
        ("设置中心", settings),
        ("快捷键与手势", keypage),
        ("数据与迁移", data),
        ("常见问题", faq),
        ("关于与联系", about),
    )
    return [
        (title, f"<html><body style='font-size:13px; color:{text};'>{body}</body></html>")
        for title, body in pages
    ]


class _HelpBrowser(QTextBrowser):
    """帮助正文。图不存文件，按名字从内存里取（打开帮助时实时渲染的界面截图）。"""

    def __init__(self, images, parent=None):
        super().__init__(parent)
        self.images = images or {}

    def loadResource(self, type_, url):
        try:
            if int(type_) == int(QTextDocument.ResourceType.ImageResource.value):
                name = url.toString().rsplit("/", 1)[-1].rsplit(".", 1)[0]
                image = self.images.get(name)
                if image is not None and not image.isNull():
                    return image
        except Exception:
            pass
        return super().loadResource(type_, url)


class HelpDialog(QDialog):
    """使用帮助：左侧目录导航 + 右侧文档浏览器风格正文。"""

    def __init__(self, bar=None, parent=None):
        super().__init__(parent)
        p = ui_palette()
        self.setWindowTitle("Niumer · 使用帮助")
        self.setMinimumSize(860, 620)
        avail = QApplication.primaryScreen().availableGeometry()
        self.resize(min(960, avail.width() - 80), min(860, avail.height() - 60))

        browser_css = f"""
            QTextBrowser {{
                background:{p['card']}; border:1px solid {p['border']};
                border-radius:12px; color:{p['text']}; padding:20px 24px;
            }}
            QTextBrowser h1 {{ font-size:20px; font-weight:700; color:{p['text']}; margin:0 0 12px 0; }}
            QTextBrowser h2 {{ font-size:15px; font-weight:600; color:{p['text']}; margin:20px 0 8px 0; }}
            QTextBrowser h3 {{ font-size:13px; font-weight:600; color:{p['sub']}; margin:16px 0 6px 0; }}
            QTextBrowser p {{ margin:4px 0; line-height:1.7; color:{p['text']}; font-size:13px; }}
            QTextBrowser ul {{ margin:6px 0; padding-left:20px; }}
            QTextBrowser li {{ margin:3px 0; font-size:13px; color:{p['text']}; }}
            QTextBrowser code {{ background:{p['accent_soft']}; color:{p['accent']};
                padding:1px 6px; border-radius:4px; font-family:'Consolas'; font-size:12px; }}
            QTextBrowser img {{ max-width:100%; border-radius:8px; margin:8px 0; }}
            QTextBrowser strong {{ color:{p['text']}; font-weight:600; }}
        """
        nav_css = f"""
            QListWidget {{ background:{p['card']}; border:1px solid {p['border']};
                border-radius:12px; outline:none; padding:6px; font-size:13px; }}
            QListWidget::item {{ padding:10px 14px; border-radius:8px; margin:2px 0; color:{p['text']}; }}
            QListWidget::item:hover {{ background:{p['hover']}; }}
            QListWidget::item:selected {{ background:{p['accent_soft']}; color:{p['accent']}; font-weight:600; }}
        """
        apply_dialog_theme(self, nav_css + browser_css)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        # 顶部标题
        head = QHBoxLayout()
        head.setSpacing(12)
        head_title = QLabel("使用帮助")
        head_title.setStyleSheet("font-size:18px; font-weight:700;")
        head_sub = QLabel("左侧选章节 · 右侧看图文说明")
        head_sub.setObjectName("Subtitle")
        head.addWidget(head_title)
        head.addWidget(head_sub)
        head.addStretch(1)
        ver = QLabel(f"v{VERSION} · by {AUTHOR}")
        ver.setObjectName("Hint")
        head.addWidget(ver)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(16)

        # 左侧目录
        self.nav = QListWidget()
        self.nav.setFixedWidth(156)
        self.nav.setCursor(Qt.CursorShape.PointingHandCursor)
        self.images = self.build_images(bar)

        # 右侧正文
        self.browser = _HelpBrowser(self.images)
        self.browser.setOpenExternalLinks(False)
        self.browser.document().setDocumentMargin(0)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(13)
        self.browser.setFont(font)

        body.addWidget(self.nav, 0)
        body.addWidget(self.browser, 1)
        outer.addLayout(body, 1)

        # 底部
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 6, 0, 0)
        tip = QLabel("想改参数 → 右键小条 → 「设置中心」")
        tip.setObjectName("Hint")
        footer.addWidget(tip)
        footer.addStretch(1)
        ok = QPushButton("知道了")
        ok.setObjectName("Primary")
        ok.setMinimumHeight(38)
        ok.setMinimumWidth(112)
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self.accept)
        footer.addWidget(ok)
        outer.addLayout(footer)

        self.pages = help_pages()
        for title, _ in self.pages:
            self.nav.addItem(title)
        self.nav.currentRowChanged.connect(self.show_page)
        self.nav.setCurrentRow(0)

    @staticmethod
    def build_images(bar):
        """一次性渲染帮助里要用的图；任何一张失败都不影响文字部分。"""
        images = {}
        if bar is None:
            return images
        try:
            images["taskbar"] = render_taskbar_scene(bar)
        except Exception:
            pass
        for name, kwargs in (
            ("salary", dict(page=PAGE_SALARY)),
            ("word", dict(page=PAGE_WORD)),
            ("novel", dict(page=PAGE_NOVEL)),
            ("muyu", dict(page=PAGE_MUYU)),
        ):
            try:
                images[name] = render_bar_image(bar, **kwargs)
            except Exception:
                pass
        try:
            word = (bar.deck.current()[0] or "")[:2]
            images["word-spell"] = render_bar_image(
                bar, PAGE_WORD, spelling=True, typed=word
            )
        except Exception:
            pass
        try:
            data = bar.weather_data or demo_weather()
            images["weather"] = render_bar_image(
                bar, PAGE_NOVEL, weather=True, weather_data=data
            )
        except Exception:
            pass
        shot = render_settings_image(bar)
        if shot is not None and not shot.isNull():
            images["settings"] = shot
        return images

    def show_page(self, row):
        if 0 <= row < len(self.pages):
            self.browser.setHtml(self.pages[row][1])
            self.browser.verticalScrollBar().setValue(0)


class NavIcon(QWidget):
    """设置中心左侧的单线简笔图标，QPainter 手绘，不依赖图片或字体。"""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.checked = False
        self.setFixedSize(28, 28)

    def set_checked(self, on):
        if self.checked != on:
            self.checked = on
            self.update()

    def paintEvent(self, event):
        p = ui_palette()
        # 背景自己画：QSS 的 QLabel#NavBadgeChecked 对自定义 QWidget 不生效，
        # 白线画在浅灰底上会看不清。这里选中态画实底、线条转白，保证对比度。
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bg = QColor(p["accent"]) if self.checked else QColor(p["accent_soft"])
        color = QColor("#ffffff") if self.checked else QColor(p["accent"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)

        pen = QPen(color, 1.4, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = w / 2.0, h / 2.0

        if self.kind == "salary":
            # 硬币：外圆 + 内圆 + 一枚小钱字符（用两横一竖抽象表示）
            painter.drawEllipse(QPointF(cx, cy), 9, 9)
            painter.drawEllipse(QPointF(cx, cy), 6.2, 6.2)
            painter.drawLine(QPointF(cx, cy - 3.5), QPointF(cx, cy + 3.5))
            painter.drawLine(QPointF(cx - 2.6, cy - 1.6), QPointF(cx + 2.6, cy - 1.6))
            painter.drawLine(QPointF(cx - 2.6, cy + 1.4), QPointF(cx + 2.6, cy + 1.4))
        elif self.kind == "words":
            # 单词卡：一张卷角卡片 + 三行字线
            card = QPainterPath()
            card.moveTo(cx - 8, cy - 9)
            card.lineTo(cx + 5, cy - 9)
            card.lineTo(cx + 8, cy - 6)
            card.lineTo(cx + 8, cy + 9)
            card.lineTo(cx - 8, cy + 9)
            card.closeSubpath()
            painter.drawPath(card)
            painter.drawLine(QPointF(cx + 5, cy - 9), QPointF(cx + 5, cy - 6))
            painter.drawLine(QPointF(cx + 5, cy - 6), QPointF(cx + 8, cy - 6))
            for dy in (-2, 2, 6):
                painter.drawLine(QPointF(cx - 5, cy + dy), QPointF(cx + 4, cy + dy))
        elif self.kind == "remind":
            # 铃铛：钟体 + 钟舌 + 顶部小柄
            body = QPainterPath()
            body.moveTo(cx - 7, cy + 5)
            body.quadTo(cx - 6, cy - 7, cx, cy - 7)
            body.quadTo(cx + 6, cy - 7, cx + 7, cy + 5)
            body.closeSubpath()
            painter.drawPath(body)
            painter.drawLine(QPointF(cx - 9, cy + 5), QPointF(cx + 9, cy + 5))
            painter.drawEllipse(QPointF(cx, cy + 8), 1.3, 1.3)
            painter.drawLine(QPointF(cx, cy - 7), QPointF(cx, cy - 9.5))
        elif self.kind == "novel":
            # 翻开的书：中缝 + 两侧书页弧线
            book = QPainterPath()
            book.moveTo(cx, cy - 6)
            book.quadTo(cx - 5, cy - 9, cx - 10, cy - 7)
            book.lineTo(cx - 10, cy + 6)
            book.quadTo(cx - 5, cy + 4, cx, cy + 7)
            book.quadTo(cx + 5, cy + 4, cx + 10, cy + 6)
            book.lineTo(cx + 10, cy - 7)
            book.quadTo(cx + 5, cy - 9, cx, cy - 6)
            painter.drawPath(book)
            painter.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy + 7))
        elif self.kind == "muyu":
            # 木鱼：椭圆轮廓 + 开口缝 + 小木槌（与第四页一致）
            painter.drawEllipse(QRectF(cx - 9, cy - 6, 18, 12))
            slit = QPainterPath()
            slit.moveTo(cx - 6, cy - 1)
            slit.quadTo(cx - 1, cy + 3, cx + 4, cy - 2)
            painter.drawPath(slit)
            painter.drawLine(QPointF(cx + 8, cy - 9), QPointF(cx + 3, cy - 3))
            painter.drawEllipse(QPointF(cx + 8, cy - 9), 1.8, 1.8)
        elif self.kind == "appearance":
            # 日月：左半边月牙（空心）+ 右半边太阳带光芒，一眼看懂深浅主题
            moon = QPainterPath()
            moon.moveTo(cx + 0.5, cy - 8)
            moon.arcTo(QRectF(cx - 8, cy - 8, 16, 16), 90, 180)
            moon.quadTo(cx + 4, cy, cx + 0.5, cy - 8)
            painter.drawPath(moon)
            painter.drawEllipse(QPointF(cx + 4, cy), 3.2, 3.2)
            for a in (0, 60, 120, 180, 240, 300):
                rad = math.radians(a)
                x1 = cx + 4 + math.cos(rad) * 5.2
                y1 = cy + math.sin(rad) * 5.2
                x2 = cx + 4 + math.cos(rad) * 7.0
                y2 = cy + math.sin(rad) * 7.0
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.end()


class SettingsCenter(QDialog):
    """统一设置中心：左侧图标导航，右侧配置面板。

    风格参考 Linear / Raycast：左侧导航紧凑、选中态用浅底+细竖线指示；
    右侧面板是一个大卡片，里面分组。
    """

    CARDS = (
        ("salary", "salary", "工资条", "月薪、作息与每秒进账"),
        ("words", "words", "单词卡", "词库与默写"),
        ("remind", "remind", "健康提醒", "喝水 · 活动 · 护眼"),
        ("novel", "novel", "摸鱼阅读", "TXT 自动滚"),
        ("muyu", "muyu", "电子木鱼", "敲一敲 · 攒功德"),
        ("appearance", "appearance", "外观", "主题 · 深浅色"),
    )

    def __init__(self, bar, parent=None):
        super().__init__(parent)
        p = ui_palette()
        self.setWindowTitle("Niumer · 设置中心")
        self.setMinimumSize(860, 640)
        avail = QApplication.primaryScreen().availableGeometry()
        self.resize(min(960, avail.width() - 80), min(880, avail.height() - 60))
        apply_dialog_theme(self, f"""
            /* dialog_style() 已覆盖 QFrame#Nav / QPushButton#NavCard 的 color/background/border，
               这里只设 Nav 专用的尺寸/圆角和 NavTitle/NavSub/NavBadge 这些独有的 objectName */
            QFrame#Nav {{ border-radius:12px; }}
            QPushButton#NavCard {{ border-radius:8px; padding:8px 10px; }}
            QLabel#NavTitle {{ font-size:13px; font-weight:600; color:{p['text']}; background:transparent; }}
            QLabel#NavSub {{ font-size:11px; color:{p['sub']}; background:transparent; }}
            /* NavBadge 是自定义 QWidget，背景和线条由 NavIcon.paintEvent 自己画 */
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        # 顶部
        head = QHBoxLayout()
        head.setSpacing(12)
        head_title = QLabel("设置中心")
        head_title.setStyleSheet("font-size:18px; font-weight:700;")
        head_sub = QLabel("改完点右下角保存立即生效")
        head_sub.setObjectName("Subtitle")
        head.addWidget(head_title)
        head.addWidget(head_sub)
        head.addStretch(1)
        ver = QLabel(f"v{VERSION} · by {AUTHOR}")
        ver.setObjectName("Hint")
        head.addWidget(ver)
        outer.addLayout(head)

        # 主体：左导航 + 右面板
        main = QHBoxLayout()
        main.setSpacing(16)

        nav = QFrame()
        nav.setObjectName("Nav")
        nav.setFixedWidth(192)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(8, 10, 8, 10)
        nl.setSpacing(4)
        self.nav_group = []
        self.nav_badges = {}
        for key, icon_kind, title_text, sub in self.CARDS:
            btn = QPushButton()
            btn.setObjectName("NavCard")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            bl = QHBoxLayout(btn)
            bl.setContentsMargins(8, 4, 8, 4)
            bl.setSpacing(10)
            badge = NavIcon(icon_kind)
            badge.setObjectName("NavBadge")
            texts = QVBoxLayout()
            texts.setSpacing(1)
            t = QLabel(title_text)
            t.setObjectName("NavTitle")
            s = QLabel(sub)
            s.setObjectName("NavSub")
            texts.addWidget(t)
            texts.addWidget(s)
            bl.addWidget(badge)
            bl.addLayout(texts, 1)
            btn.clicked.connect(lambda _, k=key: self.show_panel(k))
            nl.addWidget(btn)
            self.nav_group.append((key, btn))
            self.nav_badges[key] = badge
        nl.addStretch(1)
        main.addWidget(nav, 0)

        self.stack = QStackedWidget()
        self.panels = {
            "salary": SalaryPanel(bar),
            "words": WordsPanel(bar),
            "remind": ReminderPanel(bar),
            "novel": NovelPanel(bar),
            "muyu": MuyuPanel(bar),
            "appearance": AppearancePanel(bar),
        }
        for key, panel in self.panels.items():
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setWidget(panel)
            self.stack.addWidget(area)
        main.addWidget(self.stack, 1)

        # 底部按钮
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 6, 0, 0)
        help_btn = QPushButton("使用帮助")
        help_btn.setObjectName("Ghost")
        help_btn.setMinimumHeight(38)
        help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        help_btn.clicked.connect(lambda: HelpDialog(bar, self).exec())
        done = QPushButton("保存并关闭")
        done.setObjectName("Primary")
        done.setMinimumHeight(38)
        done.setMinimumWidth(128)
        done.setCursor(Qt.CursorShape.PointingHandCursor)
        done.clicked.connect(self.accept)
        footer.addWidget(help_btn)
        footer.addStretch(1)
        footer.addWidget(done)
        outer.addLayout(main, 1)
        outer.addLayout(footer)

        self.show_panel("salary")

    def show_panel(self, key):
        for k, btn in self.nav_group:
            btn.setChecked(k == key)
        # 选中态：背景和线条颜色由 NavIcon 自己画（QSS 对自定义 QWidget 不生效）
        for k, badge in self.nav_badges.items():
            badge.set_checked(k == key)
        idx = list(self.panels.keys()).index(key)
        self.stack.setCurrentIndex(idx)

    def accept(self):
        for panel in self.panels.values():
            if panel.apply() is False:
                return
        super().accept()


class SalaryBar(QWidget):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = QSettings("Niumer", "Niumer")
        self.monthly = float(self.settings.value("monthly_salary", 3000.0))
        # 上下班时间、每月工作日都可配；金额按「今天已经过去的上班时间」折算，
        # 不是从打开软件那一刻起从 0 累加 —— 中午才开机也不会少算。
        self.work_start = clock_time(self.settings.value("work_start"), DEFAULT_WORK_START)
        self.work_end = clock_time(self.settings.value("work_end"), DEFAULT_WORK_END)
        if self.work_start.secsTo(self.work_end) <= 0:
            # 存档里是「下班早于上班」这类坏数据：退回默认作息，否则金额会一直停在 0
            self.work_start = clock_time(DEFAULT_WORK_START, DEFAULT_WORK_START)
            self.work_end = clock_time(DEFAULT_WORK_END, DEFAULT_WORK_END)
            self.settings.setValue("work_start", DEFAULT_WORK_START)
            self.settings.setValue("work_end", DEFAULT_WORK_END)
        try:
            self.work_days = int(self.settings.value("work_days", DEFAULT_WORK_DAYS)
                                 or DEFAULT_WORK_DAYS)
        except (TypeError, ValueError):
            self.work_days = DEFAULT_WORK_DAYS
        self.work_days = max(1, min(31, self.work_days))
        self.show_total = True
        self.paused = False
        self.paused_value = 0.0
        self.reset_day = None      # 重置累计金额的那一天
        self.reset_value = 0.0     # 重置那一刻今天已经赚到的钱
        self.phase = 0.0
        self.shown_earned = self.earned
        self.shown_rate = self.rate

        self.deck = WordDeck(self.settings)
        self.shelf = NovelShelf(self.settings)
        self.novel = NovelView(self.settings, self.shelf)
        self.novel_paused = False

        # 电子木鱼：只存累计值；长按 250ms 起连击，每 160ms 一下
        self.muyu = MuyuCounter(self.settings)
        self.muyu_hold_timer = QTimer(self)
        self.muyu_hold_timer.setSingleShot(True)
        self.muyu_hold_timer.timeout.connect(self.start_muyu_repeat)
        self.muyu_repeat_timer = QTimer(self)
        self.muyu_repeat_timer.timeout.connect(self.muyu_hit_once)
        self.muyu_repeating = False
        self.hover_inside = False
        self.novel_save_at = 0.0

        # 天气伪装：鼠标不在条上时，小说页改显示当地天气
        self.weather = WeatherService(self.settings, self)
        self.weather.ready.connect(self.on_weather_ready)
        self.weather.failed.connect(self.on_weather_failed)
        self.weather_data = self.weather.cached()
        self.weather_busy = False
        self.weather_error = ""
        self.weather_on = bool(int(self.settings.value("weather_on", 1)))
        self.weather_city = str(self.settings.value("weather_city", "") or "")
        self.weather_interval = int(
            self.settings.value("weather_interval_min", WEATHER_DEFAULT_INTERVAL)
            or WEATHER_DEFAULT_INTERVAL
        )
        self.weather_tried_at = 0.0

        self.page = PAGE_SALARY
        self.view = float(PAGE_SALARY)
        self.drag_x = 0.0
        self.drag_page = PAGE_SALARY
        self.drag_distance = 0.0
        self.dragging = False

        # 默写状态：空格开始，逐字填入，输满判定
        self.spelling = False
        self.spell_input = ""
        self.spell_result = None  # None 输入中 / True 正确 / False 错误
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self.finish_feedback)

        self.view_anim = QVariantAnimation(self)
        self.view_anim.setDuration(260)
        self.view_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.view_anim.valueChanged.connect(self.on_view_changed)
        self.view_anim.finished.connect(self.on_view_finished)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(186, 32)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.tray = QSystemTrayIcon(make_tray_icon(), self)
        self.reminders = ReminderManager(self.settings, self.tray)
        self.tray.messageClicked.connect(self.on_message_clicked)
        self.menu = self.build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.hotkey_filter = HotkeyFilter(self.toggle_visibility)
        self.app.installNativeEventFilter(self.hotkey_filter)
        self.hotkey_registered = bool(
            user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL, VK_Q)
        )
        self.app.aboutToQuit.connect(self.cleanup)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.animate)
        self.anim_timer.start(100)

        # 木鱼浮字/微震专用动画：33ms 一帧（30fps），只在有动画时跑，
        # 100ms 的主动画帧率对 350~600ms 的浮字太粗，看着一顿一顿。
        self.muyu_anim_timer = QTimer(self)
        self.muyu_anim_timer.timeout.connect(self.animate_muyu)
        self.muyu_anim_timer.setInterval(33)

        # 健康提醒：每秒检查是否到点
        self.remind_timer = QTimer(self)
        self.remind_timer.timeout.connect(self.check_reminders)
        self.remind_timer.start(1000)

        # 小说滚动：33ms 一帧，只有鼠标停在小条上、且停在小说页时才走
        self.novel_timer = QTimer(self)
        self.novel_timer.timeout.connect(self.novel_tick)
        self.novel_timer.start(33)

        # 鼠标是否停在条上：定时轮询比 enter/leave 可靠（拖动、切页都不会漏）
        self.hover_timer = QTimer(self)
        self.hover_timer.timeout.connect(self.poll_hover)
        self.hover_timer.start(160)

        # 置顶守护：鼠标单击任务栏时，任务栏会把自己顶到最前面，
        # 把贴在它上面的小条整块盖住（看着就像窗口消失了）。
        # 每 200ms 看一眼，被任务栏盖住就顶回来。
        self.topmost_timer = QTimer(self)
        self.topmost_timer.timeout.connect(self.guard_topmost)
        self.topmost_timer.start(200)

        # 天气：每 30 秒看一眼要不要刷新
        self.weather_timer = QTimer(self)
        self.weather_timer.timeout.connect(self.weather_tick)
        self.weather_timer.start(30000)

        self.locate()
        self.show()
        force_topmost(int(self.winId()))
        self.update_tip()
        self.update_menu()

    def build_menu(self):
        """精简菜单：只留页面切换、设置中心、隐藏、退出。"""
        menu = QMenu()
        title = menu.addAction(f"Niumer v{VERSION} · by {AUTHOR}")
        title.setEnabled(False)
        menu.addSeparator()
        self.page_actions = []
        for i, name in enumerate(PAGE_NAMES):
            self.page_actions.append(menu.addAction(name, lambda i=i: self.goto_page(i)))
        menu.addSeparator()
        menu.addAction("设置中心...", lambda: self.open_settings_center("salary"))
        menu.addAction("使用帮助...", self.open_help)
        self.visibility_action = menu.addAction(
            "隐藏窗口 (Ctrl+Q)" if self.isVisible() else "显示窗口 (Ctrl+Q)",
            self.toggle_visibility,
        )
        menu.addSeparator()
        menu.addAction("退出", self.app.quit)
        menu.setStyleSheet(self.menu_style())
        return menu

    @staticmethod
    def menu_style():
        light = is_light_theme()
        if light:
            return '''
                QMenu { background-color:#FFFFFF; border:1px solid #E5E5E5;
                    border-radius:4px; padding:4px 0; color:#1F1F1F;
                    font-family:'Segoe UI', 'Microsoft YaHei'; font-size:12px; }
                QMenu::item { padding:8px 28px 8px 10px; margin:0; border-radius:2px; }
                QMenu::item:hover { background-color:#F3F3F3; }
                QMenu::item:selected { background-color:#E1EFFD; color:#0078D4; }
                QMenu::item:disabled { color:#A0A0A0; padding:4px 28px 6px 10px; }
                QMenu::separator { height:1px; background-color:#E5E5E5; margin:6px 10px; }
            '''
        return '''
            QMenu { background-color:#2D2D2D; border:1px solid #404040;
                border-radius:4px; padding:4px 0; color:#F5F5F5;
                font-family:'Segoe UI', 'Microsoft YaHei'; font-size:12px; }
            QMenu::item { padding:8px 28px 8px 10px; margin:0; border-radius:2px; }
            QMenu::item:hover { background-color:#353535; }
            QMenu::item:selected { background-color:#1A3A5C; color:#0A84FF; }
            QMenu::item:disabled { color:#7A7A7A; padding:4px 28px 6px 10px; }
            QMenu::separator { height:1px; background-color:#404040; margin:6px 10px; }
        '''

    @property
    def work_seconds_per_day(self) -> int:
        return max(0, self.work_start.secsTo(self.work_end))

    @property
    def rate(self):
        month_seconds = self.work_days * self.work_seconds_per_day
        return self.monthly / month_seconds if month_seconds > 0 else 0.0

    def earned_today(self) -> float:
        """今天从上班时间到现在已经过去的秒数 × 每秒进账。

        直接读系统时钟，所以中午才打开、休眠唤醒、手动改时间都能算对；
        早于上班时间是 0，过了下班时间就封顶为整天。
        """
        now = QTime.currentTime()
        worked = min(max(self.work_start.secsTo(now), 0), self.work_seconds_per_day)
        return worked * self.rate

    @property
    def earned(self):
        if self.paused:
            return self.paused_value
        value = self.earned_today()
        if self.reset_day == datetime.date.today():
            value = max(0.0, value - self.reset_value)
        return value

    def colors(self):
        if is_light_theme():
            # Windows 10 light
            return dict(
                top=QColor(245, 245, 245, 252), bottom=QColor(235, 235, 235, 250),
                border=QColor(229, 229, 229, 215), text=QColor(31, 31, 31),
                sub=QColor(92, 92, 92), faint=QColor(138, 138, 138),
                green=QColor(0, 120, 212), blue=QColor(0, 120, 212),
                purple=QColor(88, 101, 242), glow=QColor(0, 120, 212, 42),
            )
        # Windows 10 dark
        return dict(
            top=QColor(32, 32, 32, 252), bottom=QColor(25, 25, 25, 250),
            border=QColor(64, 64, 64, 220), text=QColor(245, 245, 245),
            sub=QColor(176, 176, 176), faint=QColor(122, 122, 122),
            green=QColor(10, 132, 255), blue=QColor(10, 132, 255),
            purple=QColor(94, 115, 229), glow=QColor(10, 132, 255, 55),
        )

    def tick(self):
        self.shown_earned = self.earned
        self.shown_rate = self.rate
        self.update_tip()
        self.update()

    def animate(self):
        self.phase += 0.13
        # 木鱼敲击后要持续刷到微震和浮字都结束，不能只刷一帧
        if self.page == PAGE_MUYU:
            elapsed = (time.monotonic() - self.muyu.hit_at) * 1000.0 \
                if self.muyu.hit_at else 9999.0
            if elapsed <= MUYU_HIT_ANIM_MS or self.muyu.floats:
                self.update()
        else:
            self.update()

    def update_tip(self):
        """只在托盘图标上挂一行简短悬停提示。

        小条本体不再设 tooltip —— 原来鼠标一停就弹一大块文字挡视线，
        详细说明已移到右键菜单的「使用帮助」里。
        """
        self.setToolTip("")
        due = self.reminders.next_due()
        if self.page == PAGE_SALARY:
            head = f"Niumer ¥{money(self.earned)}（¥{fmt_rate(self.rate)}/秒）"
        elif self.page == PAGE_NOVEL:
            book = self.shelf.current_book()
            if book is None:
                head = "摸鱼阅读 · 未导入"
            else:
                ch = self.novel.chapter_label()
                head = (f"《{book['title']}》 {self.novel.percent():.1f}%"
                        + (f" · {ch}" if ch else ""))
        elif self.page == PAGE_MUYU:
            head = f"电子木鱼 · 累计功德 {self.muyu.total}"
        else:
            head = f"{self.deck.deck_name} {self.deck.index + 1}/{len(self.deck.words)}"
        tail = f" · 下次{due[1]} {fmt_duration(due[0])}" if due else ""
        self.tray.setToolTip(head + tail)

    def guard_topmost(self):
        """任务栏一被点就顶到最前，把小条压下去。这里只负责把它顶回来。

        只针对任务栏：右键菜单、设置窗口、开始菜单等别的窗口压上来都算正常，
        不去抢，免得菜单被小条戳穿。
        """
        if not self.isVisible():
            return
        try:
            hwnd = int(self.winId())
            under = window_under(hwnd)
            if not under or under == hwnd:
                return
            if under != int(user32.FindWindowW("Shell_TrayWnd", None) or 0):
                return
            force_topmost(hwnd)
            self.update()
        except Exception:
            pass

    def locate(self):
        bar, tray = taskbar_geometry()
        screen = QApplication.primaryScreen().geometry()
        if bar:
            left, top, right, bottom = bar
            bar_height = bottom - top
            right_edge = tray[0] - 4 if tray and tray[0] > left + 100 else right - 140
            x = right_edge - self.width()
            y = top + (bar_height - self.height()) // 2
            if not (screen.left() <= x <= screen.right() and screen.top() <= y <= screen.bottom()):
                x = screen.right() - self.width()
                y = screen.bottom() - self.height()
        else:
            x = screen.right() - self.width()
            y = screen.bottom() - self.height()
        self.move(x, y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.colors()
        w, h = self.width(), self.height()

        # 默写判定结果：整条染绿（对）或染红（错）
        if self.spell_result is True:
            top, bottom = QColor(16, 185, 129, 250), QColor(12, 150, 103, 250)
        elif self.spell_result is False:
            top, bottom = QColor(229, 72, 72, 250), QColor(190, 45, 45, 250)
        else:
            top, bottom = c["top"], c["bottom"]

        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 7, 7)
        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0, top)
        gradient.setColorAt(1, bottom)
        painter.fillPath(path, gradient)
        painter.setPen(QPen(c["border"], 1))
        painter.drawPath(path)

        # 判定结果覆盖整条：✓ 正确 / ✗ 错误（附正确答案）
        if self.spell_result is not None:
            word, _, _ = self.deck.current()
            ok = self.spell_result is True
            painter.setPen(QColor(255, 255, 255))
            icon_font = QFont("Microsoft YaHei")
            icon_font.setPixelSize(14)
            icon_font.setBold(True)
            painter.setFont(icon_font)
            painter.drawText(
                QRectF(7, 0, 18, h), Qt.AlignmentFlag.AlignVCenter, "✓" if ok else "✗"
            )
            main_font = QFont("Consolas")
            main_font.setPixelSize(13)
            main_font.setBold(True)
            painter.setFont(main_font)
            painter.drawText(
                QRectF(26, 0, 130, h),
                Qt.AlignmentFlag.AlignVCenter,
                word if ok else f"{word} ✗",
            )
            painter.end()
            return

        painter.save()
        painter.setClipRect(QRectF(1, 1, w - 2, h - 2))
        left = math.floor(self.view)
        frac = self.view - left
        for idx, xoff in ((left, -frac * w), (left + 1, (1 - frac) * w)):
            if not 0 <= idx < PAGE_COUNT:
                continue
            painter.save()
            painter.translate(xoff, 0)
            painter.setOpacity(1.0 - 0.28 * min(1.0, frac))
            if idx == PAGE_SALARY:
                self.draw_salary(painter, c)
            elif idx == PAGE_WORD:
                self.draw_word_page(painter, c)
            elif idx == PAGE_NOVEL:
                if self.weather_shown():
                    self.draw_weather_page(painter, c)
                else:
                    self.draw_novel_page(painter, c)
            elif idx == PAGE_MUYU:
                self.draw_muyu_page(painter, c)
            painter.restore()
        painter.restore()

        self.draw_page_dots(self, painter, c)
        painter.end()

    def draw_salary(self, painter, c):
        h = self.height()
        w = self.width()
        pulse = 0.5 + 0.5 * math.sin(self.phase)
        center = QPointF(11, h / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        if not self.paused:
            painter.setBrush(c["glow"])
            r = 5.5 + 2 * pulse
            painter.drawEllipse(center, r, r)
        dot = QColor(c["green"])
        dot.setAlpha(int(150 + 105 * pulse))
        painter.setBrush(dot)
        painter.drawEllipse(center, 3.2, 3.2)

        # 两种模式各显示一样、不重复：累计模式配每秒速率，速率模式配月薪
        if self.show_total:
            main_text = "¥" + money(self.shown_earned)
            side = f"+{fmt_rate(self.shown_rate)}/s"
        else:
            main_text = f"¥{fmt_rate(self.shown_rate)}/s"
            side = f"月薪{self.monthly:,.0f}"

        side_font = QFont("Microsoft YaHei")
        side_font.setPixelSize(9)
        side_w = QFontMetricsF(side_font).horizontalAdvance(side)
        right = w - DOTS_ZONE
        money_left = 20.0
        money_max = max(30.0, right - side_w - 10 - money_left)

        # 金额随位宽自动降字号，月薪再大也不会压到右边的小字
        font = fit_font(main_text, money_max, (15, 14, 13, 12, 11, 10))
        if QFontMetricsF(font).horizontalAdvance(main_text) > money_max:
            # 位数实在太多：保住金额，把速率让出去，宁可少显示一部分信息
            side = ""
            money_max = right - money_left
            font = fit_font(main_text, money_max, (15, 14, 13, 12, 11, 10))
        painter.setFont(font)
        painter.setPen(c["text"])
        painter.drawText(
            QRectF(money_left, 0, money_max, h),
            Qt.AlignmentFlag.AlignVCenter,
            elide(font, main_text, money_max),
        )

        if side:
            painter.setFont(side_font)
            painter.setPen(c["sub"])
            painter.drawText(
                QRectF(right - side_w, 0, side_w, h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                side,
            )

    def draw_word_page(self, painter, c):
        word, phonetic, meaning = self.deck.current()
        right = self.width() - DOTS_ZONE
        if not self.spelling:
            # 常态：第一行单词（占满宽度，超长自动省略），第二行音标释义 + 右下进度
            font = QFont("Microsoft YaHei")
            font.setPixelSize(13)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(c["text"])
            painter.drawText(
                QRectF(PAD_L, 0, right - PAD_L - 4, 17),
                Qt.AlignmentFlag.AlignVCenter,
                elide(font, word, right - PAD_L - 4),
            )

            # 学习进度：右下角，浅色小字，不跟单词抢位置
            prog_font = QFont("Consolas")
            prog_font.setPixelSize(9)
            prog = f"{self.deck.index + 1}/{len(self.deck.words)}"
            prog_w = QFontMetricsF(prog_font).horizontalAdvance(prog)
            painter.setFont(prog_font)
            painter.setPen(c["faint"])
            painter.drawText(
                QRectF(right - prog_w, 15, prog_w, 17),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                prog,
            )

            small = QFont("Microsoft YaHei")
            small.setPixelSize(11)
            painter.setFont(small)
            painter.setPen(c["sub"])
            avail = max(20.0, right - PAD_L - prog_w - 6)
            text = f"{phonetic} {meaning}".strip()
            if QFontMetricsF(small).horizontalAdvance(text) > avail:
                text = meaning
            painter.drawText(
                QRectF(PAD_L, 15, avail, 17),
                Qt.AlignmentFlag.AlignVCenter,
                elide(small, text, avail),
            )
            return

        # 默写中：上行中文释义提示，下行按字母个数的下划线
        if self.spell_result is not None:
            return  # 判定结果由 paintEvent 整条染色显示

        tip_font = QFont("Microsoft YaHei")
        tip_font.setPixelSize(11)
        painter.setFont(tip_font)
        painter.setPen(c["sub"])
        painter.drawText(
            QRectF(PAD_L, 0, right - PAD_L, 16),
            Qt.AlignmentFlag.AlignVCenter,
            elide(tip_font, meaning, right - PAD_L),
        )

        # 逐字母下划线：每个字母一个短横，能数得出还剩几个字母
        n = max(1, len(word))
        typed = self.spell_input
        slot_w = min(13.0, (right - PAD_L - 4) / n)
        mono = QFont("Consolas")
        if not mono.exactMatch():
            mono = QFont("Courier New")
        mono.setPixelSize(13 if slot_w >= 11 else (11 if slot_w >= 9 else 9))
        mono.setBold(True)
        painter.setFont(mono)
        base_y = 28.0
        for i in range(n):
            x = PAD_L + i * slot_w
            if i < len(typed):
                painter.setPen(c["blue"])
                painter.drawText(
                    QRectF(x, 12, slot_w, 16),
                    Qt.AlignmentFlag.AlignCenter,
                    typed[i],
                )
                painter.setPen(QPen(c["blue"], 1.2))
            else:
                painter.setPen(QPen(c["faint"], 1.2))
            painter.drawLine(QPointF(x + 1.6, base_y), QPointF(x + slot_w - 1.6, base_y))

    def draw_novel_page(self, painter, c):
        """小说页：正文直接在小条里，几行字慢慢往上爬。"""
        h = self.height()
        w = self.width()
        right = w - DOTS_ZONE  # 右侧留给页码指示
        book = self.shelf.current_book()

        if book is None:
            font = QFont("Microsoft YaHei")
            font.setPixelSize(12)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(c["text"])
            painter.drawText(
                QRectF(PAD_L, 1, right - PAD_L, 17),
                Qt.AlignmentFlag.AlignVCenter,
                "还没导入小说",
            )
            small = QFont("Microsoft YaHei")
            small.setPixelSize(10)
            painter.setFont(small)
            painter.setPen(c["sub"])
            painter.drawText(
                QRectF(PAD_L, 16, right - PAD_L, 15),
                Qt.AlignmentFlag.AlignVCenter,
                "轻点这里导入 txt",
            )
            return

        if self.novel.book is None:
            # 还没来得及载入（切页瞬间），给个占位
            small = QFont("Microsoft YaHei")
            small.setPixelSize(11)
            painter.setFont(small)
            painter.setPen(c["sub"])
            painter.drawText(
                QRectF(PAD_L, 0, right - PAD_L, h),
                Qt.AlignmentFlag.AlignVCenter,
                "正在载入…",
            )
            return

        rect = QRectF(PAD_L, 0, right - PAD_L, h - 2)
        self.novel.set_viewport(rect.width(), rect.height())
        self.novel.draw(painter, rect, c["text"])

        # 底部细进度条，不抢文字的地方
        pct = self.novel.percent()
        bar_w = max(20.0, right - PAD_L)
        track = QColor(c["faint"])
        track.setAlpha(70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(PAD_L, h - 2.0, bar_w, 1.5), 0.75, 0.75)
        painter.setBrush(c["green"] if self.novel_running() else c["blue"])
        painter.drawRoundedRect(
            QRectF(PAD_L, h - 2.0, max(1.5, bar_w * pct / 100.0), 1.5), 0.75, 0.75
        )

    def draw_weather_page(self, painter, c):
        """鼠标离开时顶班的小天气条：城市 + 天气 + 气温，第二行高低温与湿度。"""
        right = self.width() - DOTS_ZONE
        data = self.weather_data or {}
        base = QFont("Microsoft YaHei")

        def line1(text, color, size=12, bold=True):
            f = QFont(base)
            f.setPixelSize(size)
            f.setBold(bold)
            painter.setFont(f)
            painter.setPen(color)
            painter.drawText(
                QRectF(PAD_L, 0, right - PAD_L, 17), Qt.AlignmentFlag.AlignVCenter, text
            )

        def line2(text, color):
            f = QFont(base)
            f.setPixelSize(10)
            painter.setFont(f)
            painter.setPen(color)
            painter.drawText(
                QRectF(PAD_L, 15, right - PAD_L, 15), Qt.AlignmentFlag.AlignVCenter, text
            )

        if not data:
            if self.weather_busy:
                line1("天气加载中…", c["text"])
                line2("正在获取当地天气", c["sub"])
            elif self.weather_error:
                line1("天气暂无数据", c["text"])
                line2("稍后自动重试", c["sub"])
            else:
                line1("天气", c["text"])
                line2("等待获取", c["sub"])
            return

        city = str(data.get("city") or "本地")
        desc = str(data.get("desc") or "") or weather_desc(data.get("code", -1))
        temp = f"{int(data.get('temp', 0) or 0)}°"

        # 气温：靠右，大一号
        ft = QFont(base)
        ft.setPixelSize(14)
        ft.setBold(True)
        fm_t = QFontMetricsF(ft)
        tw = fm_t.horizontalAdvance(temp)
        painter.setFont(ft)
        painter.setPen(c["blue"])
        painter.drawText(
            QRectF(right - tw - 1, 0, tw + 1, 17),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            temp,
        )

        # 城市 + 天气现象：靠左，宽度不够就省略
        avail = max(40.0, right - tw - 10 - PAD_L)
        fc = QFont(base)
        fc.setPixelSize(11)
        fc.setBold(True)
        fm_c = QFontMetricsF(fc)
        city_txt = fm_c.elidedText(city, Qt.TextElideMode.ElideRight, max(24.0, avail * 0.6))
        painter.setFont(fc)
        painter.setPen(c["text"])
        painter.drawText(
            QRectF(PAD_L, 0, max(24.0, avail), 17), Qt.AlignmentFlag.AlignVCenter, city_txt
        )
        cw = fm_c.horizontalAdvance(city_txt)

        fd = QFont(base)
        fd.setPixelSize(10)
        fm_d = QFontMetricsF(fd)
        room = max(0.0, avail - cw - 4)
        if room > 14:
            desc_txt = fm_d.elidedText(desc, Qt.TextElideMode.ElideRight, room)
            painter.setFont(fd)
            painter.setPen(c["sub"])
            painter.drawText(
                QRectF(PAD_L + cw + 4, 0, room, 17), Qt.AlignmentFlag.AlignVCenter, desc_txt
            )

        # 第二行：高低温 + 湿度；数据太旧就直说更新时间
        at = float(data.get("at", 0) or 0)
        if at and time.time() - at > WEATHER_STALE_SEC:
            line = time.strftime("%H:%M 更新", time.localtime(at))
        else:
            line = (
                f"{int(data.get('tmax', 0) or 0)}° / {int(data.get('tmin', 0) or 0)}°"
                f"　湿度 {int(data.get('humidity', 0) or 0)}%"
            )
        f2 = QFont(base)
        f2.setPixelSize(10)
        fm2 = QFontMetricsF(f2)
        line = fm2.elidedText(line, Qt.TextElideMode.ElideRight, right - PAD_L)
        painter.setFont(f2)
        painter.setPen(c["sub"])
        painter.drawText(
            QRectF(PAD_L, 15, right - PAD_L, 15), Qt.AlignmentFlag.AlignVCenter, line
        )

    def draw_muyu_page(self, painter, c):
        """电子木鱼：左侧单线简笔木鱼 + 右侧累计数 + 飘动的柔和文案。

        全部用 QPainterPath / drawText 画，不引外部图片。动画由 hit_at 与浮字队列
        的相对时间推出，animate() 每 100ms 刷一次；浮字最多 4 条，向上飘并淡出。
        """
        h = self.height()
        right = self.width() - DOTS_ZONE
        now = time.monotonic()
        elapsed = (now - self.muyu.hit_at) * 1000.0 if self.muyu.hit_at else 9999.0

        ink = c["sub"]          # 柔和深灰，浅色主题下不刺眼
        faint = c["faint"]

        # ---- 左侧：透明底单线简笔木鱼 ----
        cx, cy = 17.0, h / 2.0
        # 左右微震：150ms 内幅度 1.2px 的快速衰减抖动，不缩放
        dx = 0.0
        if elapsed <= MUYU_HIT_ANIM_MS:
            p = elapsed / MUYU_HIT_ANIM_MS
            dx = math.sin(p * math.pi * 6) * 1.2 * (1.0 - p)
        painter.save()
        painter.translate(dx, 0)
        pen = QPen(ink, 1.0, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # 鱼身：一道扁椭圆轮廓
        painter.drawEllipse(QRectF(cx - 8.5, cy - 5.5, 17, 11))
        # 木鱼背上的开口缝：一条上扬的短线
        slit = QPainterPath()
        slit.moveTo(cx - 5.5, cy - 1.5)
        slit.quadTo(cx - 1.0, cy + 2.0, cx + 3.5, cy - 2.0)
        painter.drawPath(slit)
        # 鱼眼
        painter.setBrush(QBrush(ink))
        painter.drawEllipse(QPointF(cx - 4.5, cy - 2.5), 0.8, 0.8)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # 木槌：斜搭在右上，顶端一个小圆头
        painter.setPen(QPen(ink, 1.0, Qt.PenStyle.SolidLine))
        painter.drawLine(QPointF(cx + 10, cy - 8), QPointF(cx + 4, cy - 3))
        painter.drawEllipse(QPointF(cx + 10, cy - 8), 1.8, 1.8)
        painter.restore()

        # ---- 右侧：累计数，敲击时平滑小幅跳动 ----
        text = f"{self.muyu.total:,}"
        font = fit_font(text, 66, range(16, 8, -1), family="Consolas")
        jump = 0.0
        if elapsed <= MUYU_HIT_ANIM_MS:
            p = elapsed / MUYU_HIT_ANIM_MS
            jump = -2.0 * math.sin(p * math.pi)   # 轻轻上抬 2px 再落回
        painter.setFont(font)
        painter.setPen(c["text"])
        painter.drawText(
            QRectF(right - 68, jump, 66, h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text,
        )

        # ---- 浮动文案：从木鱼右侧冒出，向右上飘远并淡出 ----
        floats = self.muyu.live_floats(now)
        if floats:
            painter.save()
            # 允许浮字飘进数字区：两者颜色、字号差异大，短暂叠加能分辨；
            # clip 到内容区右界，飘到边界时正好接近淡出末期，不会显得突兀。
            painter.setClipRect(QRectF(28, 0, right - 28, h))
            ff = QFont("Microsoft YaHei")
            ff.setPixelSize(10)
            ff.setBold(True)
            painter.setFont(ff)
            palette = MUYU_COLORS_LIGHT if is_light_theme() else MUYU_COLORS_DARK
            # 内容区只放得下一条文案宽，多条同屏靠"分层"区分：
            # 每条占一个横向车道，越晚的越靠右；同时按出现顺序错开纵向高度。
            for lane, (word, ci, born, life) in enumerate(floats):
                p = (now - born) / life
                if p >= 1.0:
                    continue
                e = 1.0 - (1.0 - p) ** 2
                # 横向：起点按车道错开，向右飘 52px（之前只有 10px）
                x = 30 + lane * 6 + e * 52
                # 前 65% 接近全不透明，最后 35% 才淡出；
                # 飘进数字区后略降透明度，免得盖住计数
                fade = 1.0 if p <= 0.65 else max(0.0, (1.0 - p) / 0.35)
                if x > right - 68:
                    fade *= 0.78
                color = QColor(palette[ci])
                color.setAlphaF(fade)
                painter.setPen(color)
                # 纵向：每条车道一个基准高度，各自向上飘 12px，互不追尾
                base_y = (h - 2) - lane * 3
                y = base_y - e * 12
                painter.drawText(
                    QRectF(x, y - 12, 60, 12),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, word,
                )
            painter.restore()
        else:
            # 没在飘的时候给一句极淡的提示
            tip = QFont("Microsoft YaHei")
            tip.setPixelSize(9)
            painter.setFont(tip)
            painter.setPen(faint)
            painter.drawText(
                QRectF(30, 0, right - 30 - 68, h),
                Qt.AlignmentFlag.AlignVCenter, "空格敲击",
            )

    @staticmethod
    def draw_page_dots(bar, painter, c):
        """右侧页码指示：一个圆环按页数等分，当前页那段用绿色突出。

        圆环尺寸固定，不随页数变；加页只是多分几段，不会再往左挤占内容区。
        圆心固定在右侧 DOTS_ZONE 内，左缘 ≈165，远离内容右界 152。
        """
        w, h = bar.width(), bar.height()
        current = int(round(bar.view))
        r = 7.0
        cx, cy = w - 12.0, h / 2.0
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)

        active = QColor(46, 139, 87) if is_light_theme() else QColor(102, 194, 153)
        step = 360.0 / PAGE_COUNT
        gap = 16.0                       # 段与段之间留缺口，四段之间看得清
        span = step - gap
        for i in range(PAGE_COUNT):
            pen = QPen(active if i == current else c["faint"], 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # Qt 角度：0° 在 3 点方向、顺时针为正；从 12 点(-90°)开始分段
            start = -90.0 + i * step + gap / 2.0
            painter.drawArc(rect, int(start * 16), int(span * 16))

    # ---- 滑动切页 ----
    def on_view_changed(self, value):
        self.view = float(value)
        self.update()

    def on_view_finished(self):
        self.page = int(round(self.view))
        self.view = float(self.page)
        if self.page != PAGE_WORD and self.spelling:
            self.feedback_timer.stop()
            self.spelling = False
            self.spell_input = ""
            self.spell_result = None
        if self.page != PAGE_MUYU:
            self.stop_muyu_repeat()
        if self.page == PAGE_NOVEL:
            # 滑到小说页才载入正文，避免开机就白读一遍大文件
            self.load_novel_book()
            self.novel_paused = False
            # 顺手把天气备好：鼠标一离开就有得显示
            self.maybe_request_weather()
        self.update_menu()
        self.update_tip()
        self.update()

    def animate_view(self, target):
        target = max(0, min(PAGE_COUNT - 1, int(target)))
        # 切页一开始就停连击，别让动画那 260ms 里还在敲
        self.stop_muyu_repeat()
        self.view_anim.stop()
        self.view_anim.setStartValue(self.view)
        self.view_anim.setEndValue(float(target))
        self.view_anim.start()

    def goto_page(self, index):
        self.animate_view(index)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.view_anim.stop()
            self.dragging = True
            self.drag_x = event.position().x()
            self.drag_page = int(round(self.view))
            self.drag_distance = 0.0
            # 木鱼页：按住一小会儿才开始连击，轻点不算
            if self.page == PAGE_MUYU and int(round(self.view)) == PAGE_MUYU:
                self.setFocus()
                self.muyu_hold_timer.start(MUYU_HOLD_MS)
        elif event.button() == Qt.MouseButton.RightButton:
            self.update_menu()
            self.menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self.dragging:
            dx = event.position().x() - self.drag_x
            self.drag_distance = max(self.drag_distance, abs(dx))
            if self.drag_distance > 3:
                # 一旦开始拖动就取消敲击，别边拖边敲
                self.stop_muyu_repeat()
                target = self.drag_page - dx / self.width()
                self.view = max(0.0, min(float(PAGE_COUNT - 1), target))
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.dragging:
            self.dragging = False
            self.stop_muyu_repeat()
            dx = event.position().x() - self.drag_x
            if self.drag_distance > 22 and abs(dx) > 18:
                target = self.drag_page + (-1 if dx > 0 else 1)
            else:
                target = self.drag_page
                # 轻点单词页：取得焦点，可直接按空格开始默写
                if target == PAGE_WORD and self.spell_result is None:
                    self.setFocus()
                elif target == PAGE_MUYU:
                    # 木鱼页轻点只取焦点，不敲；敲击靠空格或长按
                    self.setFocus()
                    self.update_tip()
                    return
                elif target == PAGE_NOVEL:
                    # 轻点小说页：暂停/继续，顺便取焦点好接键盘快捷键；没书就去选文件
                    if self.shelf.current_book() is None:
                        self.open_settings_center("novel")
                        return
                    self.setFocus()
                    self.load_novel_book()
                    self.novel_paused = not self.novel_paused
                    self.update_tip()
                    self.update()
                    return
            self.animate_view(target)

    # ---- 小说：换书 / 跳章 / 跳进度（阅读页面本身不动） ----
    def novel_refresh(self):
        self.update_tip()
        self.update()

    def novel_switch_book(self, path, goto=False):
        """切到书架里另一本；已读位置各自保留。"""
        if not path or not self.shelf.get(path):
            return False
        if self.novel.book:
            self.novel.save()
        self.shelf.set_current(path)
        ok = self.load_novel_book(
            notify=lambda t, m: styled_message(self, t, m, QMessageBox.Icon.Warning)
        )
        if goto:
            self.goto_page(PAGE_NOVEL)
        self.novel_refresh()
        return ok

    def novel_step_book(self, delta, goto=False):
        return self.novel_switch_book(self.shelf.step_book(delta), goto=goto)

    def novel_action(self, fn, *args):
        """跳转类操作的统一入口：确保正文已载入、存进度、刷提示。"""
        if self.novel.book is None:
            self.load_novel_book()
        if self.novel.book is None:
            return False
        result = fn(*args)
        self.shelf.touch(self.novel.book["path"])
        self.novel_refresh()
        return result

    def novel_seek_percent(self, pct):
        return self.novel_action(self.novel.goto_percent, pct)

    def novel_goto_chapter(self, index):
        return self.novel_action(self.novel.goto_chapter, index)

    def novel_step_chapter(self, delta):
        return self.novel_action(self.novel.step_chapter, delta)

    def novel_goto_start(self):
        return self.novel_action(self.novel.goto_start)

    def novel_goto_end(self):
        return self.novel_action(self.novel.goto_end)

    def novel_page_scroll(self, sign):
        return self.novel_action(self.novel.page_scroll, sign)

    # ---- 小说：条内滚动 ----
    def load_novel_book(self, notify=None):
        """把当前书架里的书装进条内视图；已经装过同一本就不重读。"""
        book = self.shelf.current_book()
        if book is None:
            self.novel.unload()
            return False
        if self.novel.book and self.novel.book["path"] == book["path"]:
            return True
        ok = self.novel.load(book)
        if not ok and notify:
            notify("打开小说失败", f"文件可能已移动或删除：\n{book['path']}")
        self.update_tip()
        return ok

    def novel_running(self):
        return (
            self.page == PAGE_NOVEL
            and int(round(self.view)) == PAGE_NOVEL
            and self.hover_inside
            and not self.novel_paused
            and self.novel.book is not None
            and not self.novel.at_end()
        )

    def novel_tick(self):
        if not self.novel_running():
            return
        if self.novel.advance(0.033):
            self.update()
            now = time.time()
            if now - self.novel_save_at > 3:
                self.novel_save_at = now
                self.novel.save()
        else:
            # 刚滚到末尾：存一次、刷新提示，之后就静着不动了
            self.novel.save()
            self.update()
            self.update_tip()

    def enterEvent(self, event):
        self.hover_inside = True
        if self.page == PAGE_NOVEL and self.weather_on:
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_inside = False
        if self.page == PAGE_NOVEL:
            if self.novel.book is not None:
                self.novel.save()
                self.update_tip()
            self.update()
            self.maybe_request_weather()
        super().leaveEvent(event)

    # ---- 天气伪装 ----
    def weather_shown(self):
        """鼠标不在条上、且停在小说页时，这一页改成天气。"""
        return (
            self.page == PAGE_NOVEL
            and int(round(self.view)) == PAGE_NOVEL
            and not self.hover_inside
            and self.weather_on
        )

    def poll_hover(self):
        """轮询鼠标位置——拖动、切页、窗口被盖住时 enter/leave 都可能不准。"""
        inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        if inside == self.hover_inside:
            return
        was = self.hover_inside
        self.hover_inside = inside
        if self.page != PAGE_NOVEL:
            return
        if was and not inside:
            if self.novel.book is not None:
                self.novel.save()
            self.maybe_request_weather()
        self.update()

    def maybe_request_weather(self):
        """需要展示天气了：没数据、或数据过期，就后台取一次。"""
        if not self.weather_on or self.weather.busy():
            return
        now = time.time()
        if self.weather_error and now - self.weather_tried_at < 120:
            return  # 刚失败过，别每 30 秒锤一次
        at = float(self.weather_data.get("at", 0) or 0)
        if not self.weather_data or now - at >= self.weather_interval * 60:
            self.request_weather()

    def request_weather(self, force=False):
        if self.weather.busy():
            return
        if not self.weather_on and not force:
            return
        self.weather_tried_at = time.time()
        self.weather_busy = True
        self.weather_error = ""
        if not self.weather.refresh(self.weather_city or None):
            self.weather_busy = False
        self.update()

    def weather_tick(self):
        if self.page != PAGE_NOVEL:
            return
        self.maybe_request_weather()
        if self.weather_busy:
            self.update()

    def on_weather_ready(self, data):
        self.weather_busy = False
        self.weather_error = ""
        self.weather_data = dict(data or {})
        if self.weather_shown():
            self.update()

    def on_weather_failed(self, msg):
        self.weather_busy = False
        self.weather_error = str(msg or "获取失败")
        if self.weather_shown():
            self.update()

    def wheelEvent(self, event):
        if self.page != PAGE_NOVEL or self.novel.book is None:
            super().wheelEvent(event)
            return
        dy = event.angleDelta().y()
        if dy:
            self.novel.scroll_by(-dy / 2.0)
            self.novel.save()
            self.update()
            self.update_tip()

    # ---- 电子木鱼：敲击与连击 ----
    def muyu_hit_once(self):
        self.muyu.hit()
        # 有动画就开 30fps 定时器，动画自己会停
        if not self.muyu_anim_timer.isActive():
            self.muyu_anim_timer.start()
        self.update()

    def animate_muyu(self):
        """木鱼动画帧：飘字/微震结束后自动停表，别空转吃 CPU。"""
        self.update()
        now = time.monotonic()
        elapsed = (now - self.muyu.hit_at) * 1000.0 if self.muyu.hit_at else 9999.0
        # live_floats 顺手清掉过期项，队列空且微震结束就可以停了
        self.muyu.live_floats(now)
        if elapsed > MUYU_HIT_ANIM_MS and not self.muyu.floats:
            self.muyu_anim_timer.stop()

    def start_muyu_repeat(self):
        """按住超过阈值后进入连击：立刻敲一下，之后定时重复。"""
        if self.page != PAGE_MUYU:
            return
        self.muyu_repeating = True
        self.muyu_hit_once()
        self.muyu_repeat_timer.start(MUYU_REPEAT_MS)
        self.update()

    def stop_muyu_repeat(self):
        self.muyu_hold_timer.stop()
        self.muyu_repeat_timer.stop()
        self.muyu_repeating = False

    # ---- 单词默写 ----
    def keyPressEvent(self, event):
        # 木鱼页：空格敲一下；系统的按键重复事件天然形成连击
        if self.page == PAGE_MUYU and int(round(self.view)) == PAGE_MUYU:
            if int(event.key()) == VK_SPACE:
                self.muyu_hit_once()
            return
        if self.page == PAGE_NOVEL and int(round(self.view)) == PAGE_NOVEL:
            key = int(event.key())
            text = event.text()
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if ctrl and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                self.novel_step_book(-1 if key == int(Qt.Key.Key_Left) else 1)
            elif key == VK_SPACE:
                self.novel_paused = not self.novel_paused
                self.novel_refresh()
            elif key == int(Qt.Key.Key_Home):
                self.novel_goto_start()
            elif key == int(Qt.Key.Key_End):
                self.novel_goto_end()
            elif key in (int(Qt.Key.Key_PageUp), int(Qt.Key.Key_Up)):
                self.novel_page_scroll(-1)
            elif key in (int(Qt.Key.Key_PageDown), int(Qt.Key.Key_Down)):
                self.novel_page_scroll(1)
            elif key == int(Qt.Key.Key_Left) or text == "[":
                self.novel_step_chapter(-1)
            elif key == int(Qt.Key.Key_Right) or text == "]":
                self.novel_step_chapter(1)
            return
        if self.page != PAGE_WORD or int(round(self.view)) != PAGE_WORD:
            super().keyPressEvent(event)
            return
        key = int(event.key())
        text = event.text()

        # 空格开始默写 / 判定期重开
        if key == VK_SPACE:
            if not self.spelling or self.spell_result is not None:
                self.start_spelling()
            return
        if not self.spelling or self.spell_result is not None:
            return
        if key == int(Qt.Key.Key_Backspace):
            self.spell_input = self.spell_input[:-1]
            self.update()
            return
        if key == int(Qt.Key.Key_Escape):
            self.spelling = False
            self.spell_input = ""
            self.update()
            return
        # 仅接受英文字母，最多输入到单词长度
        if len(text) == 1 and text.isascii() and text.isalpha():
            word, _, _ = self.deck.current()
            if len(self.spell_input) < len(word):
                self.spell_input += text.lower()
                if len(self.spell_input) == len(word):
                    self.judge_spelling()
                else:
                    self.update()

    def start_spelling(self):
        self.feedback_timer.stop()
        self.spelling = True
        self.spell_input = ""
        self.spell_result = None
        self.update_tip()
        self.update()

    def judge_spelling(self):
        word, _, _ = self.deck.current()
        self.spell_result = self.spell_input == word.lower()
        # 无论对错都记入学习档案（答错标记为模糊）
        self.deck.mark(self.spell_result)
        self.update_tip()
        self.update()
        self.feedback_timer.start(FEEDBACK_MS)

    def finish_feedback(self):
        self.spelling = False
        self.spell_input = ""
        self.spell_result = None
        self.deck.next_word()
        self.update_tip()
        self.update()

    def reset_spelling_state(self):
        """切换词库/进度时清空默写状态。"""
        self.feedback_timer.stop()
        self.spelling = False
        self.spell_input = ""
        self.spell_result = None

    def on_message_clicked(self):
        """点击系统通知：把最近触发的那条延后 10 分钟。"""
        if self.reminders.last_notified:
            for it in self.reminders.items:
                if it["name"] == self.reminders.last_notified:
                    self.reminders.snooze(it, 10)
                    break
            self.update_tip()

    def check_reminders(self):
        fired = self.reminders.check()
        if fired:
            self.update_tip()

    def open_settings_center(self, panel_key="salary", novel_tab=None):
        """统一设置中心：工资 / 单词 / 健康提醒 / 摸鱼阅读。"""
        dialog = SettingsCenter(self, self)
        dialog.show_panel(panel_key)
        if novel_tab is not None and "novel" in dialog.panels:
            dialog.panels["novel"].set_tab(novel_tab)
        dialog.exec()
        self.load_novel_book()
        self.update_tip()
        self.update()

    def open_help(self):
        """详细使用说明：替代原来鼠标一停就弹的那块提示。"""
        HelpDialog(self).exec()

    def toggle_view(self):
        self.show_total = not self.show_total
        self.update()

    def toggle_pause(self):
        if self.paused:
            self.paused = False
        else:
            self.paused_value = self.earned
            self.paused = True
        self.shown_earned = self.earned
        self.update_tip()

    def reset_earned(self):
        """把今天的累计清零，之后按秒照涨；过了零点自动作废。"""
        self.reset_day = datetime.date.today()
        self.reset_value = self.earned_today()
        if self.paused:
            self.paused_value = 0.0
        self.shown_earned = self.earned
        self.update()
        self.update_tip()

    def toggle_visibility(self):
        if self.isVisible():
            self.novel.save()
            self.hide()
        else:
            self.locate()
            self.show()
            force_topmost(int(self.winId()))
        self.update_menu()

    def update_menu(self):
        for i, action in enumerate(self.page_actions):
            action.setText(("▸ " if i == self.page else "   ") + PAGE_NAMES[i])
        self.visibility_action.setText(
            "隐藏窗口 (Ctrl+Q)" if self.isVisible() else "显示窗口 (Ctrl+Q)"
        )

    def cleanup(self):
        try:
            self.novel.save()
            self.shelf.save()
        except Exception:
            pass
        if getattr(self, "hotkey_registered", False):
            user32.UnregisterHotKey(None, HOTKEY_ID)


def acquire_single_instance():
    """只允许开一个。

    双开会画出两条重叠的小条、提醒重复弹、还会抢同一份阅读进度。
    返回 False 表示已经有一个在跑。
    """
    global _single_instance_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True  # 拿不到锁就当没这回事，别拦着启动
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return False
    _single_instance_handle = handle  # 留着引用，进程活着这把锁就不放
    return True


class StartupSplash(QWidget):
    """启动屏：双击后尽快出现，避免解压/初始化那几秒看起来像没启动。

    只在启动阶段存在，主界面就绪后自动淡出；不抢焦点、不进任务栏。
    """

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(440, 250)
        self.light = is_light_theme()
        self.phase = 0.0
        self._fade = None
        logo_path = _resource_path("Niumer-head.png")
        self.logo = QPixmap(logo_path) if os.path.exists(logo_path) else QPixmap()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self._center()

    def _center(self):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.move(geo.center() - self.rect().center())

    def _tick(self):
        self.phase = (self.phase + 0.02) % 1.0
        self.update()

    def finish(self, elapsed_ms):
        """主界面已就绪：至少显示满 0.9 秒再淡出，避免闪一下就没。"""
        QTimer.singleShot(max(0, 900 - int(elapsed_ms)), self._fade_out)

    def _fade_out(self):
        self._timer.stop()
        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(220)
        anim.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
        anim.finished.connect(self.close)
        anim.start()
        self._fade = anim

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if self.light:
            bg, border = QColor("#f7f8fa"), QColor("#e2e5e9")
            text, sub, hint = QColor("#1a1d22"), QColor("#8b929c"), QColor("#5c646f")
            track, accent = QColor("#e6e9ee"), QColor("#0078d4")
        else:
            bg, border = QColor("#1e2228"), QColor("#333a44")
            text, sub, hint = QColor("#f3f5f8"), QColor("#9aa4b0"), QColor("#c3c9d2")
            track, accent = QColor("#2f3641"), QColor("#4c8dff")

        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)
        p.fillPath(path, bg)
        p.setPen(QPen(border, 1))
        p.drawPath(path)

        logo_rect = QRectF(36, 34, 64, 64)
        if not self.logo.isNull():
            clip = QPainterPath()
            clip.addRoundedRect(logo_rect, 14, 14)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(logo_rect.toRect(), self.logo)
            p.restore()
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawRoundedRect(logo_rect, 14, 14)

        title_font = QFont("Microsoft YaHei")
        title_font.setPixelSize(30)
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(text)
        p.drawText(
            QRectF(116, 32, 290, 40),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Niumer",
        )

        sub_font = QFont("Microsoft YaHei")
        sub_font.setPixelSize(14)
        p.setFont(sub_font)
        p.setPen(sub)
        p.drawText(
            QRectF(117, 72, 290, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"v{VERSION} · by {AUTHOR}",
        )

        status_font = QFont("Microsoft YaHei")
        status_font.setPixelSize(15)
        status_font.setBold(True)
        p.setFont(status_font)
        p.setPen(hint)
        p.drawText(
            QRectF(36, 140, 320, 26),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "正在启动…",
        )

        tip_font = QFont("Microsoft YaHei")
        tip_font.setPixelSize(13)
        p.setFont(tip_font)
        p.setPen(sub)
        p.drawText(
            QRectF(36, 168, 368, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "首次启动要解压组件，稍等两三秒",
        )

        bar_rect = QRectF(36, 212, 368, 4)
        track_path = QPainterPath()
        track_path.addRoundedRect(bar_rect, 2, 2)
        p.fillPath(track_path, track)
        seg_w = 96.0
        seg = QRectF(36 + (368 - seg_w) * self.phase, 212, seg_w, 4)
        seg_path = QPainterPath()
        seg_path.addRoundedRect(seg, 2, 2)
        p.fillPath(seg_path, accent)
        p.end()


def main():
    set_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Niumer")
    app.setApplicationVersion(VERSION)
    if not acquire_single_instance():
        styled_message(
            None, "Niumer",
            "已经在运行了 —— 看任务栏右下角那条，不用再开一个。",
        )
        return
    # 先把启动屏摆出来，再加载图标、构建主窗口：双击后马上有反馈
    splash = StartupSplash()
    splash.show()
    app.processEvents()
    clock = QElapsedTimer()
    clock.start()
    # 全局窗口图标：标题栏左上角的 logo。QApplication 级别设置后，
    # 所有后续创建的对话框/窗口都会自动继承，不用逐个 setWindowIcon。
    app.setWindowIcon(make_tray_icon())
    bar = SalaryBar(app)  # noqa: F841
    splash.finish(clock.elapsed())
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
