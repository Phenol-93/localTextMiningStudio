"""Create a Windows portable release zip for LocalTextMiningStudio."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path


APP_NAME = "LocalTextMiningStudio"


README_TEXT = """LocalTextMiningStudio 绿色版说明

使用方法：
1. 解压整个文件夹。
2. 双击 LocalTextMiningStudio.exe 启动程序。
3. 建议将本软件放在用户有写入权限的目录，例如桌面、文档或单独的软件目录。
4. 默认数据保存在软件目录下的 user_data 文件夹。
5. AI 功能需要用户自己的 API Key；软件包中不包含任何 API Key。

注意：
- 不需要用户安装 Python。
- 请不要只复制 exe，绿色版需要保留同目录下的依赖文件。
- 如果需要迁移数据，请一起备份 user_data、exports 和 logs 文件夹。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Create LocalTextMiningStudio Windows release zip.")
    parser.add_argument("--version", default="", help="Release version. Defaults to pyproject.toml version.")
    parser.add_argument("--dist-dir", default="dist", help="Directory containing LocalTextMiningStudio.")
    parser.add_argument("--no-zip", action="store_true", help="Only write README.txt, do not create a zip.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    dist_dir = (repo_root / args.dist_dir).resolve()
    release_dir = dist_dir / APP_NAME
    version = args.version or read_version(repo_root / "pyproject.toml")

    if not release_dir.is_dir():
        raise SystemExit(f"Release directory not found: {release_dir}")

    write_release_readme(release_dir)
    if args.no_zip:
        print(f"README.txt written to {release_dir}")
        return 0

    zip_path = dist_dir / f"{APP_NAME}_v{version}_windows.zip"
    if zip_path.exists():
        zip_path.unlink()
    make_zip(release_dir, zip_path, dist_dir)
    print(f"Release zip created: {zip_path}")
    return 0


def read_version(pyproject_path: Path) -> str:
    text = pyproject_path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Cannot find project version in {pyproject_path}")
    return match.group(1)


def write_release_readme(release_dir: Path) -> Path:
    path = release_dir / "README.txt"
    path.write_text(README_TEXT, encoding="utf-8-sig")
    return path


def make_zip(release_dir: Path, zip_path: Path, dist_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(release_dir.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(dist_dir))
    return zip_path


if __name__ == "__main__":
    raise SystemExit(main())
