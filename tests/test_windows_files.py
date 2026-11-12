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


def test_ready_marker_version_matches_across_bat_and_vbs():
    """준비 표시(setup-claim-vN)가 .bat · .vbs 에서 모두 같은 판이어야 한다(CLAUDE.md 3절).

    의존성을 바꾸면 이 판을 올려 설치된 PC 가 재설치 때 새 의존성을 받는데, 세 참조(.bat 둘 · .vbs 하나) 중
    하나라도 안 올리면 그 PC 는 새 의존성 없이 앱을 띄우다 죽거나 판 올림이 헛돈다. 셋이 같은지 코드로 지킨다.
    """
    versions: set[str] = set()
    for path in _windows_scripts():
        text = path.read_bytes().decode("cp949")
        versions.update(re.findall(r"setup-claim-v(\d+)", text))
    assert versions, "준비 표시(setup-claim-vN)를 찾지 못했습니다"
    assert len(versions) == 1, f"준비 표시 판이 .bat · .vbs 에서 어긋납니다: {sorted(versions)} — 세 곳을 함께 올리세요"


def test_pypdf_pin_is_at_least_the_dos_fixed_version():
    """pypdf 핀 하한이 DoS CVE(CVE-2026-119203~119209)가 고쳐진 6.21.4 이상이어야 한다.

    pypdf 는 외부 PDF(청구서 · 카드 영수증 · 회의록 · 출장신청서)를 읽으므로 핀을 내리면 그 DoS 를 다시 안는다.
    """
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pins = [d for d in data["project"]["dependencies"] if d.replace(" ", "").startswith("pypdf")]
    assert len(pins) == 1, f"pyproject 의 pypdf 핀을 하나 찾지 못했습니다: {pins}"
    match = re.search(r">=\s*(\d+)\.(\d+)\.(\d+)", pins[0])
    assert match, f"pypdf 핀에 >= 하한이 없습니다: {pins[0]!r}"
    assert tuple(int(g) for g in match.groups()) >= (6, 21, 4), f"pypdf 핀이 6.21.4 미만입니다: {pins[0]!r}"
