"""윈도우 실행 파일 규칙(CLAUDE.md 11절) — 배포 zip 을 만들 때만 보던 것을 푸시마다 본다.

한글 윈도우 cmd 는 CP949 · CRLF 배치 파일만 제대로 읽는다. UTF-8 + chcp 65001 에서 'echo.' 이 'cho.' 로 잘린 적이 있고,
줄바꿈이 LF 뿐이면 cmd 가 줄을 이어 붙여 엉뚱한 명령을 돌린다. setup.ps1 은 반대로 UTF-8 BOM 이어야 PowerShell 5.1 이 한글을 읽는다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _windows_scripts() -> list[Path]:
    return sorted(list(ROOT.glob("*.bat")) + list(ROOT.glob("*.vbs")))


def test_batch_files_are_cp949_crlf_without_chcp_or_em_dash():
    files = _windows_scripts()
    assert files, "실행 파일이 없습니다"
    for path in files:
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name}: BOM 이 있으면 cmd 가 첫 줄을 못 읽습니다"
        text = raw.decode("cp949")                          # CP949 가 아니면 여기서 실패
        assert "—" not in text, f"{path.name}: 줄표(—)는 CP949 변환을 끊습니다 — 하이픈을 쓰세요"
        assert not re.search(rb"(?<!\r)\n", raw), f"{path.name}: 줄바꿈이 CRLF 가 아닌 줄이 있습니다"
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip().lower()
            if stripped.startswith(("rem", "::", "'")):
                continue
            assert not re.match(r"@?chcp\b", stripped), f"{path.name} {number}번 줄: chcp 를 쓰지 않습니다"


def test_setup_ps1_is_utf8_bom_crlf_and_follows_the_update_branch():
    raw = (ROOT / "setup.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "setup.ps1 은 UTF-8 BOM 이어야 PowerShell 5.1 이 한글을 읽습니다"
    text = raw[3:].decode("utf-8")
    assert not re.search(r"(?<!\r)\n", text), "setup.ps1 줄바꿈은 CRLF"
    from claim_downloader import updater
    assert f"$Branch = '{updater.BRANCH}'" in text or f'$Branch = "{updater.BRANCH}"' in text
