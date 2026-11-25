"""重新打包「窝囊费」为单文件 exe（精简版，约 25MB，含 HTTPS 所需 ssl 库）。

用 窝囊费-slim2.spec 精确剔除用不到的 Qt 组件：
- opengl32sw.dll（软件 OpenGL 渲染，7.6MB）
- 全部 Qt 翻译文件（~3MB）
- 多余图片格式插件、Svg/Network 模块（~4MB）
- 注意：天气功能走 HTTPS，ssl/libssl/libcrypto 必须保留，不要再加回 excludes
"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
cmd = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--distpath",
    str(root / "dist"),
    str(root / "窝囊费-slim2.spec"),
]
subprocess.run(cmd, cwd=root, check=True)
print("打包完成：dist/窝囊费.exe")
