"""Niumer —— 牛马打工人的桌面助手条。

窗口固定在任务栏右下角，尺寸恒定 186x32。左键按住水平拖动切换三页：
  1) 工资条：实时累计今日工钱与每秒收入
  2) 单词卡：显示单词；点一下窗口后按空格进入默写，逐字输入判定
  3) 小说页：正文直接在小条里滚动，鼠标停在条上才走，移开即停；
     鼠标一离开就换成当地天气（伪装），移回来立刻恢复小说
Ctrl+Q 或右键菜单隐藏/显示；左键轻点不隐藏窗口。
"""
import ctypes
import datetime
import json
import math
import os
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
    QRectF, QSettings, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QFontMetricsF, QIcon, QImage,
    QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF,
    QTextBlockFormat, QTextCursor, QTextDocument,
)
from PyQt6.QtGui import QAbstractTextDocumentLayout
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QSystemTrayIcon, QTextBrowser, QVBoxLayout, QWidget,
)

WORK_HOURS_PER_DAY = 8
WORK_DAYS_PER_MONTH = 22
SECONDS_PER_MONTH = WORK_DAYS_PER_MONTH * WORK_HOURS_PER_DAY * 60 * 60

PAGE_SALARY, PAGE_WORD, PAGE_NOVEL = 0, 1, 2
PAGE_COUNT = 3
PAGE_NAMES = ("工资条 · Niumer", "单词卡 · 偷偷背", "小说 · 摸鱼读")
VK_SPACE = 0x20
FEEDBACK_MS = 1400

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

BUILTIN_WORDS = [
    ("abandon", "/əˈbændən/", "v. 放弃；抛弃"),
    ("benefit", "/ˈbenɪfɪt/", "n. 益处；v. 受益"),
    ("campaign", "/kæmˈpeɪn/", "n. 运动；战役"),
    ("capacity", "/kəˈpæsəti/", "n. 容量；能力"),
    ("commit", "/kəˈmɪt/", "v. 承诺；犯（错）"),
    ("compete", "/kəmˈpiːt/", "v. 竞争；比赛"),
    ("conclude", "/kənˈkluːd/", "v. 得出结论；结束"),
    ("consequence", "/ˈkɒnsɪkwəns/", "n. 后果；结果"),
    ("consider", "/kənˈsɪdə/", "v. 考虑；认为"),
    ("constant", "/ˈkɒnstənt/", "a. 持续的；不变的"),
    ("contribute", "/kənˈtrɪbjuːt/", "v. 贡献；促成"),
    ("convince", "/kənˈvɪns/", "v. 说服；使确信"),
    ("decline", "/dɪˈklaɪn/", "v. 下降；婉拒"),
    ("dedicate", "/ˈdedɪkeɪt/", "v. 奉献；致力于"),
    ("definite", "/ˈdefɪnət/", "a. 明确的；确定的"),
    ("demonstrate", "/ˈdemənstreɪt/", "v. 证明；演示"),
    ("deserve", "/dɪˈzɜːv/", "v. 值得；应得"),
    ("determine", "/dɪˈtɜːmɪn/", "v. 决定；查明"),
    ("distinguish", "/dɪˈstɪŋɡwɪʃ/", "v. 区分；辨别"),
    ("efficient", "/ɪˈfɪʃnt/", "a. 高效的"),
    ("eliminate", "/ɪˈlɪmɪneɪt/", "v. 消除；淘汰"),
    ("emphasis", "/ˈemfəsɪs/", "n. 强调；重点"),
    ("encounter", "/ɪnˈkaʊntə/", "v. 遭遇；遇到"),
    ("enhance", "/ɪnˈhɑːns/", "v. 增强；提高"),
    ("enormous", "/ɪˈnɔːməs/", "a. 巨大的"),
    ("essential", "/ɪˈsenʃl/", "a. 必要的；本质的"),
    ("establish", "/ɪˈstæblɪʃ/", "v. 建立；确立"),
    ("evaluate", "/ɪˈvæljueɪt/", "v. 评估；评价"),
    ("evident", "/ˈevɪdənt/", "a. 明显的"),
    ("exhibit", "/ɪɡˈzɪbɪt/", "v. 展示；展览"),
    ("facilitate", "/fəˈsɪlɪteɪt/", "v. 促进；使便利"),
    ("generate", "/ˈdʒenəreɪt/", "v. 产生；生成"),
    ("genuine", "/ˈdʒenjuɪn/", "a. 真正的；真诚的"),
    ("gradually", "/ˈɡrædʒuəli/", "ad. 逐渐地"),
    ("identify", "/aɪˈdentɪfaɪ/", "v. 识别；确认"),
    ("illustrate", "/ˈɪləstreɪt/", "v. 说明；举例"),
    ("impact", "/ˈɪmpækt/", "n. 影响；冲击"),
    ("implement", "/ˈɪmplɪment/", "v. 实施；执行"),
    ("maintain", "/meɪnˈteɪn/", "v. 维持；保养"),
    ("negotiate", "/nɪˈɡəʊʃieɪt/", "v. 谈判；协商"),
    ("obvious", "/ˈɒbviəs/", "a. 明显的"),
    ("participate", "/pɑːˈtɪsɪpeɪt/", "v. 参与"),
    ("potential", "/pəˈtenʃl/", "a. 潜在的；n. 潜力"),
    ("recognize", "/ˈrekəɡnaɪz/", "v. 认出；承认"),
    ("significant", "/sɪɡˈnɪfɪkənt/", "a. 重要的；显著的"),
    ("sufficient", "/səˈfɪʃnt/", "a. 充足的"),
]


