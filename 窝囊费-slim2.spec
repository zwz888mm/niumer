# -*- mode: python ; coding: utf-8 -*-
"""精简版打包配置：只保留窝囊费实际用到的 Qt 组件，砍掉 OpenGL 软件渲染、
翻译文件、多余图片插件等，单文件体积显著下降。"""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['ssl', '_ssl', 'hashlib', '_hashlib'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt6.QtSql', 'PyQt6.QtMultimedia', 'PyQt6.QtQml', 'PyQt6.QtQuick',
        'PyQt6.QtTest', 'PyQt6.QtXml', 'PyQt6.QtDBus', 'PyQt6.QtBluetooth',
        'PyQt6.QtNfc', 'PyQt6.QtPositioning', 'PyQt6.QtSerialPort',
        'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebChannel',
        'PIL', 'openpyxl', 'requests', 'dotenv', 'numpy', 'matplotlib',
    ],
    noarchive=False,
    optimize=0,
)


def _keep(entry):
    name = entry[0].replace('/', '\\').lower()
    # 软件 OpenGL 渲染后端：7.6MB，程序完全不用
    if 'opengl32sw' in name:
        return False
    # 所有 Qt 翻译文件：程序界面文字全中文硬编码
    if name.endswith('.qm'):
        return False
    # Qt6Svg：没用到 SVG 图标
    # 注意：天气要发 HTTPS 请求，libssl/libcrypto 必须留着，别再删
    if name.endswith('qt6svg.dll'):
        return False
    # 图片格式插件：只用托盘图标(QPainter 绘制)与 PNG，保留 ico 以防万一
    if 'imageformats' in name:
        return name.endswith('qico.dll')
    if 'iconengines' in name or 'generic' in name:
        return False
    # 平台插件：只要 windows
    if 'platforms' in name:
        return name.endswith('qwindows.dll')
    return True


a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if not e[0].lower().endswith('.qm')]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='窝囊费',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['logo.ico'],
)
