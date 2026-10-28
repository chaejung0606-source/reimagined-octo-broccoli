"""단계 흐름의 차례 셈 — Qt 없이 돈다(tests/test_flow.py). 모양은 ui/flow.py.

업무 화면마다 '지금 어느 단계인가' 를 상태 값으로 정하고, 그 단계 앞은 접고 뒤는 숨긴다(담당자 요청 2026-10-21 —
"클릭해야 하는 순서대로 버튼 및 기능이 하나 둘 떠올라서").
"""
from __future__ import annotations

HIDDEN, CURRENT, DONE, OPEN = "hidden", "current", "done", "open"


def flow_states(order: list[str], current: str, keep_open: tuple[str, ...] = ()) -> dict[str, str]:
    """차례(order)와 지금 단계로 단계마다 상태 — 앞은 접힘(keep_open 은 펼친 채), 지금은 강조, 뒤는 아직 안 보임."""
    out = {}
    at = order.index(current)
    for i, key in enumerate(order):
        if i < at:
            out[key] = OPEN if key in keep_open else DONE
        elif i == at:
            out[key] = CURRENT
        else:
            out[key] = HIDDEN
    return out


DOWNLOAD_ORDER = ["docs", "project", "login", "list"]


def download_stage(docs_picked: bool, picked: bool, reading: bool, listed: bool) -> str:
    """증빙 다운로드 — ① 받을 서류 → ② 과제 → ③ ERP 로그인 → ④ 받을 청구서 확인하고 받기.
    서류를 먼저, 과제를 그다음에 고른다(담당자 2026-10-22 — 구매요청(계약) 서류는 고른 과제의 기간으로 일자 범위를 정하므로).
    목록을 읽는 중이거나 읽었으면 ④. 목록을 못 읽으면(로그인 전 · 목록 못 찾음) ③ 으로 돌아온다."""
    if not docs_picked:
        return "docs"
    if not picked:
        return "project"
    if listed or reading:
        return "list"
    return "login"


STRUCTURE_ORDER = ["site", "open", "save", "send"]


def structure_stage(picked: bool, opened: bool, saved: bool) -> str:
    """화면 구조 저장 — ① 어느 사이트 → ② 그 사이트 열기 → ③ 실측할 화면을 띄우고 저장 → ④ 저장한 파일 보내기.
    다른 업무에서 이미 열어 둔 사이트면 ② 는 저절로 지난다. 저장한 뒤에도 ③ 은 펼친 채(화면 여러 개를 차례로 저장)."""
    if not picked:
        return "site"
    if not opened:
        return "open"
    return "send" if saved else "save"


PARKING_ORDER = ["what", "work", "result"]


def parking_stage(picked: bool, has_result: bool) -> str:
    """주차등록 — ① 무엇을 할까요(할인 적용 · 할인 링크 · 할인 내역) → ② 그 일의 칸 → ③ 결과.
    할인 내역은 ② 의 표가 결과라 ③ 이 없다(화면이 has_result 를 넘기지 않는다)."""
    if not picked:
        return "what"
    return "result" if has_result else "work"


MINUTES_ORDER = ["folders", "make", "result"]


def minutes_stage(has_dirs: bool, finished: bool) -> str:
    """회의록 생성 — ① 회의 폴더 넣기 → ② 확인하고 만들기(AI · [작업 시작]) → ③ 결과.
    폴더를 더 넣을 수 있게 ① 은 펼친 채 두고, 끝난 뒤 폴더를 더 넣으면 다시 ② 로."""
    if not has_dirs:
        return "folders"
    return "result" if finished else "make"


CLAIM_ORDER = ["kind", "add", "check", "put"]


def claim_stage(has_dirs: bool, ready: bool, kind_picked: bool = True) -> str:
    """일반청구 — ① 청구 종류 → ② 지출 폴더 넣기(과제) → ③ 내용 확인(목록 · 명단 · 결제 건) → ④ ERP 에 넣기.
    종류를 먼저 카드로 고른다(담당자 2026-10-26 "1단계에서 청구종류를 선택할 수 있도록" — 전에는 ① 의 작은 고르기 칸이라 눈에 안 띄었다).
    폴더를 넣었으면 종류는 고른 것으로 본다(종류를 고르기 전에는 폴더를 받지 않는다). ④ 는 고른 줄을 넣을 수 있을 때(명단 · 카드 폴더를
    읽어 두었으면) 떠오른다. ③ 은 늘 펼친 채(표를 보며 넣는다)."""
    if not has_dirs:
        return "add" if kind_picked else "kind"
    return "put" if ready else "check"