KAOYAN_WORDS = [
    ("abandon", "/əˈbændən/", "v. 放弃；抛弃"),
    ("absorb", "/əbˈsɔːb/", "v. 吸收；使全神贯注"),
    ("abstract", "/ˈæbstrækt/", "a. 抽象的；n. 摘要"),
    ("academic", "/ˌækəˈdemɪk/", "a. 学术的；学院的"),
    ("access", "/ˈækses/", "n. 通道；v. 访问"),
    ("accommodate", "/əˈkɒmədeɪt/", "v. 容纳；适应"),
    ("accompany", "/əˈkʌmpəni/", "v. 陪伴；伴随"),
    ("accomplish", "/əˈkʌmplɪʃ/", "v. 完成；实现"),
    ("account", "/əˈkaʊnt/", "n. 账户；v. 解释"),
    ("accumulate", "/əˈkjuːmjuleɪt/", "v. 积累；积聚"),
    ("accurate", "/ˈækjərət/", "a. 准确的"),
    ("accuse", "/əˈkjuːz/", "v. 指控；指责"),
    ("acknowledge", "/əkˈnɒlɪdʒ/", "v. 承认；致谢"),
    ("acquire", "/əˈkwaɪə/", "v. 获得；学到"),
    ("adapt", "/əˈdæpt/", "v. 适应；改编"),
    ("adequate", "/ˈædɪkwət/", "a. 足够的；适当的"),
    ("adjust", "/əˈdʒʌst/", "v. 调整；适应"),
    ("administer", "/ədˈmɪnɪstə/", "v. 管理；实施"),
    ("admit", "/ədˈmɪt/", "v. 承认；准许进入"),
    ("adopt", "/əˈdɒpt/", "v. 采用；收养"),
    ("advocate", "/ˈædvəkeɪt/", "v. 提倡；n. 拥护者"),
    ("affect", "/əˈfekt/", "v. 影响；感动"),
    ("afford", "/əˈfɔːd/", "v. 负担得起"),
    ("agenda", "/əˈdʒendə/", "n. 议程；日程"),
    ("aggregate", "/ˈæɡrɪɡət/", "n. 总计；a. 合计的"),
    ("allocate", "/ˈæləkeɪt/", "v. 分配；拨给"),
    ("ambiguous", "/æmˈbɪɡjuəs/", "a. 模糊的；歧义的"),
    ("analyze", "/ˈænəlaɪz/", "v. 分析；分解"),
    ("anticipate", "/ænˈtɪsɪpeɪt/", "v. 预期；期望"),
    ("apparent", "/əˈpærənt/", "a. 明显的；表面上的"),
    ("appeal", "/əˈpiːl/", "v. 呼吁；n. 吸引力"),
    ("apprehend", "/ˌæprɪˈhend/", "v. 理解；逮捕"),
    ("approach", "/əˈprəʊtʃ/", "n. 方法；v. 接近"),
    ("appropriate", "/əˈprəʊpriət/", "a. 适当的"),
    ("approve", "/əˈpruːv/", "v. 批准；赞成"),
    ("arbitrary", "/ˈɑːbɪtrəri/", "a. 任意的；武断的"),
    ("assess", "/əˈses/", "v. 评估；评定"),
    ("assign", "/əˈsaɪn/", "v. 分配；指派"),
    ("assume", "/əˈsjuːm/", "v. 假定；承担"),
    ("assure", "/əˈʃʊə/", "v. 使确信；保证"),
    ("attain", "/əˈteɪn/", "v. 达到；获得"),
    ("attempt", "/əˈtempt/", "n./v. 尝试；企图"),
    ("attribute", "/əˈtrɪbjuːt/", "v. 归因于；n. 属性"),
    ("authentic", "/ɔːˈθentɪk/", "a. 真实的；可靠的"),
    ("automate", "/ˈɔːtəmeɪt/", "v. 使自动化"),
    ("beneficial", "/ˌbenɪˈfɪʃl/", "a. 有益的"),
    ("bias", "/ˈbaɪəs/", "n. 偏见；v. 使有偏见"),
    ("boost", "/buːst/", "v. 促进；提高"),
    ("boundary", "/ˈbaʊndri/", "n. 边界；界限"),
    ("breakthrough", "/ˈbreɪkθruː/", "n. 突破；重大进展"),
    ("calculate", "/ˈkælkjuleɪt/", "v. 计算；推测"),
    ("capable", "/ˈkeɪpəbl/", "a. 有能力的"),
    ("capacity", "/kəˈpæsəti/", "n. 容量；能力"),
    ("challenge", "/ˈtʃælɪndʒ/", "n./v. 挑战"),
    ("characteristic", "/ˌkærəktəˈrɪstɪk/", "n. 特征；a. 典型的"),
    ("circumstance", "/ˈsɜːkəmstəns/", "n. 环境；情况"),
    ("commit", "/kəˈmɪt/", "v. 承诺；犯（错）"),
    ("commodity", "/kəˈmɒdəti/", "n. 商品；日用品"),
    ("compensate", "/ˈkɒmpenseɪt/", "v. 补偿；弥补"),
    ("compete", "/kəmˈpiːt/", "v. 竞争；比赛"),
    ("compile", "/kəmˈpaɪl/", "v. 汇编；编纂"),
    ("comply", "/kəmˈplaɪ/", "v. 遵守；顺从"),
    ("conceive", "/kənˈsiːv/", "v. 构想；想象"),
    ("concentrate", "/ˈkɒnsntreɪt/", "v. 集中；专注"),
    ("conclude", "/kənˈkluːd/", "v. 得出结论；结束"),
    ("conduct", "/kənˈdʌkt/", "v. 实施；conduct n. 行为"),
    ("conference", "/ˈkɒnfərəns/", "n. 会议；讨论会"),
    ("confirm", "/kənˈfɜːm/", "v. 确认；证实"),
    ("conform", "/kənˈfɔːm/", "v. 遵守；符合"),
    ("consequence", "/ˈkɒnsɪkwəns/", "n. 后果；结果"),
    ("conservative", "/kənˈsɜːvətɪv/", "a. 保守的"),
    ("considerable", "/kənˈsɪdərəbl/", "a. 相当大的；重要的"),
    ("consistent", "/kənˈsɪstənt/", "a. 一致的；始终如一的"),
    ("constant", "/ˈkɒnstənt/", "a. 持续的；不变的"),
    ("constitute", "/ˈkɒnstɪtjuːt/", "v. 构成；组成"),
    ("constrain", "/kənˈstreɪn/", "v. 限制；约束"),
    ("construct", "/kənˈstrʌkt/", "v. 建造；构造"),
    ("consult", "/kənˈsʌlt/", "v. 咨询；查阅"),
    ("consume", "/kənˈsjuːm/", "v. 消耗；消费"),
    ("contemporary", "/kənˈtempərəri/", "a. 当代的；同时代的"),
    ("contend", "/kənˈtend/", "v. 竞争；主张"),
    ("contribute", "/kənˈtrɪbjuːt/", "v. 贡献；促成"),
    ("convince", "/kənˈvɪns/", "v. 说服；使确信"),
    ("cooperate", "/kəʊˈɒpəreɪt/", "v. 合作；配合"),
    ("crucial", "/ˈkruːʃl/", "a. 关键的；至关重要的"),
    ("cumulative", "/ˈkjuːmjələtɪv/", "a. 累积的"),
    ("decline", "/dɪˈklaɪn/", "v./n. 下降；婉拒"),
    ("dedicate", "/ˈdedɪkeɪt/", "v. 奉献；致力于"),
    ("deficiency", "/dɪˈfɪʃnsi/", "n. 缺乏；不足"),
    ("definite", "/ˈdefɪnət/", "a. 明确的；确定的"),
    ("demonstrate", "/ˈdemənstreɪt/", "v. 证明；演示"),
    ("denote", "/dɪˈnəʊt/", "v. 表示；意味着"),
    ("deserve", "/dɪˈzɜːv/", "v. 值得；应得"),
    ("determine", "/dɪˈtɜːmɪn/", "v. 决定；查明"),
    ("diminish", "/dɪˈmɪnɪʃ/", "v. 减少；削弱"),
    ("distinguish", "/dɪˈstɪŋɡwɪʃ/", "v. 区分；辨别"),
    ("distribute", "/dɪˈstrɪbjuːt/", "v. 分发；分布"),
    ("diverse", "/daɪˈvɜːs/", "a. 多样的；不同的"),
    ("dominant", "/ˈdɒmɪnənt/", "a. 占主导地位的"),
    ("efficient", "/ɪˈfɪʃnt/", "a. 高效的"),
    ("eliminate", "/ɪˈlɪmɪneɪt/", "v. 消除；淘汰"),
    ("emerge", "/iˈmɜːdʒ/", "v. 出现；浮现"),
    ("emphasis", "/ˈemfəsɪs/", "n. 强调；重点"),
    ("employ", "/ɪmˈplɔɪ/", "v. 雇用；使用"),
    ("encounter", "/ɪnˈkaʊntə/", "v./n. 遭遇；遇到"),
    ("enhance", "/ɪnˈhɑːns/", "v. 增强；提高"),
    ("enormous", "/ɪˈnɔːməs/", "a. 巨大的"),
    ("ensure", "/ɪnˈʃʊə/", "v. 确保；保证"),
    ("essential", "/ɪˈsenʃl/", "a. 必要的；本质的"),
    ("establish", "/ɪˈstæblɪʃ/", "v. 建立；确立"),
    ("evaluate", "/ɪˈvæljueɪt/", "v. 评估；评价"),
    ("evident", "/ˈevɪdənt/", "a. 明显的"),
    ("exceed", "/ɪkˈsiːd/", "v. 超过；超出"),
    ("exclude", "/ɪkˈskluːd/", "v. 排除；不包括"),
    ("exhibit", "/ɪɡˈzɪbɪt/", "v. 展示；n. 展品"),
    ("expand", "/ɪkˈspænd/", "v. 扩大；膨胀"),
    ("expectation", "/ˌekspekˈteɪʃn/", "n. 期望；预期"),
    ("explicit", "/ɪkˈsplɪsɪt/", "a. 明确的；清楚的"),
    ("exploit", "/ɪkˈsplɔɪt/", "v. 利用；剥削"),
    ("facilitate", "/fəˈsɪlɪteɪt/", "v. 促进；使便利"),
    ("fundamental", "/ˌfʌndəˈmentl/", "a. 基本的；根本的"),
    ("generate", "/ˈdʒenəreɪt/", "v. 产生；生成"),
    ("genuine", "/ˈdʒenjuɪn/", "a. 真正的；真诚的"),
    ("gradually", "/ˈɡrædʒuəli/", "ad. 逐渐地"),
    ("guarantee", "/ˌɡærənˈtiː/", "v./n. 保证；担保"),
    ("identical", "/aɪˈdentɪkl/", "a. 完全相同的"),
    ("identify", "/aɪˈdentɪfaɪ/", "v. 识别；确认"),
    ("illustrate", "/ˈɪləstreɪt/", "v. 说明；举例"),
    ("impact", "/ˈɪmpækt/", "n. 影响；冲击"),
    ("implement", "/ˈɪmplɪment/", "v. 实施；执行"),
    ("imply", "/ɪmˈplaɪ/", "v. 暗示；意味着"),
    ("impose", "/ɪmˈpəʊz/", "v. 强加；征收"),
    ("incentive", "/ɪnˈsentɪv/", "n. 激励；动机"),
    ("indicate", "/ˈɪndɪkeɪt/", "v. 表明；指出"),
    ("individual", "/ˌɪndɪˈvɪdʒuəl/", "n. 个人；a. 个别的"),
    ("inevitable", "/ɪnˈevɪtəbl/", "a. 不可避免的"),
    ("influence", "/ˈɪnfluəns/", "n./v. 影响"),
    ("innovation", "/ˌɪnəˈveɪʃn/", "n. 创新；革新"),
    ("insight", "/ˈɪnsaɪt/", "n. 洞察力；见解"),
    ("insist", "/ɪnˈsɪst/", "v. 坚持；坚决要求"),
    ("integrate", "/ˈɪntɪɡreɪt/", "v. 整合；使成整体"),
    ("intend", "/ɪnˈtend/", "v. 打算；意图"),
    ("interpret", "/ɪnˈtɜːprɪt/", "v. 解释；口译"),
    ("interval", "/ˈɪntəvl/", "n. 间隔；间距"),
    ("introduce", "/ˌɪntrəˈdjuːs/", "v. 介绍；引进"),
    ("investigate", "/ɪnˈvestɪɡeɪt/", "v. 调查；研究"),
    ("involve", "/ɪnˈvɒlv/", "v. 涉及；使参与"),
    ("isolate", "/ˈaɪsəleɪt/", "v. 隔离；孤立"),
    ("justify", "/ˈdʒʌstɪfaɪ/", "v. 证明…正当；辩护"),
    ("maintain", "/meɪnˈteɪn/", "v. 维持；保养"),
    ("majority", "/məˈdʒɒrəti/", "n. 多数；大多数"),
    ("manipulate", "/məˈnɪpjuleɪt/", "v. 操纵；控制"),
    ("mechanism", "/ˈmekənɪzəm/", "n. 机制；机械装置"),
    ("minimize", "/ˈmɪnɪmaɪz/", "v. 使最小化"),
    ("moderate", "/ˈmɒdərət/", "a. 适度的；温和的"),
    ("modify", "/ˈmɒdɪfaɪ/", "v. 修改；调整"),
    ("monitor", "/ˈmɒnɪtə/", "v. 监控；n. 显示器"),
    ("motivate", "/ˈməʊtɪveɪt/", "v. 激励；促进"),
    ("negotiate", "/nɪˈɡəʊʃieɪt/", "v. 谈判；协商"),
    ("nevertheless", "/ˌnevəðəˈles/", "ad. 然而；不过"),
    ("objective", "/əbˈdʒektɪv/", "n. 目标；a. 客观的"),
    ("obvious", "/ˈɒbviəs/", "a. 明显的"),
    ("occupy", "/ˈɒkjupaɪ/", "v. 占据；占用"),
    ("occurred", "/əˈkɜːd/", "v. 发生；出现"),
    ("offset", "/ˈɒfset/", "v. 抵消；补偿"),
    ("participate", "/pɑːˈtɪsɪpeɪt/", "v. 参与"),
    ("particular", "/pəˈtɪkjələ/", "a. 特定的；讲究的"),
    ("perceive", "/pəˈsiːv/", "v. 感知；察觉"),
    ("perspective", "/pəˈspektɪv/", "n. 视角；观点"),
    ("phenomenon", "/fəˈnɒmɪnən/", "n. 现象"),
    ("potential", "/pəˈtenʃl/", "a. 潜在的；n. 潜力"),
    ("precise", "/prɪˈsaɪs/", "a. 精确的"),
    ("predict", "/prɪˈdɪkt/", "v. 预测；预言"),
    ("prejudice", "/ˈpredʒudɪs/", "n. 偏见；成见"),
    ("preliminary", "/prɪˈlɪmɪnəri/", "a. 初步的；预备的"),
    ("presume", "/prɪˈzjuːm/", "v. 假定；推测"),
    ("prevail", "/prɪˈveɪl/", "v. 盛行；获胜"),
    ("primary", "/ˈpraɪməri/", "a. 主要的；初级的"),
    ("principle", "/ˈprɪnsəpl/", "n. 原则；原理"),
    ("priority", "/praɪˈɒrəti/", "n. 优先；优先级"),
    ("proceed", "/prəˈsiːd/", "v. 继续进行"),
    ("professional", "/prəˈfeʃənl/", "a. 专业的；n. 专业人士"),
    ("promote", "/prəˈməʊt/", "v. 促进；晋升"),
    ("proportion", "/prəˈpɔːʃn/", "n. 比例；部分"),
    ("propose", "/prəˈpəʊz/", "v. 提议；提出"),
    ("prospect", "/ˈprɒspekt/", "n. 前景；前途"),
    ("prove", "/pruːv/", "v. 证明；证实"),
    ("pursue", "/pəˈsjuː/", "v. 追求；从事"),
    ("react", "/riˈækt/", "v. 反应；反抗"),
    ("reasonable", "/ˈriːznəbl/", "a. 合理的；公道的"),
    ("recognize", "/ˈrekəɡnaɪz/", "v. 认出；承认"),
    ("recommend", "/ˌrekəˈmend/", "v. 推荐；建议"),
    ("reduce", "/rɪˈdjuːs/", "v. 减少；降低"),
    ("reflect", "/rɪˈflekt/", "v. 反映；反思"),
    ("reform", "/rɪˈfɔːm/", "n./v. 改革；改造"),
    ("regard", "/rɪˈɡɑːd/", "v. 认为；n. 关注"),
    ("register", "/ˈredʒɪstə/", "v. 登记；注册"),
    ("reinforce", "/ˌriːɪnˈfɔːs/", "v. 加强；强化"),
    ("reject", "/rɪˈdʒekt/", "v. 拒绝；驳回"),
    ("relevant", "/ˈreləvənt/", "a. 相关的；切题的"),
    ("reliable", "/rɪˈlaɪəbl/", "a. 可靠的"),
    ("relieve", "/rɪˈliːv/", "v. 减轻；缓解"),
    ("reluctant", "/rɪˈlʌktənt/", "a. 不情愿的"),
    ("remarkable", "/rɪˈmɑːkəbl/", "a. 显著的；非凡的"),
    ("remedy", "/ˈremədi/", "n. 补救；v. 纠正"),
    ("remote", "/rɪˈməʊt/", "a. 遥远的；远程的"),
    ("remove", "/rɪˈmuːv/", "v. 移除；消除"),
    ("render", "/ˈrendə/", "v. 使成为；提供"),
    ("replace", "/rɪˈpleɪs/", "v. 取代；更换"),
    ("represent", "/ˌreprɪˈzent/", "v. 代表；表示"),
    ("require", "/rɪˈkwaɪə/", "v. 需要；要求"),
    ("resemble", "/rɪˈzembl/", "v. 相似；像"),
    ("reserve", "/rɪˈzɜːv/", "v. 保留；预订"),
    ("resist", "/rɪˈzɪst/", "v. 抵抗；忍住"),
    ("resolve", "/rɪˈzɒlv/", "v. 解决；决定"),
    ("resource", "/rɪˈsɔːs/", "n. 资源；财力"),
    ("respond", "/rɪˈspɒnd/", "v. 回应；反应"),
    ("restore", "/rɪˈstɔː/", "v. 恢复；修复"),
    ("restrict", "/rɪˈstrɪkt/", "v. 限制；约束"),
    ("retain", "/rɪˈteɪn/", "v. 保持；保留"),
    ("reveal", "/rɪˈviːl/", "v. 揭示；透露"),
    ("reverse", "/rɪˈvɜːs/", "v. 颠倒；n. 相反"),
    ("revise", "/rɪˈvaɪz/", "v. 修订；复习"),
    ("significant", "/sɪɡˈnɪfɪkənt/", "a. 重要的；显著的"),
    ("similar", "/ˈsɪmələ/", "a. 相似的"),
    ("simulate", "/ˈsɪmjuleɪt/", "v. 模拟；模仿"),
    ("sophisticated", "/səˈfɪstɪkeɪtɪd/", "a. 复杂的；精密的"),
    ("specific", "/spəˈsɪfɪk/", "a. 具体的；特定的"),
    ("speculate", "/ˈspekjuleɪt/", "v. 推测；投机"),
    ("stable", "/ˈsteɪbl/", "a. 稳定的"),
    ("standard", "/ˈstændəd/", "n. 标准；a. 标准的"),
    ("strategy", "/ˈstrætədʒi/", "n. 策略；战略"),
    ("strengthen", "/ˈstreŋθən/", "v. 加强；巩固"),
    ("subsequent", "/ˈsʌbsɪkwənt/", "a. 随后的；后来的"),
    ("substantial", "/səbˈstænʃl/", "a. 大量的；实质的"),
    ("substitute", "/ˈsʌbstɪtjuːt/", "v. 代替；n. 替代品"),
    ("sufficient", "/səˈfɪʃnt/", "a. 充足的"),
    ("sustain", "/səˈsteɪn/", "v. 维持；支撑"),
    ("tackle", "/ˈtækl/", "v. 处理；应对"),
    ("tendency", "/ˈtendənsi/", "n. 趋势；倾向"),
    ("transform", "/trænsˈfɔːm/", "v. 转变；改造"),
    ("transition", "/trænˈzɪʃn/", "n. 过渡；转变"),
    ("transmit", "/trænzˈmɪt/", "v. 传输；传播"),
    ("tremendous", "/trəˈmendəs/", "a. 巨大的；极好的"),
    ("trigger", "/ˈtrɪɡə/", "v. 引发；触发"),
    ("ultimate", "/ˈʌltɪmət/", "a. 最终的；根本的"),
    ("undermine", "/ˌʌndəˈmaɪn/", "v. 破坏；削弱"),
    ("undertake", "/ˌʌndəˈteɪk/", "v. 承担；着手"),
    ("uniform", "/ˈjuːnɪfɔːm/", "a. 统一的；n. 制服"),
    ("unique", "/juˈniːk/", "a. 独特的；唯一的"),
    ("utilize", "/ˈjuːtəlaɪz/", "v. 利用"),
    ("vary", "/ˈveəri/", "v. 变化；不同"),
    ("vast", "/vɑːst/", "a. 巨大的；广阔的"),
    ("verify", "/ˈverɪfaɪ/", "v. 核实；证明"),
    ("viable", "/ˈvaɪəbl/", "a. 可行的"),
    ("vital", "/ˈvaɪtl/", "a. 至关重要的；有活力的"),
    ("volatile", "/ˈvɒlətaɪl/", "a. 易变的；不稳定的"),
    ("widespread", "/ˈwaɪdspred/", "a. 广泛的；普遍的"),
    ("withdraw", "/wɪðˈdrɔː/", "v. 撤回；退出"),
    ("witness", "/ˈwɪtnəs/", "n. 目击者；v. 见证"),
    ("yield", "/jiːld/", "v. 产生；屈服"),
]


