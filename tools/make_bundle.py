"""배포용 zip 만들기.

    python tools/make_bundle.py [출력경로]

윈도우 탐색기에서 그냥 열리도록 두 가지를 지킨다.

  1. 최상위 폴더 이름은 영문으로 둔다.
     한글 폴더명은 압축 파일 안에서 모든 경로에 붙어, 하나라도 잘못 읽히면
     탐색기가 목록 전체를 열지 못한다.

  2. 한글 이름에는 UTF-8 플래그(0x800)를 켠다.
     리눅스 zip 명령은 이 플래그를 켜지 않아서, 윈도우가 CP949 로 읽고
     이름이 깨진다. 파이썬 zipfile 은 자동으로 켜 준다.

저장소 이력(.git)도 함께 넣는다. 그래야 압축을 푼 폴더에서 앱의
[설정 → 업데이트 적용] 이 동작한다.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOP_NAME = "expense-review"          # 압축 안 최상위 폴더 — 반드시 영문
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", "build", "dist"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
# 서류·개인정보가 실수로 섞이지 않도록 확장자 단위로 한 번 더 막는다.
NEVER_PACK = {".pdf", ".hwp", ".hwpx", ".jpg", ".jpeg"}


def collect(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts)
        if parts & SKIP_DIRS:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.suffix.lower() in NEVER_PACK:
            raise SystemExit(f"중단: 서류로 보이는 파일이 있습니다 — {path}")
        if path.name.endswith(".egg-info") or ".egg-info" in str(path):
            continue
        files.append(path)
    return files


def build(target: Path) -> Path:
    files = collect(REPO_ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            arcname = f"{TOP_NAME}/{path.relative_to(REPO_ROOT).as_posix()}"
            archive.write(path, arcname)

    # 검증 — 한글 이름에 UTF-8 플래그가 켜져 있어야 한다
    with zipfile.ZipFile(target) as archive:
        bad = [i.filename for i in archive.infolist()
               if not i.filename.isascii() and not i.flag_bits & 0x800]
        if bad:
            raise SystemExit(f"중단: UTF-8 플래그가 빠진 항목 {len(bad)}개")
        count = len(archive.infolist())

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"만들었습니다: {target}  ({count}개 파일, {size_mb:.1f} MB)")
    return target


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT.parent / "expense-review.zip"
    build(target)


if __name__ == "__main__":
    main()
