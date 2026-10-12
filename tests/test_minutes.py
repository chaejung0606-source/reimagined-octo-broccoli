"""회의록 생성 (minutes/) — 옛 도구에서 옮긴 로직이 그대로 도는지.

실제 회의 자료를 쓰지 않는다(참석자 실명이 들어 있다). 회의록 dict 는 코드로 만들고, 백엔드는
가짜(generate 가 고정 dict)를 끼운다. 그래야 Claude Code 없이, 비용 없이 돈다.

.hwpx 격자 검사(3-1): 참석자 칸 수가 가변이라 셀 주소·병합이 어긋나기 쉽다. 겹침이나 빈칸이
하나라도 있으면 한글이 '손상된 파일' 이라며 열지 않는다.
"""
from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from xml.dom import minidom

import pytest

from claim_downloader import settings
from claim_downloader.minutes import backends, docx, errors, hwpx, naming, process, rules, schema
from claim_downloader.minutes.backends import claude_cli
from claim_downloader.minutes.backends.base import BackendError, MinutesBackend

MINUTES = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "minutes"


def sample(count: int = 2, names: int = 2, **overrides) -> dict:
    orgs = ["강원대학교", "강원대학교", "한림대학교"]
    data = {
        "filenameBase": "2026-07-22 수 예산집행검토",
        "agenda": "2026학년도 2학기 예산 집행 검토",
        "date": "2026. 7. 22. (수) 11:00 ~ 12:00",
        "place": "공학관 301호",
        "expensePlace": "춘천닭갈비",
        "amount": "120,000원",
        "attendeeCount": count,
        "attendees": [{"org": orgs[i % 3], "name": f"참석자{i + 1}"} for i in range(names)],
        "content": ["예산 집행 현황에 대해 논의하였음. 세부 항목을 확인하였음.",
                    "향후 집행 계획에 대해서도 논의하였음. 분기별로 점검하기로 하였음."],
        "supplement": "보완사항 없음",
    }
    data.update(overrides)
    return data


def _grid(path: Path) -> tuple[int, int]:
    """section0.xml 의 표를 격자로 펼쳐 겹침·빈칸을 찾는다. (행 수, 열 수)."""
    with zipfile.ZipFile(path) as z:
        section = minidom.parseString(z.read("Contents/section0.xml"))
    tables = section.getElementsByTagName("hp:tbl")
    assert len(tables) == 1
    tbl = tables[0]
    rows = tbl.getElementsByTagName("hp:tr")
    grid: dict[tuple[int, int], int] = {}
    for tr in rows:
        for tc in tr.getElementsByTagName("hp:tc"):
            addr = tc.getElementsByTagName("hp:cellAddr")[0]
            span = tc.getElementsByTagName("hp:cellSpan")[0]
            r0, c0 = int(addr.getAttribute("rowAddr")), int(addr.getAttribute("colAddr"))
            for dr in range(int(span.getAttribute("rowSpan"))):
                for dc in range(int(span.getAttribute("colSpan"))):
                    assert (r0 + dr, c0 + dc) not in grid, f"겹침 {(r0 + dr, c0 + dc)}"
                    grid[(r0 + dr, c0 + dc)] = 1
    R, C = int(tbl.getAttribute("rowCnt")), int(tbl.getAttribute("colCnt"))
    assert len(rows) == R
    missing = [(r, c) for r in range(R) for c in range(C) if (r, c) not in grid]
    assert not missing, f"빈칸 {missing[:5]}"
    assert len(grid) == R * C
    return R, C


@pytest.mark.parametrize("count", [0, 1, 8, 10, 60, 999])
def test_hwpx_grid_is_consistent_for_any_attendee_count(tmp_path, count):
    out = tmp_path / "회의록.hwpx"
    hwpx.build_hwpx(sample(count=count, names=2), str(out))
    R, C = _grid(out)
    assert C == 3
    # 머리글 1 + 사업명~금액 6 + 참석자 머리 1 + 참석자 칸 + 회의내용 머리 1 + 본문 1
    attendee_rows = len(schema._attendee_rows(sample(count=count, names=2)))
    assert R == 10 + attendee_rows
    assert attendee_rows == max(min(count, 60), 2)      # 이름 2명은 늘 들어가고, 60 이 상한


def test_attendee_rows_fill_blank_up_to_count_without_inventing_names():
    rows = schema._attendee_rows(sample(count=8, names=2))
    assert len(rows) == 8
    assert [name for _, name in rows[:2]] == ["참석자1", "참석자2"]
    assert all(name == "" for _, name in rows[2:])
    assert all(org for org, _ in rows)                   # 빈칸도 소속은 기본값
    assert schema._attendee_rows({"attendees": [], "attendeeCount": 0}) == [("강원대학교", "")]


