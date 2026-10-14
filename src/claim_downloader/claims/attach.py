"""첨부 — 작성 화면의 '첨부' 를 눌러 파일등록 팝업(rcomm_0089_01.act)을 열고, 파일을 넣은 뒤 [업로드] 를 누른다.

실측(CLAUDE.md 14절 '장학금' ③ · ③-2, 2026-10-14): 팝업은 별도 창. 숨은 `#ATTFILE`(input type=file) 하나와 `#btn_upload`,
`#CALLBACK_FN`=ctl.doUploadAttfile 이 있고, '파일 첨부' 로 파일을 고르면 행 체크 `input[name=filechkKey]` 가 파일마다 하나 생긴다.
`#ATTFILE` 이 여러 파일을 한 번에 받는지는 미확인이라 **한 개씩** 넣고 체크 수가 1 늘기를 기다린 뒤 다음 파일을 넣는다.
다 넣으면 [업로드] → 창이 닫히고 작성 화면 `#fileList` 의 보기 수가 그만큼 늘어야 한다. 아니면 사람에게 넘긴다.

OS 파일 대화상자 없이 넣는 길이 Playwright 의 set_input_files 다 — 이 앱에서 그것을 쓰는 곳은 **이 파일뿐**이다
(tests/test_safety.py). 누르는 것은 '첨부'(작성 화면, 글자가 정확히 '첨부' 인 보이는 링크) 와 [업로드](btn_upload) 뿐 —
`#btn_del` '삭제' · `#allCheck` · `#btn_file` 은 누르지 않는다. Playwright 를 들여오지 않는다.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .form import read_state
from .payee import CLICK_ID_JS, find_popup, wait_closed, wait_until

OPEN_TEXT = "첨부"                 # 작성 화면의 링크 — id 가 없어 글자로. '첨부문서'(라벨) · '첨부 문서'(표 머리글)와 섞이지 않게 정확히 같은 것만
UPLOAD_BUTTON_ID = "btn_upload"
FILE_INPUT_SELECTOR = "#ATTFILE"
ROW_CHECK_SELECTOR = "input[name=filechkKey]"
FORBIDDEN_IDS = ("btn_del", "allCheck", "btn_file", "btn_mobile_file")
SKIP_SUFFIXES = (".zip", ".7z", ".rar", ".lnk", ".db", ".ini", ".tmp")

POPUP_PROBE_JS = """() => !!(document.querySelector('#ATTFILE') && document.querySelector('#btn_upload')
  && document.querySelector('#CALLBACK_FN'))"""

# 글자가 정확히 같은 링크 중 **보이는 것** 하나를 누른다 — 두 탭(일반청구·인건비)에 '첨부' 가 하나씩 있다(실측 ①)
CLICK_TEXT_JS = """(text) => {
  const norm = s => (s || '').replace(/\\s+/g, '');
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const all = Array.from(document.querySelectorAll('a, button, span[onclick]')).filter(e => norm(e.textContent) === norm(text));
  const hits = all.filter(vis);
  if (hits.length !== 1) return {ok: false, why: hits.length ? '같은 글자의 단추가 여럿' : (all.length ? '단추가 보이지 않음' : '단추가 없음')};
  hits[0].click();
  return {ok: true};
}"""

ROW_COUNT_JS = "() => document.querySelectorAll('input[name=filechkKey]').length"


@dataclass
class AttachReport:
    ok: bool
    files: list[str] = field(default_factory=list)
    uploaded: int = 0
    note: str = ""
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        names = " · ".join(os.path.basename(f) for f in self.files) or "—"
        if self.ok:
            return [f"✓ 첨부 {self.uploaded}개 올림: {names}"]
        return [f"✗ 첨부: {self.note or '올리지 못함'} ({names}) — '첨부' 로 직접 올려 주세요"]


def attachable(paths: list[str]) -> list[str]:
    """올릴 수 있는 파일만 — 압축·바로가기·시스템 파일은 뺀다. 없는 파일도 뺀다."""
    out = []
    for p in paths:
        if not os.path.isfile(p) or os.path.basename(p).startswith(("~$", ".")):
            continue
        if p.lower().endswith(SKIP_SUFFIXES):
            continue
        out.append(p)
    return out


def file_count(frame) -> int:
    """작성 화면 첨부문서 목록(#fileList, 보이는 쪽)의 보기 수."""
    state = read_state(frame, ["fileList"]).get("fileList") or {}
    return len(state.get("options") or [])


def open_popup(page, frame, log: Callable[[str], None]):
    popup = find_popup(page.context, POPUP_PROBE_JS)
    if popup is not None:
        log("파일등록 팝업이 이미 열려 있어 그대로 씁니다")
        return popup, ""
    try:
        with page.expect_popup(timeout=8000) as info:
            result = frame.evaluate(CLICK_TEXT_JS, OPEN_TEXT)
            if not result.get("ok"):
                raise RuntimeError("'첨부' 를 누르지 못했습니다: " + str(result.get("why", "")))
        return info.value, ""
    except Exception as error:  # noqa: BLE001
        return None, (str(error).splitlines()[0][:120] if str(error) else "팝업이 열리지 않았습니다")


def upload(page, frame, paths: list[str], log: Callable[[str], None],
           wait: Callable[[float], None] = time.sleep, messages: list[str] | None = None) -> AttachReport:
    """파일들을 파일등록 팝업으로 올린다. 한 개씩 넣고 행이 생기는 것을 확인한 뒤 [업로드]."""
    messages = messages if messages is not None else []
    files = attachable(list(paths))
    report = AttachReport(ok=False, files=files, messages=messages)
    if not files:
        report.ok = True
        report.note = "올릴 파일 없음"
        return report
    before = file_count(frame)
    popup, why = open_popup(page, frame, log)
    if popup is None:
        report.note = why
        log("첨부 팝업: " + why)
        return report

    def on_dialog(dialog) -> None:
        messages.append(dialog.message.strip())
        log("첨부 팝업 알림: %s" % dialog.message.strip())
        try:
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass

    popup.on("dialog", on_dialog)
    try:
        if not wait_until(lambda: popup.evaluate(POPUP_PROBE_JS) is True, wait, tries=40):
            report.note = "팝업이 파일등록 화면이 아닙니다"
            return report
        for index, path in enumerate(files):
            rows_before = int(popup.evaluate(ROW_COUNT_JS))
            try:
                popup.set_input_files(FILE_INPUT_SELECTOR, path)
            except Exception as error:  # noqa: BLE001
                report.note = "파일을 넣지 못했습니다(%s): %s" % (os.path.basename(path), str(error).splitlines()[0][:80] if str(error) else "")
                return report
            if not wait_until(lambda: int(popup.evaluate(ROW_COUNT_JS)) > rows_before, wait, tries=20):
                report.note = "파일을 넣었는데 목록에 줄이 생기지 않음(%s)" % os.path.basename(path)
                return report
            log("  첨부 %d/%d: %s" % (index + 1, len(files), os.path.basename(path)))
        clicked = popup.evaluate(CLICK_ID_JS, UPLOAD_BUTTON_ID)
        if not clicked.get("ok"):
            report.note = "[업로드] 를 누르지 못했습니다: " + str(clicked.get("why", ""))
            return report
        if not wait_closed(popup, wait, seconds=90):
            report.note = "[업로드] 를 눌렀지만 팝업이 닫히지 않음"
            return report
        wait(0.5)
        after = file_count(frame)
        report.uploaded = after - before
        if report.uploaded >= len(files):
            report.ok = True
            log("첨부 %d개 올림 (첨부문서 %d → %d)" % (len(files), before, after))
        else:
            report.note = "작성 화면 첨부문서가 %d개만 늘었습니다(%d개 기대)" % (report.uploaded, len(files))
        return report
    finally:
        try:
            popup.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass
