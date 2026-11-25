"""重新打包 Niumer 为单文件 exe（精简版，约 27MB，含 HTTPS 所需 ssl 库）。

打完 exe 后，如果本机装了 Inno Setup，会顺手用 Niumer.iss 生成安装包
dist/Niumer-Setup-1.0.0.exe；没装就跳过，只留 exe。

用 Niumer.spec 精确剔除用不到的 Qt 组件：
- opengl32sw.dll（软件 OpenGL 渲染，19.7MB）
- 全部 Qt 翻译文件（~3MB）
- 多余图片格式插件、Svg/Network 模块（~4MB）
- 注意：天气功能走 HTTPS，ssl/libssl/libcrypto 必须保留，不要再加回 excludes
"""
import shutil
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
    str(root / "Niumer.spec"),
]
subprocess.run(cmd, cwd=root, check=True)
print("打包完成：dist/Niumer.exe")

# 有 Inno Setup 就继续做安装包
iscc = shutil.which("ISCC")
if not iscc:
    for candidate in (
        Path.home() / "AppData/Local/Programs/Inno Setup 6/ISCC.exe",
        Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
        Path("C:/Program Files/Inno Setup 6/ISCC.exe"),
    ):
        if candidate.exists():
            iscc = str(candidate)
            break
if iscc:
    subprocess.run([iscc, "/Q", str(root / "Niumer.iss")], cwd=root, check=True)
    print("安装包完成：dist/Niumer-Setup-1.0.0.exe")
else:
    print("没找到 Inno Setup（ISCC.exe），跳过安装包。")