def test_hwpx_package_rules(tmp_path):
    out = tmp_path / "회의록.hwpx"
    hwpx.build_hwpx(sample(), str(out))
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/hwp+zip"
        header = minidom.parseString(z.read("Contents/header.xml"))
        section = z.read("Contents/section0.xml").decode("utf-8")
    # itemCnt 선언값과 실제 개수
    for tag, child in (("hh:fontfaces", "hh:fontface"), ("hh:borderFills", "hh:borderFill"),
                       ("hh:charProperties", "hh:charPr"), ("hh:paraProperties", "hh:paraPr")):
        node = header.getElementsByTagName(tag)[0]
        assert int(node.getAttribute("itemCnt")) == len(node.getElementsByTagName(child)), tag
    # section 이 참조하는 id 가 header 에 있어야 한다
    import re
    char_ids = {n.getAttribute("id") for n in header.getElementsByTagName("hh:charPr")}
    para_ids = {n.getAttribute("id") for n in header.getElementsByTagName("hh:paraPr")}
    fill_ids = {n.getAttribute("id") for n in header.getElementsByTagName("hh:borderFill")}
    assert set(re.findall(r'charPrIDRef="(\d+)"', section)) <= char_ids
    assert set(re.findall(r'paraPrIDRef="(\d+)"', section)) <= para_ids
    assert set(re.findall(r'borderFillIDRef="(\d+)"', section)) <= fill_ids


def test_hwpx_marks_supplement_at_top(tmp_path):
    out = tmp_path / "a.hwpx"
    hwpx.build_hwpx(sample(supplement="회의비 50만원 이상 집행 건은 참석 서명부가 필요하나 확인되지 않음"), str(out))
    with zipfile.ZipFile(out) as z:
        section = z.read("Contents/section0.xml").decode("utf-8")
    assert "[보완요청] 회의비 50만원" in section
    assert "<hp:t>회 의 록</hp:t>" in section


def test_docx_fallback_builds(tmp_path):
    out = tmp_path / "a.docx"
    docx.build_docx(sample(count=3, names=1), str(out))
    with zipfile.ZipFile(out) as z:
        document = z.read("word/document.xml").decode("utf-8")
        assert "word/styles.xml" in z.namelist()
    assert schema.HEADER_TITLE in document
    assert document.count("<w:vMerge/>") >= 2       # 참석자 라벨 세로 병합


def test_sanitize_is_whitelist_and_unique_uses_dash(tmp_path):
    assert naming._sanitize("2026-07-22 (수) [예산] 집행/검토?") == "2026-07-22 수 예산 집행 검토"
    assert naming._sanitize("...") == "회의록"
    first = tmp_path / "회의록.hwpx"
    assert naming._unique(str(first)) == str(first)
    first.write_bytes(b"x")
    assert naming._unique(str(first)) == str(tmp_path / "회의록-2.hwpx")
    (tmp_path / "회의록-2.hwpx").write_bytes(b"x")
    assert naming._unique(str(first)) == str(tmp_path / "회의록-3.hwpx")


def test_extract_json_is_lenient():
    assert errors._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert errors._extract_json('앞말 {"a": {"b": 2}} 뒷말') == {"a": {"b": 2}}
    assert errors._extract_json("") is None
    assert errors._extract_json("json 아님") is None


def _completed(result: str = "", stderr: str = "", rc: int = 1) -> subprocess.CompletedProcess:
    stdout = json.dumps({"result": result}) if result else ""
    return subprocess.CompletedProcess(["claude"], rc, stdout=stdout, stderr=stderr)


@pytest.mark.parametrize("text, kind, head", [
    ("Not logged in · Please run /login", "login", errors._LOGIN),
    ("You've hit your limit · resets 7:50pm (Asia/Seoul)", "limit", errors._LIMIT + " — 7:50pm (Asia/Seoul) 에 풀림"),
    ("Your credit balance is too low to access the API", "balance", errors._BALANCE),
    ("API Error: 529 overloaded_error", "", "Claude 서버가 혼잡함"),
    ("", "", "회의록 데이터가 생성되지 않음"),
])
def test_failure_reason_and_fatal_kind(text, kind, head):
    reason = errors._failure_reason(_completed(text))
    assert reason.startswith(head), reason
    assert errors._fatal_kind(reason) == kind
    assert errors.fatal_kind(BackendError(reason)) == kind
    assert errors.fatal_kind(BackendError("아무 말", kind="limit")) == "limit"


def test_failure_reason_falls_back_to_last_stderr_line():
    reason = errors._failure_reason(_completed(stderr="첫 줄\nECONNREFUSED 127.0.0.1"))
    assert reason == "네트워크 연결 오류"
    assert errors._fatal_kind(reason) == ""


