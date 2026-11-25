# -*- mode: python ; coding: utf-8 -*-

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

# 剔除用不到的 Qt 组件，exe 体积和解压耗时都能降下来：
# - opengl32sw.dll：软件 OpenGL 渲染器，19.7MB，控件界面走光栅引擎用不到
# - translations：Qt 自带翻译文件，界面文案全是自己写的中文
_DROP_BINARIES = {"opengl32sw.dll"}
a.binaries = [b for b in a.binaries
              if os.path.basename(b[0]).lower() not in _DROP_BINARIES]
a.datas = [d for d in a.datas
           if "\\translations\\" not in d[0] and "/translations/" not in d[0]]

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Niumer',
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
    version='version_info.txt',
    icon=['logo.ico'],
)
