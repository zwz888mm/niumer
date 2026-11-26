# -*- mode: python ; coding: utf-8 -*-
"""onedir 版：给安装包用。

和 Niumer.spec（单文件绿色版）的区别：
- onefile 每次启动要把 28MB 解压到临时目录，慢；
- onedir 由安装程序把文件释放到程序目录，启动直接用，快。
两边共用同一套精简规则：剔除软件 OpenGL 和 Qt 翻译文件，
但保留 ssl/libssl/libcrypto —— 天气走 HTTPS，删了就废。
"""
import os

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('Niumer-head.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

_DROP_BINARIES = {"opengl32sw.dll"}
a.binaries = [b for b in a.binaries
              if os.path.basename(b[0]).lower() not in _DROP_BINARIES]
a.datas = [d for d in a.datas
           if "\\translations\\" not in d[0] and "/translations/" not in d[0]]

exe = EXE(
    pyz,
    a.scripts,
    [],                      # onedir：依赖不塞进 exe
    exclude_binaries=True,
    name='Niumer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['logo.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Niumer',
)