class FakeBackend:
    """generate 가 고정 dict 를 돌려주는 가짜 — 규약(base.py)만 지키면 끼워진다."""
    key = "fake"
    label = "시험용"

    def __init__(self, fail_with: list[BaseException | None] | None = None):
        self.calls: list[tuple[Path, str]] = []
        self._fail = list(fail_with or [])

    def available(self):
        return True, "시험용"

    def generate(self, meeting_dir, rules):
        self.calls.append((Path(meeting_dir), rules))
        if self._fail:
            error = self._fail.pop(0)
            if error is not None:
                raise error
        return sample()


def _meeting_dirs(tmp_path, n: int) -> list[Path]:
    dirs = []
    for i in range(n):
        d = tmp_path / f"회의{i + 1}"
        d.mkdir()
        (d / "자료.txt").write_text("회의 자료", encoding="utf-8")
        dirs.append(d)
    return dirs


def test_fake_backend_runs_whole_flow_without_cli(tmp_path):
    dirs = _meeting_dirs(tmp_path, 2)
    backend = FakeBackend()
    assert isinstance(backend, MinutesBackend)
    events = list(process.run(dirs, backend, rules="규칙 본문"))
    kinds = [(i, e) for i, e, _ in events]
    assert kinds == [(0, "start"), (0, "done"), (1, "start"), (1, "done")]
    results = [p for _, e, p in events if e == "done"]
    assert all(r.ok for r in results)
    assert Path(results[0].info) == dirs[0] / "2026-07-22 수 예산집행검토.hwpx"
    assert results[0].note == "보완사항 없음"
    assert backend.calls[0][1] == "규칙 본문"           # 규칙은 백엔드로 그대로 넘어간다
    _grid(Path(results[0].info))
    # 같은 폴더를 다시 돌리면 덮어쓰지 않고 -2
    again = process.process_meeting(dirs[0], backend, "규칙 본문")
    assert Path(again.info).name == "2026-07-22 수 예산집행검토-2.hwpx"


def test_fatal_error_skips_remaining_meetings(tmp_path):
    dirs = _meeting_dirs(tmp_path, 3)
    backend = FakeBackend(fail_with=[BackendError(errors._LOGIN)])
    events = [(i, e, p) for i, e, p in process.run(dirs, backend, rules="r")]
    assert [e for _, e, _ in events] == ["start", "done", "skip", "skip"]
    first = events[1][2]
    assert not first.ok and first.kind == "login"
    assert events[2][2] == "login"
    assert len(backend.calls) == 1                       # 1건만 시도
    assert not list(tmp_path.rglob("*.hwpx"))


def test_transient_error_fails_only_that_meeting(tmp_path):
    dirs = _meeting_dirs(tmp_path, 2)
    backend = FakeBackend(fail_with=[BackendError("네트워크 연결 오류")])
    results = [p for _, e, p in process.run(dirs, backend, rules="r") if e == "done"]
    assert [r.ok for r in results] == [False, True]
    assert results[0].kind == ""
    assert len(backend.calls) == 2


def test_stop_request_leaves_remaining_untouched(tmp_path):
    dirs = _meeting_dirs(tmp_path, 3)
    backend = FakeBackend()
    seen = []
    events = []
    for event in process.run(dirs, backend, rules="r", should_stop=lambda: len(seen) >= 1):
        events.append(event)
        if event[1] == "done":
            seen.append(event)
    assert [e for _, e, _ in events] == ["start", "done", "stopped", "stopped"]
    assert len(backend.calls) == 1


def test_never_writes_inside_upload_folder(tmp_path):
    meeting = tmp_path / "09. 그 밖의사업운영경비" / "업로드" / "회의"
    meeting.mkdir(parents=True)
    backend = FakeBackend()
    result = process.process_meeting(meeting, backend, "r")
    assert not result.ok and "업로드" in result.info
    assert backend.calls == []
    assert not list(tmp_path.rglob("*.hwpx"))


def test_missing_folder_is_reported_not_raised(tmp_path):
    result = process.process_meeting(tmp_path / "없음", FakeBackend(), "r")
    assert not result.ok and result.kind == ""