# 词库目录：id -> (显示名, 词表)
DECK_LIBRARY = {
    "basic": ("高频核心词", BUILTIN_WORDS),
    "kaoyan": ("考研核心词", KAOYAN_WORDS),
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


def per_second(monthly: float) -> float:
    return monthly / SECONDS_PER_MONTH


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
    """词库与学习进度；支持内置高频/考研/自定义，进度按词库独立保存。

    每个词的学习状态：0=未学 1=模糊(答错过) 2=已掌握(答对过且未再错)。
    状态按「单词」为键存 QSettings，切换词库互不干扰。
    """

    def __init__(self, settings):
        self.settings = settings
        self.deck_id = str(settings.value("deck_id", "basic"))
        # 兼容旧数据：之前词库存 word_list
        legacy = settings.value("word_list", "")
        if self.deck_id == "custom" and not legacy:
            self.deck_id = "basic"
        if self.deck_id not in DECK_LIBRARY and self.deck_id != "custom":
            self.deck_id = "basic"
        self.custom_words = self.parse(legacy) if legacy else []

        self.words = self._source_words()
        if not self.words:
            self.words = list(BUILTIN_WORDS)
            self.deck_id = "basic"

        self.index = self._load_index()
        self.states = self._load_states()   # word -> [status, correct, wrong]
        self.combo = 0

    # ---------- 词库源 ----------
    def _source_words(self):
        if self.deck_id == "custom":
            return list(self.custom_words)
        return list(DECK_LIBRARY[self.deck_id][1])

    @property
    def deck_name(self):
        if self.deck_id == "custom":
            return "自定义词库"
        return DECK_LIBRARY[self.deck_id][0]

    @staticmethod
    def parse(text):
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                out.append((parts[0], parts[1], parts[2]))
            else:
                sp = line.split(None, 1)
                if len(sp) == 2 and sp[0].isascii():
                    out.append((sp[0], "", sp[1]))
        return out

    # ---------- 持久化 ----------
    def _key(self, name):
        return f"deck_{self.deck_id}_{name}"

    def _load_index(self):
        raw = self.settings.value(self._key("index"), "")
        if raw == "":
            # 兼容旧键
            raw = self.settings.value("word_index", 0)
        try:
            return int(raw) % len(self.words)
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
        # 兼容旧 mastered 键
        parts = [f"{w},{v[0]},{v[1]},{v[2]}" for w, v in self.states.items()]
        self.settings.setValue(self._key("states"), ";".join(parts))
        self.settings.setValue("word_mastered", self.mastered_count)

    def save(self):
        self.settings.setValue("deck_id", self.deck_id)
        self.settings.setValue(self._key("index"), self.index)
        if self.deck_id == "custom":
            self.settings.setValue(
                "word_list", "\n".join("|".join(w) for w in self.custom_words)
            )
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
        if deck_id == "custom" and not self.custom_words:
            return False
        if deck_id != "custom" and deck_id not in DECK_LIBRARY:
            return False
        self.settings.setValue("deck_id", deck_id)
        self.deck_id = deck_id
        self.words = self._source_words()
        self.index = self._load_index()
        self.states = self._load_states()
        self.combo = 0
        return True

    def replace(self, words):
        """把自定义词库整体替换并切过去；进度归零。"""
        if not words:
            return False
        self.custom_words = list(words)
        self.settings.setValue("word_list", "\n".join("|".join(w) for w in words))
        # 自定义词库进度清零
        self.settings.remove("deck_custom_index")
        self.settings.remove("deck_custom_states")
        self.deck_id = "custom"
        self.words = self._source_words()
        self.index = 0
        self.states = {}
        self.combo = 0
        self.save()
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
                    self.books.append({
                        "path": p,
                        "title": str(it.get("title") or os.path.basename(p)),
                        "pos": int(it.get("pos", 0) or 0),
                        "total": int(it.get("total", 0) or 0),
                    })
        self.current = str(settings.value("novel_current", ""))

    def save(self):
        self.settings.setValue("novel_shelf", json.dumps(self.books, ensure_ascii=False))
        self.settings.setValue("novel_current", self.current)

    def add(self, path, text, total):
        """加入书架（同名路径则更新），返回书对象。"""
        title = os.path.splitext(os.path.basename(path))[0] or path
        for b in self.books:
            if b["path"] == path:
                b["title"] = title
                b["total"] = total
                self.current = path
                self.save()
                return b
        book = {"path": path, "title": title, "pos": 0, "total": total}
        self.books.insert(0, book)
        del self.books[self.MAX_BOOKS:]
        self.current = path
        self.save()
        return book

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
            self.save()

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
        QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox, QPlainTextEdit {{
            background:{p['card']}; border:1px solid {p['border']}; border-radius:4px;
            padding:5px 10px; color:{p['text']}; selection-background-color:{p['accent']};
            selection-color:#ffffff; }}
        QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{
            border:2px solid {p['accent']}; padding:4px 9px; }}
        QSpinBox QLineEdit, QDoubleSpinBox QLineEdit {{ border:none; background:transparent; padding:0; }}
        QComboBox::drop-down {{ border:none; width:20px; }}

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
        QDialogButtonBox QPushButton {{ min-width:80px; }}
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
            # 进度很低时（比如 261 个词背了 2 个）也要留一节看得见的头
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
    """工资面板：月薪、快捷预设、计时操作。"""

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

        info = QLabel(f"计算口径：月薪 ÷ {WORK_DAYS_PER_MONTH}天 × {WORK_HOURS_PER_DAY}小时 × 3600秒")
        info.setObjectName("Hint")
        root.addWidget(info)

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

    def update_preview(self):
        rate = per_second(self.spin.value())
        self.preview.setText(f"¥{rate:.4f}")
        self.detail.setText(
            f"按 {WORK_DAYS_PER_MONTH}天 × {WORK_HOURS_PER_DAY}小时算 · "
            f"一天约 ¥{rate * WORK_HOURS_PER_DAY * 3600:,.0f}"
        )

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
        new = self.spin.value()
        if abs(new - bar.monthly) > 1e-9:
            bar.earned_base = bar.earned
            bar.elapsed.restart()
            bar.monthly = new
            bar.settings.setValue("monthly_salary", new)
            bar.shown_earned = bar.earned
            bar.shown_rate = bar.rate
            bar.update_tip()


class WordsPanel(_BasePanel):
    """单词卡面板：词库选择、学习进度、续背与词库管理。"""

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
            ("basic", "高频核心词"),
            ("kaoyan", "考研核心词"),
            ("custom", "自定义词库"),
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

        # 自定义词库卡
        custom = QFrame()
        custom.setObjectName("Card")
        cl = QVBoxLayout(custom)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)
        hint = QLabel("自定义词库格式：单词 | 音标 | 释义　　或　　单词 释义\n以 # 开头的行会跳过")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        cl.addWidget(hint)
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        b1 = QPushButton("从文件导入...")
        b2 = QPushButton("粘贴文本...")
        b1.clicked.connect(self.on_import)
        b2.clicked.connect(self.on_paste)
        for b in (b1, b2):
            b.setMinimumHeight(36)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row2.addWidget(b)
        cl.addLayout(row2)
        root.addWidget(custom)
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
        if deck.deck_id == "custom":
            self.deck_hint.setText(f"当前使用自定义词库（{len(deck.words)} 词）")
        elif deck.deck_id == "kaoyan":
            self.deck_hint.setText("考研核心词 261 个，按字母序排列，进度独立保存")
        else:
            self.deck_hint.setText("高频核心词 46 个，进度独立保存")

    def on_deck(self, deck_id):
        if deck_id == "custom" and not self.bar.deck.custom_words:
            styled_message(self, "Niumer", "还没有自定义词库，请先从文件或粘贴导入。")
            self.refresh()
            return
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

    def on_import(self):
        self.bar.import_words()
        self.refresh()

    def on_paste(self):
        self.bar.paste_words()
        self.refresh()

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
        self.font_size = int(settings.value("novel_font", 11))
        self.speed = float(settings.value("novel_speed", 14))

    # ---- 排版 ----
    def set_viewport(self, width, height):
        """正文区域尺寸变化时重排（只为宽度重排，高度只影响可视行数）。"""
        width = max(40.0, float(width))
        self.view_h = max(12.0, float(height))
        if abs(width - self.view_w) > 0.5:
            pos = self.char_pos() if self.book else 0
            self.view_w = width
            self.doc.setTextWidth(width)
            if self.book:
                self.offset = min(self._y_for_pos(pos), self.max_offset())

    def apply_font(self):
        font = QFont("Microsoft YaHei")
        font.setPixelSize(max(9, int(self.font_size)))
        self.doc.setDefaultFont(font)
        cursor = QTextCursor(self.doc)
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(100.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        fmt.setTopMargin(0)
        fmt.setBottomMargin(0)
        fmt.setLeftMargin(0)
        fmt.setRightMargin(0)
        cursor.mergeBlockFormat(fmt)
        cursor.clearSelection()

    def load(self, book, text=None):
        if not os.path.exists(book["path"]):
            return False
        try:
            if text is None:
                text, _ = read_text_auto(book["path"])
        except OSError:
            return False
        self.book = book
        self.doc.setPlainText(text)
        self.doc.setTextWidth(self.view_w)
        self.apply_font()
        self.offset = min(self._y_for_pos(int(book.get("pos", 0) or 0)), self.max_offset())
        return True

    def unload(self):
        self.book = None
        self.offset = 0.0
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

    def save(self):
        if not self.book:
            return
        pos = self.char_pos()
        self.book["pos"] = pos
        self.shelf.set_pos(self.book["path"], pos, self.doc.characterCount() - 1)

    def set_font_size(self, size):
        size = max(9, min(20, int(size)))
        if size == self.font_size:
            return
        pos = self.char_pos() if self.book else 0
        self.font_size = size
        self.settings.setValue("novel_font", size)
        if self.book:
            self.apply_font()
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
    """摸鱼阅读面板：导入 txt、书架管理、字号与滚动速度。"""

    def __init__(self, bar):
        super().__init__(bar)
        self.shelf = bar.shelf
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        head = QLabel("导入 txt 小说，文字直接在任务栏小条里滚动，鼠标移开就停")
        head.setObjectName("Title")
        head.setWordWrap(True)
        root.addWidget(head)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(10)

        self.list = QListWidget()
        self.list.setMinimumHeight(190)
        self.list.setItemDelegate(_BookDelegate(self.list))
        self.list.itemDoubleClicked.connect(lambda *_: self.read_selected())
        cl.addWidget(self.list)

        row = QHBoxLayout()
        row.setSpacing(8)
        import_btn = QPushButton("导入 txt")
        import_btn.setObjectName("Primary")
        read_btn = QPushButton("读这本")
        del_btn = QPushButton("移出书架")
        reset_btn = QPushButton("从头读")
        for btn in (import_btn, read_btn, del_btn, reset_btn):
            btn.setMinimumHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.clicked.connect(self.import_txt)
        read_btn.clicked.connect(self.read_selected)
        del_btn.clicked.connect(self.remove_selected)
        reset_btn.clicked.connect(self.reset_selected)
        row.addWidget(import_btn)
        row.addWidget(read_btn)
        row.addWidget(del_btn)
        row.addWidget(reset_btn)
        row.addStretch(1)
        cl.addLayout(row)
        root.addWidget(card)

        feel = QGroupBox("阅读手感")
        feel.setMinimumHeight(118)
        form = QFormLayout(feel)
        form.setSpacing(8)
        self.font_spin = FlatSpin()
        self.font_spin.setRange(10, 20)
        self.font_spin.setSuffix(" px")
        self.font_spin.setValue(int(self.bar.settings.value("novel_font", 11)))
        self.speed_spin = FlatSpin()
        self.speed_spin.setRange(NOVEL_SPEED_MIN, NOVEL_SPEED_MAX)
        self.speed_spin.setSingleStep(2)
        self.speed_spin.setSuffix(" px/秒")
        self.speed_spin.setValue(int(float(self.bar.settings.value("novel_speed", 14))))
        for sp in (self.font_spin, self.speed_spin):
            sp.setMinimumHeight(30)
            sp.setMaximumWidth(150)  # 一行放个小数字就够，别铺满整张卡
        self.font_spin.valueChanged.connect(self.on_font_changed)
        self.speed_spin.valueChanged.connect(self.on_speed_changed)
        form.addRow("正文字号：", self.font_spin)
        form.addRow("滚动速度：", self.speed_spin)
        root.addWidget(feel)

        note = QLabel(
            "小条里一次显示两行左右，鼠标停在条上才开始爬，移开立刻停。"
            "阅读位置按字序记录，重启接着读。"
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        root.addWidget(note)

        # 伪装：鼠标离开时这一页显示天气
        mask = QGroupBox("鼠标移开时（伪装成天气）")
        mask.setMinimumHeight(132)
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
        root.addWidget(mask)
        root.addStretch(1)

        self.bar.weather.ready.connect(self.on_weather_signal)
        self.bar.weather.failed.connect(self.on_weather_signal)
        self.refresh_weather_state()

        self.refresh_list()

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
        self.list.clear()
        current = self.shelf.current
        if not self.shelf.books:
            empty = QListWidgetItem("还没导入小说 —— 点下面「导入 txt」")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setForeground(QColor(ui_palette()["faint"]))
            empty.setSizeHint(QSize(0, 34))
            self.list.addItem(empty)
            return
        for b in self.shelf.books:
            is_current = b["path"] == current
            item = QListWidgetItem(f"《{b['title']}》")
            item.setData(Qt.ItemDataRole.UserRole, b["path"])
            item.setData(_BookDelegate.PCT_ROLE, f"{NovelShelf.percent(b):.1f}%")
            item.setData(_BookDelegate.CURRENT_ROLE, is_current)
            item.setToolTip(b["path"])
            item.setSizeHint(QSize(0, 30))
            self.list.addItem(item)
        if self.list.count() and not self.shelf.current:
            self.list.setCurrentRow(0)

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
            last = self.shelf.add(path, text, len(text))
            if len(text) > 600000:
                big.append(os.path.basename(path))
        self.refresh_list()
        if last:
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == last["path"]:
                    self.list.setCurrentRow(i)
                    break
            msg = f"已加入书架：《{last['title']}》，共 {last['total']} 字。点“读这本”开始。"
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
        self.shelf.remove(path)
        self.refresh_list()
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
        self.bar.update_tip()
        self.bar.update()

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
            "摸鱼阅读三页都在这同一条里切换，不会另开窗口，也不会越变越大。")
        + img("taskbar", "位置示意：小条就挨着托盘图标，和时钟、音量排在一起。", 440)
        + h("三个入口")
        + ol([
            "左键按住小条左右拖 —— 三页之间切换，松手自动吸附",
            "右键小条 —— 菜单：切页、设置中心、使用帮助、隐藏窗口、退出",
            f"隐藏之后按 {k('Ctrl+Q')}，或点托盘图标，就能叫回来",
        ])
        + note("第一次用，先右键 → 设置中心 → 工资条，把月薪填上；其余默认设置就能跑起来。")
        + h("三页分别是什么")
        + table([
            ("第一页", "工资条：每秒都在涨的“工钱”，一眼看到今天赚了多少"),
            ("第二页", "单词卡：一个单词 + 音标释义，轻点后按空格可以默写"),
            ("第三页", "摸鱼阅读：小说正文在条里慢慢滚，鼠标移开自动变天气"),
        ])
    )

    salary = (
        h("它在算什么")
        + p("把月薪折算到秒：月薪 ÷ 22 个工作日 ÷ 8 小时 ÷ 3600 秒。屏幕上那个数字每秒都在涨，"
            "涨的就是你此刻“已经赚到”的钱。")
        + img("salary", "第一页：左边绿点表示正在计时，右边是每秒进账速率。")
        + h("怎么设置")
        + ol([
            "右键 → 设置中心 → 工资条",
            "填月薪（也可以直接点 ¥5000 这类预设按钮），点「保存并关闭」",
            "参数一改，累计金额自动接着算，不会清零",
        ])
        + h("两个常用操作")
        + ol([
            "去开会、午休：点「暂停计时」，绿点变灰，数字停住；回来点「继续计时」",
            "想只看每秒：点「显示每秒」，大数字变成速率，右边显示月薪；再点一次切回累计",
        ])
        + note("「重置累计金额」只把今天累计的数字清零，不影响月薪设置。")
    )

    word = (
        h("平时看什么")
        + p("第一行是单词，第二行是音标和释义，右下角浅灰的 12/261 是学习进度。"
            "默认 46 个高频词，可以换成 261 个考研词，也能导入自己的词表。")
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
            ("高频核心词", "46 个常见词，默认"),
            ("考研核心词", "261 个考研高频词，带音标释义"),
            ("自定义词库", "从 txt 导入或直接粘贴，一行一个词"),
        ])
        + note("三个词库的学习进度分别保存，切换不会互相覆盖。")
    )

    novel = (
        h("导入小说")
        + ol([
            "右键 → 设置中心 → 摸鱼阅读",
            "点「导入 txt」，可以一次选多个文件；单个文件 8MB 以内（约 400 万字）",
            "书架里双击书名，或选中后点「读这本」",
        ])
        + h("怎么读")
        + p("把它拖到第三页，正文就在条里慢慢往上爬。鼠标停在条上才滚，一移开立刻停 —— "
            "有人走过来时手一挪，看着就是一条普通的桌面小工具。")
        + img("novel", "第三页：两行正文，底部细线是全书进度。")
        + ol([
            "轻点小条：暂停 / 继续滚动",
            "滚轮停在条上：手动往下翻一点",
            "底部细线：整本书读到哪了；右边小点：当前在第几页",
        ])
        + note("阅读位置按字序保存，换字号、重启、切到别的书再切回来，都能接着上次的地方读。"
               "字号 10～20px、速度 4～80px/秒，在设置里调。")
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
        h("四个面板")
        + p("右键小条 → 设置中心。左边四张卡选功能，右边改参数，底部两个按钮。")
        + img("settings", "设置中心：左侧选功能，右侧改参数，右下角「保存并关闭」。", 700)
        + table([
            ("工资条", "月薪、暂停/继续、显示累计或每秒、重置累计"),
            ("单词卡", "换词库、看学习进度、续背/跳到未掌握/重置、导入自定义词库"),
            ("健康提醒", "三类提醒的开关、间隔、文案，以及提醒时段"),
            ("摸鱼阅读", "书架、导入 txt、正文字号、滚动速度、天气伪装"),
        ])
        + note("改完一定要点右下角「保存并关闭」。直接点窗口右上角的 × 关闭不会保存。")
        + note("设置中心左下角还有「使用帮助」，随时能翻到这里。")
    )

    keypage = (
        h("鼠标")
        + table([
            (k("左键拖动"), "切换三页，松手自动吸附到最近一页"),
            (k("左键轻点"), "单词页：取得键盘焦点；小说页：暂停 / 继续滚动"),
            (k("右键"), "弹出菜单"),
            (k("滚轮"), "小说页：手动滚动正文"),
        ])
        + h("键盘")
        + table([
            (k("空格"), "单词页：开始默写；判定完再按一次进入下一个词"),
            (k("Backspace"), "默写时删掉一个字母"),
            (k("Esc"), "退出默写"),
            (k("Ctrl+Q"), "全局热键：隐藏 / 显示小条"),
        ])
        + note("Ctrl+Q 如果被别的软件占了同一个热键，会静默失效；"
               "用右键菜单里的「隐藏窗口 / 显示窗口」一样管用。")
        + h("托盘图标")
        + p("右键托盘图标同样是那个菜单；左键点一下，隐藏的小条会重新出现。"
            "鼠标悬停在图标上能看到当前状态：累计金额、单词进度或阅读进度，以及下次提醒还有多久。")
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
            "exe 约 25MB，常驻内存六七十兆；平时每秒刷一次数字，小说滚动时才跑 33ms 一帧。")
    )

    pages = (
        ("30 秒上手", quick),
        ("工资条", salary),
        ("单词卡", word),
        ("摸鱼阅读", novel),
        ("天气伪装", weather),
        ("健康提醒", remind),
        ("设置中心", settings),
        ("快捷键与手势", keypage),
        ("数据与迁移", data),
        ("常见问题", faq),
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


class SettingsCenter(QDialog):
    """统一设置中心：左侧图标导航，右侧配置面板。

    风格参考 Linear / Raycast：左侧导航紧凑、选中态用浅底+细竖线指示；
    右侧面板是一个大卡片，里面分组。
    """

    CARDS = (
        ("salary", "¥", "工资条", "月薪与每秒进账"),
        ("words", "A", "单词卡", "词库与默写"),
        ("remind", "!", "健康提醒", "喝水 · 活动 · 护眼"),
        ("novel", "书", "摸鱼阅读", "TXT 自动滚"),
        ("appearance", "◐", "外观", "主题 · 深浅色"),
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
            QLabel#NavBadge {{ font-size:13px; font-weight:700; color:{p['accent']};
                background:{p['accent_soft']}; border-radius:8px; }}
            QLabel#NavBadgeChecked {{ background:{p['accent']}; color:#ffffff; border-radius:8px; font-weight:700; font-size:13px; }}
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
        for key, icon, title_text, sub in self.CARDS:
            btn = QPushButton()
            btn.setObjectName("NavCard")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            bl = QHBoxLayout(btn)
            bl.setContentsMargins(8, 4, 8, 4)
            bl.setSpacing(10)
            badge = QLabel(icon)
            badge.setObjectName("NavBadge")
            badge.setFixedSize(28, 28)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        # 选中态：badge 实底
        for k, badge in self.nav_badges.items():
            if k == key:
                badge.setObjectName("NavBadgeChecked")
            else:
                badge.setObjectName("NavBadge")
            # 触发样式刷新
            badge.style().unpolish(badge)
            badge.style().polish(badge)
        idx = list(self.panels.keys()).index(key)
        self.stack.setCurrentIndex(idx)

    def accept(self):
        for panel in self.panels.values():
            panel.apply()
        super().accept()


