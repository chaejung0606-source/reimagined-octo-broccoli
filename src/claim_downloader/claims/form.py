"""ERP 일반청구 작성 화면에 값을 채우고, 사람이 입금처·첨부를 넣은 뒤 [임시저장](저장 단추)까지 — 신청은 사람.

실측(CLAUDE.md 14절, 2026-10-13)한 요소 id 만 만진다(FIELDS). 값은 JS 로 넣고 input·change 이벤트를
일으켜 화면의 처리기(비목 → 세목 불러오기 등)가 돌게 한다. 비목을 바꾸면 세목 보기가 채워질 때까지 기다린다.

이 모듈은 Playwright 를 들여오지 않는다 — session.py 가 넘겨준 프레임의 evaluate 만 쓴다. 받기 코드(erp.py)에는
값 넣기가 끝까지 없어야 하므로 값 넣기는 여기에만 둔다(tests/test_safety.py 가 본다).

담당자 결정(2026-10-13): 내역 작성 후 **임시저장까지** 앱이 하고, 그 뒤 사람이 검토해 [신청] 을 누른다.
그래서 누르는 단추는 '저장' 하나뿐이다(SAVE_TEXT · save_draft). '신청' 을 비롯한 FORBIDDEN_TEXTS 를
누르는 코드가 들어오면 안전 테스트가 깨진다. 사람이 하는 것: 입금처 돋보기 팝업 · [예금주조회] · 첨부 · [신청].
팝업 실측이 오면 pick_payee 를 채운다.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .schema import summary_lines

# 절대 누르지 않는 단추의 글자 (id 가 없어 글자로 둔다). '신청' 이 돈이 나가는 단추다.
FORBIDDEN_TEXTS = ("신청", "삭제", "초기화", "새 청구서", "일괄예금주조회", "[예금주조회]", "청구서복사")
# 앱이 누르는 유일한 단추 — 임시저장. 글자가 정확히 같은 단추가 하나일 때만 누른다(CLICK_SAVE_JS).
SAVE_TEXT = "저장"

# 채우는 순서. (데이터 키, 요소 id, 종류, 화면 이름). 비목 다음에 세목 — 세목 보기는 비목을 고른 뒤 채워진다.
FIELDS = (
    ("expCategory", "PAY_EXP_CD", "select", "비목"),
    ("expDetail", "DTL_EXP_CD", "select", "세목"),
    ("evidence", "EVDI_DIV_CD", "select", "증빙구분"),
    ("expenseDate", "EXP_DT", "text", "지출일자"),
    ("settleMethod", "SETTLE_METH_CD", "select", "결제방법"),
    ("bank", "BNK_CD", "select", "은행"),
    ("accountNo", "ACCT_NO", "text", "계좌번호"),
    ("owner", "OWNR", "text", "예금주"),
    ("amount", "REQ_AMT", "text", "청구액"),
    ("supplyAmount", "SUPPLY_AMT", "text", "공급가액"),
    ("taxAmount", "TAX_AMT", "text", "부가세"),
    ("summary", "REQ_PTCL", "text", "적요"),
)
ALLOWED_IDS = frozenset(f[1] for f in FIELDS) | {"PROC_TYP_CD", "MOD_YN", "REQ_SEQ_NO", "RCV_NM", "RCV_CD", "BAL_AMT"}
MANUAL_STEPS = (
    "입금처 — 돋보기(🔍)로 거래처를 골라 주세요 (팝업은 아직 자동화 전)",
    "[예금주조회] 를 눌러 계좌를 확인해 주세요",
    "첨부 — 세금계산서·품의서 등을 '첨부' 로 올려 주세요",
    "그다음 앱의 [임시저장] 을 누르면 앱이 ERP 의 [저장] 을 누릅니다. [신청] 은 검토 후 직접 누르세요",
)
AFTER_SAVE_STEPS = (
    "ERP 에서 임시저장된 청구서를 검토하세요",
    "[신청] 은 직접 누르세요 — 앱은 누르지 않습니다",
)

# 작성 프레임 알아보기 — 일반청구(P10) 작성 화면에만 있는 조합
PROBE_JS = """() => {
  const p = document.querySelector('#PROC_TYP_CD');
  return !!(p && p.value === 'P10' && document.querySelector('#REQ_PTCL') && document.querySelector('#PAY_EXP_CD'));
}"""

STATE_JS = """(ids) => {
  const out = {};
  for (const id of ids) {
    const el = document.getElementById(id);
    if (!el) { out[id] = null; continue; }
    const tag = el.tagName.toLowerCase();
    const info = {tag, value: String(el.value || ''), disabled: !!el.disabled, readonly: !!el.readOnly};
    if (tag === 'select') {
      info.options = Array.from(el.options).map(o => (o.textContent || '').replace(/\\s+/g, ' ').trim());
      const sel = el.options[el.selectedIndex];
      info.text = sel ? (sel.textContent || '').trim() : '';
    }
    out[id] = info;
  }
  return out;
}"""

# 값 넣기. 처리기(jQuery change 등)가 돌도록 이벤트를 일으킨다. 읽기전용·비활성 칸은 건드리지 않는다.
SET_TEXT_JS = """([id, value]) => {
  const el = document.getElementById(id);
  if (!el) return {ok: false, why: '칸이 없음'};
  if (el.readOnly || el.disabled) return {ok: false, why: '읽기전용'};
  el.focus();
  el.value = value;
  for (const type of ['input', 'keyup', 'change']) el.dispatchEvent(new Event(type, {bubbles: true}));
  el.blur();
  return {ok: true, now: String(el.value || '')};
}"""

SET_SELECT_JS = """([id, wanted]) => {
  const el = document.getElementById(id);
  if (!el) return {ok: false, why: '칸이 없음'};
  if (el.disabled) return {ok: false, why: '비활성'};
  const norm = s => (s || '').replace(/[\\s·ㆍ・.,\\-()\\[\\]{}_/\\\\]/g, '');
  const want = norm(wanted);
  const opts = Array.from(el.options);
  let hit = opts.find(o => norm(o.textContent) === want);
  if (!hit) hit = opts.find(o => want && norm(o.textContent).startsWith(want));
  if (!hit) hit = opts.find(o => want && norm(o.textContent).includes(want));
  if (!hit) return {ok: false, why: '보기에 없음', options: opts.map(o => (o.textContent || '').trim())};
  if (el.value === hit.value) return {ok: true, now: (hit.textContent || '').trim(), same: true};
  el.focus();
  el.value = hit.value;
  el.dispatchEvent(new Event('change', {bubbles: true}));
  el.blur();
  return {ok: true, now: (hit.textContent || '').trim()};
}"""

OPTION_COUNT_JS = "(id) => { const el = document.getElementById(id); return el ? el.options.length : -1; }"

# 글자가 정확히 같은 단추가 딱 하나일 때만 누른다 — '청구서출력' · '신청' 같은 다른 단추와 섞이지 않게
CLICK_SAVE_JS = """(text) => {
  const norm = s => (s || '').replace(/\\s+/g, '');
  const hits = Array.from(document.querySelectorAll('a, button, input[type=button], span[onclick]'))
    .filter(e => norm(e.textContent || e.value) === norm(text));
  if (hits.length !== 1) return {ok: false, why: hits.length ? '같은 글자의 단추가 여럿' : '단추가 없음'};
  hits[0].click();
  return {ok: true};
}"""


@dataclass
class SaveReport:
    ok: bool
    messages: list[str] = field(default_factory=list)    # ERP 가 띄운 알림 글(alert · confirm)
    before: dict = field(default_factory=dict)             # 누르기 전 REQ_SEQ_NO · MOD_YN · APPR_DIV_CD
    after: dict = field(default_factory=dict)
    note: str = ""

    def lines(self) -> list[str]:
        out = ["임시저장 " + ("됨" if self.ok else "안 됨")]
        if self.note:
            out.append("· " + self.note)
        for message in self.messages:
            out.append("· ERP 알림: " + message)
        if self.after:
            out.append("· 결의번호 %s · 변경모드 %s · 진행 %s" % (
                self.after.get("REQ_SEQ_NO") or "—", self.after.get("MOD_YN") or "—", self.after.get("APPR_DIV_CD") or "—"))
        out.append("사람이 할 것:")
        out.extend("  · " + m for m in AFTER_SAVE_STEPS)
        return out


@dataclass
class Step:
    label: str
    value: str
    ok: bool
    note: str = ""


@dataclass
class FillReport:
    dry_run: bool
    steps: list[Step] = field(default_factory=list)
    manual: tuple[str, ...] = MANUAL_STEPS
    blocked: str = ""                  # 채우지 못한 이유 (작성 화면이 아님 등)

    @property
    def ok(self) -> bool:
        return not self.blocked and all(s.ok for s in self.steps)

    def lines(self) -> list[str]:
        head = "미리 보기 (ERP 에 넣지 않음)" if self.dry_run else "ERP 에 채움"
        out = [head]
        if self.blocked:
            out.append("✗ " + self.blocked)
        for s in self.steps:
            mark = "✓" if s.ok else "✗"
            out.append(f"{mark} {s.label}: {s.value}" + (f"  — {s.note}" if s.note else ""))
        out.append("사람이 할 것:")
        out.extend("  · " + m for m in self.manual)
        return out


def _value_for(key: str, data: dict) -> str:
    value = data.get(key)
    if value is None:
        return ""
    return str(value)


def frame_matches(frame) -> bool:
    try:
        return frame.evaluate(PROBE_JS) is True
    except Exception:  # noqa: BLE001 — 로딩 중인 프레임
        return False


def find_form(context):
    """열린 모든 창에서 일반청구 작성 프레임을 찾는다. (창, 프레임) 또는 (None, None)."""
    for page in context.pages:
        for frame in page.frames:
            if frame_matches(frame):
                return page, frame
    return None, None


def read_state(frame, ids=None) -> dict:
    return frame.evaluate(STATE_JS, list(ids or ALLOWED_IDS))


def plan(data: dict) -> list[Step]:
    """프레임 없이 — 무엇을 어디에 넣을지. 미리 보기와 확인 창이 쓴다."""
    steps = []
    for key, _id, _kind, label in FIELDS:
        value = _value_for(key, data)
        if value:
            steps.append(Step(label, value, True))
    return steps


def fill(frame, data: dict, log: Callable[[str], None], dry_run: bool = True,
         wait: Callable[[float], None] = time.sleep) -> FillReport:
    """작성 화면에 값을 넣는다. dry_run 이면 화면 상태만 읽고 계획을 보여 준다."""
    report = FillReport(dry_run=dry_run)
    state = read_state(frame, ["PROC_TYP_CD", "MOD_YN", "REQ_SEQ_NO"])
    mod = (state.get("MOD_YN") or {}).get("value", "")
    if mod and mod != "N":
        # 기존 청구서를 변경하는 화면 — 거기에 덮어쓰면 남의 값을 지운다
        report.blocked = f"새 청구서 화면이 아닙니다(MOD_YN={mod}). 결의서내역에서 [일반청구] 로 새 화면을 여세요."
        return report
    log("일반청구 채우기 %s — %s" % ("미리 보기" if dry_run else "시작", (state.get("REQ_SEQ_NO") or {}).get("value", "")))
    for line in summary_lines(data):
        log("  " + line)
    if dry_run:
        report.steps = plan(data)
        return report

    for key, element_id, kind, label in FIELDS:
        value = _value_for(key, data)
        if not value:
            continue
        try:
            if kind == "select":
                result = frame.evaluate(SET_SELECT_JS, [element_id, value])
            else:
                result = frame.evaluate(SET_TEXT_JS, [element_id, value])
        except Exception as error:  # noqa: BLE001 — 한 칸이 막혀도 나머지는 넣고 보고한다
            result = {"ok": False, "why": str(error).splitlines()[0][:80] if str(error) else "오류"}
        ok = bool(result.get("ok"))
        note = "" if ok else result.get("why", "")
        if not ok and result.get("options"):
            note += " (보기: " + " | ".join(result["options"][:8]) + ")"
        report.steps.append(Step(label, value, ok, note))
        log("  %s %s: %s%s" % ("✓" if ok else "✗", label, value, (" — " + note) if note else ""))
        if key == "expCategory" and ok:
            _wait_for_options(frame, "DTL_EXP_CD", wait)
    log("채우기 끝 — 입금처·첨부·예금주조회·저장·신청은 사람이 합니다")
    return report


def _wait_for_options(frame, element_id: str, wait: Callable[[float], None], tries: int = 20) -> None:
    """비목을 고르면 세목 보기가 서버에서 온다. 2개 이상(선택 + 실제 보기)이 될 때까지 최대 ~5초."""
    for _ in range(tries):
        try:
            if frame.evaluate(OPTION_COUNT_JS, element_id) >= 2:
                return
        except Exception:  # noqa: BLE001
            pass
        wait(0.25)


_STATUS_IDS = ("REQ_SEQ_NO", "MOD_YN", "APPR_DIV_CD", "RCV_NM", "REQ_PTCL", "REQ_AMT")


def _status(frame) -> dict:
    state = read_state(frame, _STATUS_IDS)
    return {key: (state.get(key) or {}).get("value", "") for key in _STATUS_IDS}


def save_draft(frame, log: Callable[[str], None], messages: list[str],
               wait: Callable[[float], None] = time.sleep, tries: int = 24) -> SaveReport:
    """ERP 의 [저장](임시저장)을 누르고 결과를 읽는다. messages 는 부르는 쪽이 ERP 알림 창을 받아 모아 주는 목록.

    누르기 전에 적요·청구액·입금처가 비어 있으면 누르지 않는다 — ERP 가 알림만 띄우고 끝나는 것을 미리 막는다.
    누른 뒤에는 결의번호(REQ_SEQ_NO)나 변경모드(MOD_YN)가 바뀌거나 알림이 뜰 때까지 최대 ~6초 기다린다.
    """
    assert SAVE_TEXT not in FORBIDDEN_TEXTS
    before = _status(frame)
    report = SaveReport(ok=False, before=before)
    missing = [name for key, name in (("REQ_PTCL", "적요"), ("REQ_AMT", "청구액"), ("RCV_NM", "입금처")) if not before.get(key)]
    if missing:
        report.note = "ERP 화면에 %s 이(가) 비어 있어 누르지 않았습니다. 넣은 뒤 다시 누르세요." % " · ".join(missing)
        log("임시저장 보류 — " + report.note)
        return report
    log("임시저장: ERP [%s] 누름 (결의번호 %s)" % (SAVE_TEXT, before.get("REQ_SEQ_NO") or "—"))
    try:
        result = frame.evaluate(CLICK_SAVE_JS, SAVE_TEXT)
    except Exception as error:  # noqa: BLE001
        result = {"ok": False, "why": str(error).splitlines()[0][:80] if str(error) else "오류"}
    if not result.get("ok"):
        report.note = "[%s] 단추를 누르지 못했습니다: %s" % (SAVE_TEXT, result.get("why", ""))
        log("임시저장 실패 — " + report.note)
        return report
    after = before
    for _ in range(tries):
        wait(0.25)
        try:
            after = _status(frame)
        except Exception:  # noqa: BLE001 — 저장 뒤 화면이 다시 뜨는 중이면 잠시 못 읽는다
            continue
        # '저장하시겠습니까?' 같은 확인 창은 끝이 아니다 — 화면이 바뀌거나 '저장되었습니다' 가 뜰 때까지 더 기다린다
        if _changed(before, after) or any(_is_done_message(m) for m in messages):
            break
    report.after = after
    report.messages = list(messages)
    report.ok = _changed(before, after) or any(_is_done_message(m) for m in messages)
    if not report.ok and not messages:
        report.note = "화면이 바뀌지 않았습니다. ERP 에서 저장됐는지 직접 확인하세요."
    log("임시저장 결과: %s" % " / ".join(report.lines()[:3]))
    return report


def _changed(before: dict, after: dict) -> bool:
    return any(after.get(k) != before.get(k) for k in ("REQ_SEQ_NO", "MOD_YN", "APPR_DIV_CD"))


def _is_done_message(message: str) -> bool:
    """'저장되었습니다' 류만 끝으로 본다. '저장하시겠습니까?' · '저장 실패' 는 아니다."""
    return bool(re.search(r"저장.*(되었|완료|했습니다)", message)) and not re.search(r"실패|오류|않", message)
