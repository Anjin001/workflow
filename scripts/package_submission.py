"""将提交所需源码与文档打包；排除密钥、依赖环境和运行记录。"""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = {
    "main.py",
    "README.md",
    "Design.md",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    "start.py",
    "start.bat",
}
SOURCE_DIRS = {"workflow", "examples", "tests", "docs", "scripts", "web"}
SUFFIXES = {".py", ".md", ".json", ".txt", ".toml", ".html", ".css", ".js", ".svg"}


def build_archive(name: str, output: Path) -> Path:
    if not name.strip() or any(char in name for char in '/\\:*?"<>|') or name in {".", ".."}:
        raise ValueError("压缩包名称必须是合法的单个文件名，不能包含路径")
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / f"{name}.zip"
    files = [ROOT / name for name in sorted(ROOT_FILES)]
    for folder in sorted(SOURCE_DIRS):
        files.extend(
            path
            for path in (ROOT / folder).rglob("*")
            if path.is_file()
            and path.suffix in SUFFIXES
            and not any(
                part.startswith(".") or part == "__pycache__"
                for part in path.relative_to(ROOT).parts
            )
        )
    with ZipFile(archive_path, "x", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            archive.write(path, arcname=Path(name) / path.relative_to(ROOT))
    if archive_path.stat().st_size >= 200_000_000:
        raise ValueError("压缩包达到或超过 200 MB，不符合提交要求")
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description="制作 Homework 2 提交压缩包")
    parser.add_argument("--name", default="workflow-homework2", help="提交时改成自己的学号姓名")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        path = build_archive(args.name, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"打包失败：{exc}\n")
    print(f"压缩包：{path}（{path.stat().st_size / 1024:.1f} KB）")


if __name__ == "__main__":
    main()