class SalaryBar(QWidget):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = QSettings("Niumer", "Niumer")
        self.monthly = float(self.settings.value("monthly_salary", 3000.0))
        self.show_total = True
        self.paused = False
        self.earned_base = 0.0
        self.elapsed = QElapsedTimer()
        self.elapsed.start()
        self.phase = 0.0
        self.shown_earned = self.earned
        self.shown_rate = self.rate

        self.deck = WordDeck(self.settings)
        self.shelf = NovelShelf(self.settings)
        self.novel = NovelView(self.settings, self.shelf)
        self.novel_paused = False
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
        title = menu.addAction("Niumer · 致敬打工人")
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
    def rate(self):
        return per_second(self.monthly)

    @property
    def earned(self):
        seconds = 0.0 if self.paused else self.elapsed.elapsed() / 1000.0
        return self.earned_base + seconds * self.rate

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
            head = "摸鱼阅读 · 未导入" if book is None else f"摸鱼阅读 {self.novel.percent():.1f}%"
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

    @staticmethod
    def draw_page_dots(bar, painter, c):
        """右侧页码指示：当前页是一条小横杠，其余是小圆点，一眼能看出在第几页。"""
        h = bar.height()
        w = bar.width()
        current = int(round(bar.view))
        cy = h / 2
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(PAGE_COUNT):
            x = (w - 11) - 7 * (PAGE_COUNT - 1 - i)
            if i == current:
                painter.setBrush(c["green"])
                painter.drawRoundedRect(QRectF(x - 3.2, cy - 1.3, 6.4, 2.6), 1.3, 1.3)
            else:
                painter.setBrush(c["faint"])
                painter.drawEllipse(QPointF(x, cy), 1.7, 1.7)

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
        elif event.button() == Qt.MouseButton.RightButton:
            self.update_menu()
            self.menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self.dragging:
            dx = event.position().x() - self.drag_x
            self.drag_distance = max(self.drag_distance, abs(dx))
            if self.drag_distance > 3:
                target = self.drag_page - dx / self.width()
                self.view = max(0.0, min(float(PAGE_COUNT - 1), target))
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.dragging:
            self.dragging = False
            dx = event.position().x() - self.drag_x
            if self.drag_distance > 22 and abs(dx) > 18:
                target = self.drag_page + (-1 if dx > 0 else 1)
            else:
                target = self.drag_page
                # 轻点单词页：取得焦点，可直接按空格开始默写
                if target == PAGE_WORD and self.spell_result is None:
                    self.setFocus()
                elif target == PAGE_NOVEL:
                    # 轻点小说页：暂停/继续；没书就去选文件
                    if self.shelf.current_book() is None:
                        self.open_settings_center("novel")
                        return
                    self.load_novel_book()
                    self.novel_paused = not self.novel_paused
                    self.update_tip()
                    self.update()
                    return
            self.animate_view(target)

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

    # ---- 单词默写 ----
    def keyPressEvent(self, event):
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

    def open_settings_center(self, panel_key="salary"):
        """统一设置中心：工资 / 单词 / 健康提醒 / 摸鱼阅读。"""
        dialog = SettingsCenter(self, self)
        dialog.show_panel(panel_key)
        dialog.exec()
        self.load_novel_book()
        self.update_tip()
        self.update()

    def open_help(self):
        """详细使用说明：替代原来鼠标一停就弹的那块提示。"""
        HelpDialog(self).exec()

    def import_words(self):
        """从 txt 文件导入词库。支持 UTF-8 / GBK 编码。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择词库文件", "", "文本文件 (*.txt);;所有文件 (*)"
        )
        if not path:
            return
        text = ""
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with open(path, "r", encoding=enc) as f:
                    text = f.read()
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                styled_message(self, "Niumer", f"读取文件失败：{e}", QMessageBox.Icon.Warning)
                return
        words = self.deck.parse(text)
        self._apply_words(words, f"从文件导入 {len(words)} 个单词", "文件里没读到有效单词，请检查格式。")

    def paste_words(self):
        """直接粘贴词库文本导入。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("粘贴词库")
        dlg.setMinimumSize(460, 360)
        apply_dialog_theme(dlg)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)
        head = QLabel("每行一个词，两种写法可混用")
        head.setObjectName("Title")
        layout.addWidget(head)
        hint = QLabel("单词 | 音标 | 释义　　或　　单词 释义\n以 # 开头的行会跳过")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        edit = QPlainTextEdit()
        edit.setPlaceholderText("abandon | /əˈbændən/ | v. 放弃；抛弃\nbenefit 益处；受益")
        edit.setPlainText("")
        layout.addWidget(edit)
        buttons = QDialogButtonBox()
        ok = buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        ok.setObjectName("Primary")
        ok.setText("导入")
        cancel.setText("取消")
        ok.setMinimumHeight(34)
        cancel.setMinimumHeight(34)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = edit.toPlainText().strip()
        if not text:
            return
        words = self.deck.parse(text)
        self._apply_words(words, f"已导入 {len(words)} 个单词", "没识别到有效单词，请检查格式。")

    def _apply_words(self, words, success_msg, fail_msg):
        if not words:
            styled_message(self, "Niumer", fail_msg)
            return
        self.deck.replace(words)
        self._after_words_changed(success_msg)

    def _after_words_changed(self, msg):
        # 词库变了，复位默写状态
        self.reset_spelling_state()
        self.goto_page(PAGE_WORD)
        self.update_tip()
        self.update()
        styled_message(self, "Niumer · 词库", msg)

    def toggle_view(self):
        self.show_total = not self.show_total
        self.update()

    def toggle_pause(self):
        if self.paused:
            self.elapsed.restart()
            self.paused = False
        else:
            self.earned_base = self.earned
            self.paused = True
        self.shown_earned = self.earned
        self.update_tip()

    def reset_earned(self):
        self.earned_base = 0.0
        self.elapsed.restart()
        self.shown_earned = 0.0
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


def main():
    set_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Niumer")
    # 全局窗口图标：标题栏左上角的 logo。QApplication 级别设置后，
    # 所有后续创建的对话框/窗口都会自动继承，不用逐个 setWindowIcon。
    app.setWindowIcon(make_tray_icon())
    if not acquire_single_instance():
        styled_message(
            None, "Niumer",
            "已经在运行了 —— 看任务栏右下角那条，不用再开一个。",
        )
        return
    bar = SalaryBar(app)  # noqa: F841
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
