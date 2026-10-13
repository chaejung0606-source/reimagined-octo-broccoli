"""일반청구 (claims/) — 브라우저·AI 없이 계약·규칙·채우기 순서·안전을 본다.

ERP 프레임은 가짜(evaluate 가 JS 상수를 알아보고 흉내 낸다). 실제 화면은 모의 페이지(tools 밖)와
담당자 PC 에서 확인한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from claim_downloader import settings
from claim_downloader.claims import extract, form, process, record, rules, schema
from claim_downloader.minutes.backends.base import BackendError, MinutesBackend
from claim_downloader.minutes import errors

CLAIMS = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "claims"


def sample(**overrides) -> dict:
    data = {
        "summary": "09_2026년 사업단 정수기 임차료(9월)", "expCategory": "그 밖의 사업운영 경비", "expDetail": "임차료",
        "evidence": "세금계산서", "expenseDate": "2026.09.30", "amount": "51,900원", "supplyAmount": 47182,
        "taxAmount": 4718, "payeeName": "코웨이(주)", "payeeBizNo": "123-45-67890", "bank": "국민은행",
        "accountNo": "123-456-789", "owner": "코웨이(주)", "settleMethod": "", "attachments": ["세금계산서.pdf"],
        "notes": "",
    }
    data.update(overrides)
    return data


# ── schema ───────────────────────────────────────────────────────────
def test_category_code_accepts_any_spelling():
    assert schema.category_code("그 밖의 사업운영 경비") == "09"
    assert schema.category_code("기타운영경비") == "09"
    assert schema.category_code("09") == "09"
    assert schema.category_code("교육연구프로그램개발운영비") == "03"
    assert schema.category_code("지역연계협업지원비") == "06"
    assert schema.category_code("") == "" and schema.category_code("모르는비목") == ""
    assert schema.category_name("09") == "기타운영경비"
    assert schema.category_name("이상한") == "이상한"       # 사람이 고치게 그대로


def test_normalize_coerces_amounts_dates_and_options():
    data = schema.normalize(sample())
    assert data["amount"] == 51900 and data["supplyAmount"] == 47182 and data["taxAmount"] == 4718
    assert data["expenseDate"] == "2026-09-30"
    assert data["expCategory"] == "기타운영경비"
    assert data["settleMethod"] == "계좌이체"
    assert data["attachments"] == ["세금계산서.pdf"]
    assert set(data) == set(schema.KEYS)
    assert schema.normalize({"evidence": "전자세금계산서", "expenseDate": "20261013"})["evidence"] == "세금계산서"
    assert schema.normalize({"amount": None})["amount"] is None


def test_problems_flag_missing_and_inconsistent_values():
    assert schema.problems(schema.normalize(sample())) == []
    found = schema.problems(schema.normalize(sample(summary="", amount="", accountNo="")))
    assert "적요 없음" in found and "청구액 없음" in found and "계좌번호 없음 (ERP 에서 직접 넣어야 함)" in found
    found = schema.problems(schema.normalize(sample(supplyAmount=1, taxAmount=1)))
    assert any("≠ 청구액" in f for f in found)
    found = schema.problems(schema.normalize(sample(expenseDate="9월말", evidence="영수증")))
    assert any("형식이 YYYY-MM-DD" in f for f in found) and any("증빙구분" in f for f in found)


def test_summary_lines_are_readable():
    lines = schema.summary_lines(schema.normalize(sample(notes="금액 상이")))
    assert lines[0] == "적요: 09_2026년 사업단 정수기 임차료(9월)"
    assert "청구액: 51,900원" in lines[3] and lines[-1] == "확인: 금액 상이"


# ── rules · record ───────────────────────────────────────────────────
def test_rules_files_and_user_edits(isolated_home):
    assert rules.load_rules() == rules.RULES_DEFAULT
    path = settings.claims_rules_path()
    assert path.parent == isolated_home and settings.claims_rules_base_path().exists()
    path.write_text("# 메모\n- 내 규칙\n", encoding="utf-8")
    assert rules.load_rules() == "- 내 규칙"
    assert "NN_내용" in rules.RULES_DEFAULT and "추측 금지" in rules.RULES_DEFAULT


def test_record_remembers_filled_folders(isolated_home, tmp_path):
    folder = tmp_path / "지출1"
    assert record.previous(folder) is None
    record.remember(folder, {"amount": 51900, "summary": "09_정수기"})
    before = record.previous(str(folder))
    assert before["amount"] == 51900 and before["summary"] == "09_정수기" and before["when"]
    assert settings.claim_record_path().parent == isolated_home


# ── extract ──────────────────────────────────────────────────────────
def test_prompt_names_folder_json_and_rules(tmp_path):
    prompt = extract.build_prompt(str(tmp_path), str(tmp_path / "claim.json"), "규칙 ABC")
    assert str(tmp_path) in prompt and "claim.json" in prompt and prompt.endswith("[규칙]\n규칙 ABC")
    for key in schema.KEYS:
        assert f'"{key}"' in prompt, key
    assert "기타운영경비" in prompt and "세금계산서" in prompt
    assert "폴더 안의 파일을 고치거나 지우지 마세요" in prompt


def test_extractor_registry_and_missing_claude(monkeypatch):
    assert extract.keys() == ["claude-cli"]
    assert isinstance(extract.get("없는키"), extract.ClaudeCliExtractor)
    # available() 은 claude_cli.check_claude 가, generate() 는 extract 가 각자 find_claude 를 본다
    monkeypatch.setattr(extract, "find_claude", lambda: "")
    monkeypatch.setattr(extract.claude_cli_module, "find_claude", lambda: "")
    backend = extract.ClaudeCliExtractor(model="")
    ok, note = backend.available()
    assert not ok and "claude 명령을 찾을 수 없습니다" in note
    with pytest.raises(BackendError):
        backend.generate(Path("."), "r")
    source = (CLAIMS / "extract.py").read_text(encoding="utf-8")
    assert '"Read,Glob,Grep,Write,Edit,Bash,PowerShell"' in source


class FakeExtractor:
    key = "fake"
    label = "시험용"

    def __init__(self, fail_with=None):
        self.calls = []
        self._fail = list(fail_with or [])

    def available(self):
        return True, "시험용"

    def generate(self, folder, rules_text):
        self.calls.append((Path(folder), rules_text))
        if self._fail:
            error = self._fail.pop(0)
            if error is not None:
                raise error
        return sample()


def _folders(tmp_path, n):
    out = []
    for i in range(n):
        d = tmp_path / f"지출{i + 1}"
        d.mkdir()
        (d / "세금계산서.pdf").write_bytes(b"%PDF-")
        out.append(d)
    return out


def test_process_run_with_fake_extractor(tmp_path):
    folders = _folders(tmp_path, 2)
    backend = FakeExtractor()
    assert isinstance(backend, MinutesBackend)
    events = list(process.run(folders, backend, rules="r"))
    assert [e for _, e, _ in events] == ["start", "done", "start", "done"]
    result = events[1][2]
    assert result.ok and result.data["amount"] == 51900 and result.problems == []
    assert backend.calls[0][1] == "r"


def test_process_skips_after_fatal_and_continues_after_transient(tmp_path):
    folders = _folders(tmp_path, 3)
    events = list(process.run(folders, FakeExtractor([BackendError(errors._LIMIT)]), rules="r"))
    assert [e for _, e, _ in events] == ["start", "done", "skip", "skip"]
    assert events[1][2].kind == "limit"
    events = list(process.run(folders, FakeExtractor([BackendError("네트워크 연결 오류")]), rules="r"))
    results = [p for _, e, p in events if e == "done"]
    assert [r.ok for r in results] == [False, True, True]


# ── form ─────────────────────────────────────────────────────────────
class FakeFrame:
    """evaluate 가 form.py 의 JS 상수를 알아보고 ERP 화면처럼 반응한다."""

    def __init__(self, mod_yn="N", options=None):
        self.values = {}
        self.sets = []
        self.mod_yn = mod_yn
        self.options = options or {
            "PAY_EXP_CD": ["선택", "인건비", "기타운영경비"], "DTL_EXP_CD": ["선택", "임차료"],
            "EVDI_DIV_CD": ["선택", "세금계산서", "계산서"], "SETTLE_METH_CD": ["계좌이체", "현금/지로"],
            "BNK_CD": ["해당없음", "국민은행", "신한은행"],
        }

    def evaluate(self, js, arg=None):
        if js is form.PROBE_JS:
            return True
        if js is form.STATE_JS:
            return {i: {"tag": "input", "value": self.mod_yn if i == "MOD_YN" else ("P10" if i == "PROC_TYP_CD" else "")}
                    for i in arg}
        if js is form.OPTION_COUNT_JS:
            return len(self.options.get(arg, []))
        if js is form.SET_SELECT_JS:
            element_id, wanted = arg
            hit = next((o for o in self.options.get(element_id, []) if o.replace(" ", "") == wanted.replace(" ", "")), None)
            self.sets.append((element_id, wanted))
            return {"ok": True, "now": hit} if hit else {"ok": False, "why": "보기에 없음", "options": self.options.get(element_id, [])}
        if js is form.SET_TEXT_JS:
            element_id, value = arg
            self.sets.append((element_id, value))
            return {"ok": True, "now": value}
        raise AssertionError("모르는 JS")


def test_fill_sets_fields_in_order_and_never_touches_buttons():
    frame = FakeFrame()
    logs = []
    report = form.fill(frame, schema.normalize(sample()), logs.append, dry_run=False, wait=lambda s: None)
    assert report.ok and not report.blocked
    ids = [i for i, _ in frame.sets]
    assert ids[:2] == ["PAY_EXP_CD", "DTL_EXP_CD"] and ids[-1] == "REQ_PTCL"
    assert ("REQ_AMT", "51900") in frame.sets and ("EXP_DT", "2026-09-30") in frame.sets
    assert set(ids) <= form.ALLOWED_IDS
    assert any("채우기 끝" in line for line in logs)
    assert "저장" in " ".join(report.manual) and "신청" in " ".join(report.manual)


def test_dry_run_reads_only_and_existing_claim_is_refused():
    frame = FakeFrame()
    report = form.fill(frame, schema.normalize(sample()), lambda m: None, dry_run=True)
    assert report.dry_run and frame.sets == [] and [s.label for s in report.steps][0] == "비목"
    assert report.lines()[0].startswith("미리 보기")
    frame = FakeFrame(mod_yn="Y")
    report = form.fill(frame, schema.normalize(sample()), lambda m: None, dry_run=False)
    assert report.blocked and "새 청구서 화면이 아닙니다" in report.blocked and frame.sets == [] and not report.ok


def test_unknown_option_is_reported_not_fatal():
    frame = FakeFrame()
    report = form.fill(frame, schema.normalize(sample(bank="토스뱅크")), lambda m: None, dry_run=False, wait=lambda s: None)
    bank = next(s for s in report.steps if s.label == "은행")
    assert not bank.ok and "보기에 없음" in bank.note and "국민은행" in bank.note
    assert not report.ok and any(s.label == "적요" and s.ok for s in report.steps)   # 나머지는 계속 넣는다


def test_form_module_only_fills_allowed_fields_and_never_clicks():
    text = (CLAIMS / "form.py").read_text(encoding="utf-8")
    assert ".click(" not in text and "submit" not in text.lower()
    assert "import playwright" not in text and "from playwright" not in text
    for forbidden in form.FORBIDDEN_TEXTS:
        assert forbidden in ("저장", "신청", "삭제", "초기화", "새 청구서", "일괄예금주조회", "[예금주조회]", "청구서복사")
    assert {f[1] for f in form.FIELDS} <= form.ALLOWED_IDS
    assert "RCV_CD" not in {f[1] for f in form.FIELDS}      # 입금처는 팝업 — 직접 쓰지 않는다
