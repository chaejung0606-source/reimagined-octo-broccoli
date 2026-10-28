"""ERP 일반청구 작성 화면 — 작성 프레임 찾기 · 칸 읽기 · 값 넣는 JS · [저장](임시저장). 신청은 사람.

장학금 · 혁신인재지원금(scholarship.py) · 카드청구(card_erp.py) · 첨부만 다시 올리기(reattach.py)가 같이 쓴다. 실측(CLAUDE.md 14절,
2026-10-13)한 요소 id 만 만진다. 값은 JS 로 넣고 input·change 이벤트를 일으켜 화면의 처리기가 돌게 한다.
일반 종류(AI 가 읽은 값을 채우던 fill · FIELDS)는 2026-10-28 담당자 요청으로 걷어냈다 — 코드는 git 이력에만 있다.

이 모듈은 Playwright 를 들여오지 않는다 — session.py 가 넘겨준 프레임의 evaluate 만 쓴다. 받기 코드(erp.py)에는
값 넣기가 끝까지 없어야 하므로 값 넣는 JS 는 claims/ 에만 둔다(tests/test_safety.py 가 본다).

담당자 결정(2026-10-13): 내역 작성 후 **임시저장까지** 앱이 하고, 그 뒤 사람이 검토해 [신청] 을 누른다.
그래서 이 모듈이 누르는 단추는 '저장' 하나뿐이다(SAVE_TEXT · save_draft). '신청' 을 비롯한 FORBIDDEN_TEXTS 를
누르는 코드가 들어오면 안전 테스트가 깨진다.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

# 절대 누르지 않는 단추의 글자 (id 가 없어 글자로 둔다). '신청' 이 돈이 나가는 단추다.
FORBIDDEN_TEXTS = ("신청", "삭제", "초기화", "새 청구서", "일괄예금주조회", "[예금주조회]", "청구서복사")
# 앱이 누르는 유일한 단추 — 임시저장. 글자가 정확히 같은 단추가 하나일 때만 누른다(CLICK_SAVE_JS).
SAVE_TEXT = "저장"

# read_state 가 ids 를 안 받았을 때 읽는 칸 — 실측 id(14절)
ALLOWED_IDS = frozenset({"PAY_EXP_CD", "DTL_EXP_CD", "EVDI_DIV_CD", "EXP_DT", "SETTLE_METH_CD", "BNK_CD", "ACCT_NO", "OWNR", "REQ_AMT",
                         "SUPPLY_AMT", "TAX_AMT", "REQ_PTCL", "PROC_TYP_CD", "MOD_YN", "REQ_SEQ_NO", "REQ_CNT", "RCV_NM", "RCV_CD", "BAL_AMT"})
AFTER_SAVE_STEPS = (
    "ERP 에서 임시저장된 청구서를 검토하세요",
    "[신청] 은 직접 누르세요 — 앱은 누르지 않습니다",
)

# 작성 프레임 알아보기 — 일반청구(P10) 작성 화면에만 있는 조합
PROBE_JS = """() => {
  const p = document.querySelector('#PROC_TYP_CD');
  return !!(p && p.value === 'P10' && document.querySelector('#REQ_PTCL') && document.querySelector('#PAY_EXP_CD'));
}"""

# 같은 id 중 보이는 요소를 고르는 JS 조각 — 아래 JS 들이 공유한다
PICK_EL_JS = """// 같은 id 가 두 탭(일반청구 · 인건비)에 하나씩 있다(실측 2026-10-13 ①). 보이는 쪽을 고르고, 다 숨었으면 첫째.
  const pickEl = id => {
    const all = Array.from(document.querySelectorAll('[id="' + String(id).replace(/"/g, '\\"') + '"]'));
    if (!all.length) return null;
    const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    return all.find(vis) || all[0];
  };"""

STATE_JS = """(ids) => {
  """ + PICK_EL_JS + """
  const out = {};
  for (const id of ids) {
    const el = pickEl(id);
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
  """ + PICK_EL_JS + """
  const el = pickEl(id);
  if (!el) return {ok: false, why: '칸이 없음'};
  // 고르기 칸(select)에 글을 넣으면 값이 '' 가 되는데도 ok 로 보고됐다 — 글 칸만 받는다(2026-10-14 점검)
  if (!/^(INPUT|TEXTAREA)$/.test(el.tagName)) return {ok: false, why: '글 칸이 아님(' + el.tagName.toLowerCase() + ')'};
  if (el.readOnly || el.disabled) return {ok: false, why: '읽기전용'};
  el.focus();
  el.value = value;
  for (const type of ['input', 'keyup', 'change']) el.dispatchEvent(new Event(type, {bubbles: true}));
  el.blur();
  return {ok: true, now: String(el.value || '')};
}"""

SET_SELECT_JS = """([id, wanted]) => {
  """ + PICK_EL_JS + """
  const el = pickEl(id);
  if (!el) return {ok: false, why: '칸이 없음'};
  if (el.disabled) return {ok: false, why: '비활성'};
  const norm = s => (s || '').replace(/[\\s·ㆍ・.,\\-()\\[\\]{}_/\\\\]/g, '').toLowerCase();
  // 은행 이름의 앞뒤 꾸밈(KB국민은행 · NH농협은행 · 카카오뱅크)을 뗀 몸통 — 명단의 짧은 이름(국민 · 카카오)과 맞춘다
  const ALIAS = {'sc제일': '스탠다드차타드', '제일': '스탠다드차타드', '씨티': '한국씨티'};
  const core = s => {
    let c = norm(s).replace(/^(kb|nh|ibk|keb|sc|bnk|dgb|im)(?=[가-힣])/, '').replace(/(은행|뱅크)$/, '');
    return Object.prototype.hasOwnProperty.call(ALIAS, c) ? ALIAS[c] : c;
  };
  const want = norm(wanted), wantCore = core(wanted);
  const opts = Array.from(el.options);
  const label = o => (o.textContent || '').trim();
  const options = opts.map(label);
  if (!want) return {ok: false, why: '보기에 없음', options};
  // 정확히 같은 보기가 먼저. 그다음 단계는 맞는 보기가 **하나일 때만** 고른다 — 전에는 첫 보기를 골라
  // '농협' 이 농협은행 · 지역농축협 중 앞의 것으로, '수협' 이 수협은행 · 수협중앙회 중 앞의 것으로 갈 수 있었다(2026-10-14 점검)
  let hit = opts.find(o => norm(o.textContent) === want);
  if (!hit && /^(농협|수협)$/.test(wantCore) && !/(은행|뱅크)$/.test(want)) {
    // 명단의 '농협' · '수협' 은 은행(011 · 007)인지 지역 조합(012 · 030)인지 알 수 없다 — 보기에 둘 다 있으면 사람이 고른다
    const family = opts.filter(o => norm(o.textContent).includes(wantCore) || (wantCore === '농협' && /농축협|단위농/.test(norm(o.textContent))));
    if (family.length > 1) return {ok: false, why: '보기가 여럿(' + family.map(label).join(' · ') + ') — 명단에 은행 이름을 정확히', options};
  }
  for (const test of [o => wantCore && core(o.textContent) === wantCore,
                      o => norm(o.textContent).startsWith(want),
                      o => wantCore.length > 1 && core(o.textContent).startsWith(wantCore),
                      o => norm(o.textContent).includes(want)]) {
    if (hit) break;
    const found = opts.filter(test);
    if (found.length > 1) return {ok: false, why: '보기가 여럿(' + found.map(label).join(' · ') + ')', options};
    hit = found[0];
  }
  if (!hit) return {ok: false, why: '보기에 없음', options};
  if (el.value === hit.value) return {ok: true, now: (hit.textContent || '').trim(), same: true};
  el.focus();
  el.value = hit.value;
  el.dispatchEvent(new Event('change', {bubbles: true}));
  el.blur();
  return {ok: true, now: (hit.textContent || '').trim()};
}"""

# 세목 select 의 상태 — 보기 수와 보이는지. 숨은 채 비어 있으면 이 과제는 세목을 쓰지 않는 것이다.
CLICK_SAVE_JS = """(text) => {
  const norm = s => (s || '').replace(/\\s+/g, '');
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'; };
  const all = Array.from(document.querySelectorAll('a, button, input[type=button], span[onclick]'))
    .filter(e => norm(e.textContent || e.value) === norm(text));
  const shown = all.filter(vis);
  const hits = shown.filter(h => !shown.some(o => o !== h && h.contains(o)));
  if (hits.length !== 1) {
    return {ok: false, why: (hits.length ? '화면에 보이는 같은 글자의 단추가 여럿' : '화면에 보이는 단추가 없음')
                            + ' (보이는 것 ' + hits.length + '개 · 숨은 것 포함 ' + all.length + '개)'};
  }
  hits[0].click();
  return {ok: true, hidden: all.length - shown.length};
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
            out.append("· 결의번호 %s · 진행 %s" % (
                self.after.get("REQ_CNT") or self.after.get("REQ_SEQ_NO") or "—",
                "임시저장" if self.after.get("APPR_DIV_CD") == "40" else (self.after.get("APPR_DIV_CD") or "—")))
        out.append("사람이 할 것:")
        out.extend("  · " + m for m in AFTER_SAVE_STEPS)
        return out


def frame_matches(frame) -> bool:
    try:
        return frame.evaluate(PROBE_JS) is True
    except Exception:  # noqa: BLE001 — 로딩 중인 프레임
        return False


# 작성 프레임이 지금 화면에 보이는지 — ERP 는 상단 탭마다 iframe 을 두고 안 보이는 탭은 숨긴다(같은 출처라 frameElement 를 읽을 수 있다)
FRAME_VISIBLE_JS = """() => { try { const f = window.frameElement; if (!f) return true;
  const r = f.getBoundingClientRect(); return r.width > 0 && r.height > 0; } catch (e) { return true; } }"""


def find_form(context):
    """열린 모든 창에서 일반청구 작성 프레임을 찾는다. (창, 프레임) 또는 (None, None).

    작성 화면이 둘 이상 열려 있으면(앞 폴더의 청구서 탭이 남은 채 새 청구서를 띄운 경우) **화면에 보이는 것**을 고른다 —
    첫째 것을 고르면 앞 청구서에 다음 폴더의 사람이 들어갈 수 있다(담당자 요청 2026-10-14: 폴더를 하나씩 끝내고 다음으로)."""
    found = [(page, frame) for page in context.pages for frame in page.frames if frame_matches(frame)]
    if not found:
        return None, None
    for page, frame in found:
        try:
            if frame.evaluate(FRAME_VISIBLE_JS) is True:
                return page, frame
        except Exception:  # noqa: BLE001 — 읽지 못하면 다음 것
            continue
    return found[0]


def wait_for_form(context, tries: int = 12, interval_ms: int = 500, log: Callable[[str], None] | None = None):
    """find_form 을 한 번 보고 포기하지 않는다 — 받기의 목록 찾기(erp.wait_for_grid)와 같은 함정(CLAUDE.md 7절 1번: 화면이 보여도 첫
    evaluate 가 False · 예외일 수 있다).

    담당자 실제 시험(2026-10-19): 작성 화면을 띄워 두고 [ERP 에 넣기] 를 눌러도 처음에는 '작성 화면을 찾지 못했습니다' 였고, 브라우저를
    한 번 누른 뒤 다시 누르면 됐다. 그래서 0.5초마다 다시 보고, 두 번째부터는 작성 화면이 든 창을 앞으로 가져온다 — 사람이 브라우저 창을
    누른 것과 같은 일이고 ERP 의 단추를 누르는 것이 아니다. 끝내 못 찾으면 어느 프레임이 무엇을 돌려줬는지 기록에 남긴다."""
    for attempt in range(max(1, tries)):
        page, frame = find_form(context)
        if frame is not None:
            if attempt and log:
                log("작성 화면을 %d번째에 찾았습니다" % (attempt + 1))
            return page, frame
        pages = list(getattr(context, "pages", []) or [])
        if attempt == 0:
            for pg in [pg for pg in pages if any("rexpe_0084" in (f.url or "") for f in pg.frames)] or pages[:1]:
                try:
                    pg.bring_to_front()
                except Exception:  # noqa: BLE001 — 닫히는 중인 창
                    pass
        if attempt + 1 < tries:
            if pages:
                try:
                    pages[0].wait_for_timeout(interval_ms)
                    continue
                except Exception:  # noqa: BLE001 — 닫힌 창
                    pass
            time.sleep(interval_ms / 1000)
    if log:
        log("작성 화면을 찾지 못함 — " + describe_frames(context))
    return None, None


def describe_frames(context) -> str:
    """진단용 — 열린 창 수와, 주소가 작성 화면(rexpe_0084)인 프레임마다 확인 결과. 주소의 물음표 뒤(과제번호 등)는 적지 않는다."""
    pages = list(getattr(context, "pages", []) or [])
    out = []
    for pi, pg in enumerate(pages):
        for fr in pg.frames:
            url = fr.url or ""
            if "rexpe_0084" not in url:
                continue
            try:
                got = fr.evaluate(PROBE_JS)
            except Exception as error:  # noqa: BLE001
                got = "오류 " + (str(error).splitlines() or [""])[0][:80]
            out.append("창 %d %s → %s" % (pi + 1, url.split("?")[0].rsplit("/", 1)[-1], got))
    return "창 %d개 · 작성 화면 주소 프레임 %d개%s" % (len(pages), len(out), (": " + " · ".join(out)) if out else "")


def read_state(frame, ids=None) -> dict:
    return frame.evaluate(STATE_JS, list(ids or ALLOWED_IDS))


_STATUS_IDS = ("REQ_SEQ_NO", "MOD_YN", "APPR_DIV_CD", "REQ_CNT", "RCV_NM", "REQ_PTCL", "REQ_AMT")


def saved_sheet(state: dict) -> str:
    """작성 화면이 이미 [저장] 된 청구서면 그 결의번호(없으면 '임시저장'), 새 청구서면 ''. state 는 read_state 결과."""
    def value(key: str) -> str:
        item = state.get(key)
        return str(item.get("value", "") if isinstance(item, dict) else item or "").strip()
    if value("REQ_CNT"):
        return value("REQ_CNT")
    return "임시저장" if value("APPR_DIV_CD") == "40" else ""


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
    try:
        result = frame.evaluate(CLICK_SAVE_JS, SAVE_TEXT)
    except Exception as error:  # noqa: BLE001
        result = {"ok": False, "why": str(error).splitlines()[0][:80] if str(error) else "오류"}
    if not result.get("ok"):
        report.note = "[%s] 단추를 누르지 못했습니다: %s" % (SAVE_TEXT, result.get("why", ""))
        log("임시저장 실패 — " + report.note)
        return report
    # 누른 뒤에 적는다 — 전에는 누르기 전에 '누름' 을 적어 실패한 시험의 로그가 헷갈렸다
    # 결의번호(#REQ_CNT)는 첫 [저장] 에 생긴다(실측 ⑤). REQ_SEQ_NO 는 'TMP_REQ_…' 임시 번호라 결의번호로 적지 않는다
    log("임시저장: ERP [%s] 누름 (%s)" % (SAVE_TEXT, f"결의번호 {before['REQ_CNT']}" if before.get("REQ_CNT") else "첫 저장"))
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
    """저장되면 작성 프레임이 다시 열린다(실측 ⑤ 2026-10-14): 숨은 REQ_CNT(결의번호)가 생기고 APPR_DIV_CD 가 40(임시저장).
    REQ_SEQ_NO 도 새 TMP_ 값으로 바뀌지만 MOD_YN 은 N 그대로다. 둘째 사람부터는 REQ_CNT 가 이미 있으므로 REQ_SEQ_NO 변화도 본다."""
    if after.get("REQ_CNT") and after.get("REQ_CNT") != before.get("REQ_CNT"):
        return True
    if after.get("APPR_DIV_CD") == "40" and before.get("APPR_DIV_CD") != "40":
        return True
    # 작성 화면이 아니게 됐으면(로그인 · 오류 화면으로 넘어가 칸이 모두 비면) 저장된 것으로 보지 않는다(2026-10-14 점검)
    if not after.get("REQ_SEQ_NO") and not after.get("MOD_YN"):
        return False
    return any(after.get(k) != before.get(k) for k in ("REQ_SEQ_NO", "MOD_YN", "APPR_DIV_CD"))


def _is_done_message(message: str) -> bool:
    """'저장되었습니다' 류만 끝으로 본다. '저장하시겠습니까?' · '저장 실패' 는 아니다."""
    return bool(re.search(r"저장.*(되었|완료|했습니다)", message)) and not re.search(r"실패|오류|않", message)