def test_rules_files_live_in_data_dir_and_user_edits_are_kept(isolated_home):
    assert rules.load_rules() == rules.RULES_DEFAULT
    path, base = settings.minutes_rules_path(), settings.minutes_rules_base_path()
    assert path.parent == isolated_home and path.exists() and base.exists()
    assert path.read_text(encoding="utf-8") == base.read_text(encoding="utf-8")

    # 담당자가 고친 규칙: 주석 줄은 빼고 본문만, 기본값 파일은 그대로
    path.write_text("# 설명\n- 내 규칙 1\n\n- 내 규칙 2\n", encoding="utf-8")
    assert rules.load_rules() == "- 내 규칙 1\n\n- 내 규칙 2"
    assert base.read_text(encoding="utf-8").endswith(rules.RULES_DEFAULT + "\n")

    # 손대지 않은(기본값과 같은) 옛 규칙은 앱이 업데이트되면 최신 기본 규칙으로 갈린다
    path.write_text("옛 기본 규칙", encoding="utf-8")
    base.write_text("옛 기본 규칙", encoding="utf-8")
    assert rules.load_rules() == rules.RULES_DEFAULT
    assert path.read_text(encoding="utf-8").endswith(rules.RULES_DEFAULT + "\n")

    # BOM 이 붙어 있어도 읽는다 (메모장이 붙이기도 한다)
    path.write_bytes(b"\xef\xbb\xbf- BOM \xea\xb7\x9c\xec\xb9\x99\n")
    assert rules.load_rules() == "- BOM 규칙"


def test_rules_default_keeps_three_hard_won_lines():
    """한 번씩 잘못 건드렸다가 되돌린 규칙 셋(인수인계.md) — 문체를 '개선' 하지 않는다."""
    text = rules.RULES_DEFAULT
    assert "회의 개최 사실·일시·장소를 쓰지 않는다" in text
    assert "1시간 이상 늦은 것'이 정상이다" in text
    assert "500,000원 이상일 때만 반드시 있어야 한다" in text
    assert "이름을 지어내지 않는다" in text


def test_settings_have_minutes_fields_without_personal_defaults():
    cfg = settings.load()
    assert (cfg.claude_email, cfg.minutes_backend, cfg.minutes_model) == ("", "claude-cli", "")
    settings.update(minutes_model="claude-sonnet-5-5", claude_email="a@b.c")
    cfg = settings.load()
    assert cfg.minutes_model == "claude-sonnet-5-5" and cfg.claude_email == "a@b.c"


def test_backend_registry_falls_back_to_default_and_accepts_new_backends():
    assert backends.keys() == ["claude-cli"]
    assert backends.labels()[0][0] == backends.DEFAULT_KEY
    assert isinstance(backends.get("모르는-키"), claude_cli.ClaudeCliBackend)
    assert isinstance(backends.get(), MinutesBackend)
    try:
        backends.register(FakeBackend)
        assert isinstance(backends.get("fake"), FakeBackend)
        assert ("fake", "시험용") in backends.labels()
    finally:
        backends._REGISTRY.pop("fake", None)


def test_claude_cli_reports_missing_install(monkeypatch):
    monkeypatch.setattr(claude_cli, "find_claude", lambda: "")
    backend = claude_cli.ClaudeCliBackend(model="")
    ok, note = backend.available()
    assert not ok and "claude 명령을 찾을 수 없습니다" in note
    assert backend.last_state == "no_claude"
    with pytest.raises(BackendError):
        backend.generate(Path("."), "r")


def test_claude_cli_uses_model_setting_and_keeps_tool_list(monkeypatch, tmp_path):
    settings.update(minutes_model="claude-sonnet-5-5")
    assert claude_cli.ClaudeCliBackend().model == "claude-sonnet-5-5"
    source = (MINUTES / "backends" / "claude_cli.py").read_text(encoding="utf-8")
    # PowerShell 이 빠지면 윈도우에서 회의 1건에 22~33턴을 낭비한다 (인수인계.md 3-3)
    assert '"Read,Glob,Grep,Write,Edit,Bash,PowerShell"' in source
    assert '"--permission-mode", "acceptEdits"' in source

    prompt = claude_cli.build_prompt(str(tmp_path), str(tmp_path / "meeting.json"), "규칙 ABC")
    assert str(tmp_path) in prompt and "meeting.json" in prompt
    assert prompt.endswith("[규칙]\n규칙 ABC")
    assert "filenameBase" in prompt and "attendeeCount" in prompt


def test_claude_command_wraps_cmd_files_only():
    assert claude_cli.claude_command("/usr/bin/claude", ["-p", "x"]) == ["/usr/bin/claude", "-p", "x"]


def test_minutes_package_is_independent_of_erp_code():
    """두 기능은 독립이다 — 회의록 코드가 ERP 모듈을 읽으면 안 된다."""
    import re
    pattern = re.compile(r"^\s*(from|import)\s+\.*\s*(claim_downloader\.)?(erp|session|targets|archive|reconcile|playwright)\b", re.M)
    for path in MINUTES.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), path.name
        assert "from ..erp" not in text and "from ..session" not in text, path.name
