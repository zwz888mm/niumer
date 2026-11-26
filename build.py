"""打包 Niumer：单文件绿色版 + onedir 安装版。

产物统一放在 dist/<版本号>/：
  Niumer.exe                  单文件绿色版，双击即用（约 28MB，启动要解压）
  runtime/Niumer.exe + DLL    onedir 目录版，安装包用（启动不用解压，快）
  Niumer-Setup-<版本>.exe     安装程序（装的是 onedir 版）

版本号从 main.py 的 VERSION 读取。放在版本子目录而不是覆盖 dist/Niumer.exe，
避免旧 exe 被占用时打包失败，也方便回滚。

精简规则（两个 spec 共用）：
- 剔除 opengl32sw.dll（软件 OpenGL 渲染，19.7MB）
- 剔除 Qt 翻译文件（~3MB）
- 必须保留 ssl/libssl/libcrypto —— 天气走 HTTPS，删了就废
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
main_py = (root / "main.py").read_text(encoding="utf-8-sig")
match = re.search(r'^VERSION\s*=\s*"([^"]+)"', main_py, re.MULTILINE)
if not match:
    raise SystemExit("main.py 里找不到 VERSION 定义")
version = match.group(1)
out_dir = root / "dist" / version
out_dir.mkdir(parents=True, exist_ok=True)


def run_pyinstaller(spec_name, distpath, expect):
    """expect 指向的成品已存在就跳过 —— 避免重跑时 PyInstaller 覆盖旧文件
    触发沙箱的删除保护，也省一次打包时间。"""
    if Path(expect).exists():
        print(f"已存在，跳过：{expect}")
        return
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--distpath", str(distpath), str(root / spec_name),
    ]
    subprocess.run(cmd, cwd=root, check=True)


# 1) 单文件绿色版（dist/<ver>/Niumer.exe）
run_pyinstaller("Niumer.spec", out_dir, out_dir / "Niumer.exe")
print(f"绿色版完成：dist/{version}/Niumer.exe")

# 2) onedir 版（dist/<ver>/runtime/Niumer/…），供安装包释放
runtime_dir = out_dir / "runtime"
run_pyinstaller("Niumer-dir.spec", runtime_dir, runtime_dir / "Niumer" / "Niumer.exe")
print(f"目录版完成：dist/{version}/runtime/（安装包用，启动免解压）")

# 3) 有 Inno Setup 就做安装包
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
    # 从 Niumer.iss 派生临时脚本，只改输出目录。
    # 顺手去掉重复 UTF-8 BOM —— 双 BOM 会让 ISCC 报 "Text is not inside a section"。
    iss = (root / "Niumer.iss").read_bytes()
    while iss.startswith(b"\xef\xbb\xbf\xef\xbb\xbf"):
        iss = iss[3:]
    text = iss.decode("utf-8-sig")
    text = text.replace("OutputDir=dist", f"OutputDir=dist\\{version}")
    temp_iss = root / f".Niumer-build-{version}.iss"
    temp_iss.write_text(text, encoding="utf-8-sig")
    try:
        subprocess.run([iscc, "/Q", str(temp_iss)], cwd=root, check=True)
    finally:
        temp_iss.unlink(missing_ok=True)
    print(f"安装包完成：dist/{version}/Niumer-Setup-{version}.exe")
else:
    print("没找到 Inno Setup（ISCC.exe），跳过安装包。")
