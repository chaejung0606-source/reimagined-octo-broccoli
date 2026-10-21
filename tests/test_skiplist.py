"""받지 않는 결의서(skiplist.py) — 담당자 2026-10-21 "지금 받지 못하는 결의서는 받지 않아도 되는 결의서 목록에 추가해주세요".

실행로그 줄은 session.download 가 남기는 모양 그대로(과제번호는 실제 것, 내용은 모양만 같은 가짜).
"""
from __future__ import annotations

from conftest import make_row

from claim_downloader import settings, skiplist

LOG = """\
17:58:31 ════ 2026-10-21 앱 실행 ════
17:58:40 ── 과제 202408470001 의 결의서내역
17:59:02 ── 과제 202408470001 → C:\\Users\\x\\Desktop\\지출결의서\\(202408470001)_2024년도 사업비
17:59:02 [1/65] No 1 (결의 1) · 정산 완료 후 잔액조정
17:59:02       ✖ 상세화면(청구서출력)이 안 뜸
18:20:00 ════ 2026-10-21 앱 실행 ════
18:21:02 ── 과제 202408470001 → C:\\Users\\x\\Desktop\\지출결의서\\(202408470001)_2024년도 사업비
18:21:02 [1/65] No 1 (결의 1 · 예산잔액조정신청) · 정산 완료 후 잔액조정
18:21:13       ↷ 건너뜀 — 상세화면에 '청구서출력' 이 없음 — 화면 rexpe_0099_01.act · 출력 단추 결의서출력 (결의서구분 '예산잔액조정신청')
18:21:14 ── 과제 202408470001 → C:\\Users\\x\\Desktop\\지출결의서\\(202408470001)_2024년도 사업비
18:21:14 [2/65] No 2 (결의 7 · 일반청구) · 09_사무용품
18:21:20       → 09. 그 밖의사업운영경비 / 09_(250301) 사무용품_가나_(10,000).pdf
18:22:00 [3/65] No 3 (결의 9 · 일반대체) · 예산 대체
18:22:06       ↷ 건너뜀 — 상세조회 뒤 ERP 알림: 대체 결의서는 출력하지 않습니다 (결의서구분 '일반대체')
18:22:07 ── 과제 202409710003 → C:\\Users\\x\\Desktop\\지출결의서\\(202409710003)_2026년도 대응자금
18:22:07 [4/65] No 4 (결의 3 · 일반청구) · 02_장학금
18:22:20       ↷ 건너뜀 — 상세조회 뒤 ERP 알림: 처리 중입니다 (결의서구분 '일반청구')
18:22:21 [5/65] No 5 (결의 4 · 예산잔액조정신청) · 잔액조정
18:22:30       ↷ 건너뜀 — 상세조회 뒤 ERP 알림: 로그인 세션이 만료되었습니다 (결의서구분 '예산잔액조정신청')
18:22:31 ── 과제 (모름) → C:\\Users\\x\\Desktop\\지출결의서
18:22:31 [6/65] No 6 (결의 5 · 일반대체) · 과제 모름
18:22:40       ↷ 건너뜀 — 상세화면에 '청구서출력' 이 없음 — 화면 ? · 출력 단추 없음 (결의서구분 '일반대체')
"""


def test_skipped_lines_in_the_log_become_the_list():
    items = skiplist.from_log(LOG)
    # 옛 판의 멈춤(✖) · 청구 결의서 · 로그인 알림 · 과제를 모르는 줄은 넣지 않는다
    assert [(i["project"], i["seq"], i["gubun"]) for i in items] == [
        ("202408470001", "1", "예산잔액조정신청"), ("202408470001", "9", "일반대체")]
    assert items[0]["cont"] == "정산 완료 후 잔액조정" and "청구서출력" in items[0]["reason"]


def test_first_load_imports_the_log_once(isolated_home):
    settings.log_path().write_text(LOG, encoding="utf-8")
    assert len(skiplist.load()) == 2
    with open(settings.log_path(), "a", encoding="utf-8") as log:      # 그 뒤의 줄은 받기가 직접 넣는다 — 로그를 다시 읽지 않는다
        log.write("19:00:00 ── 과제 202408470002 → C:\\x\n19:00:00 [1/1] No 1 (결의 2 · 일반대체) · 대체\n"
                  "19:00:09       ↷ 건너뜀 — 상세화면에 '청구서출력' 이 없음 — 화면 ? · 출력 단추 없음 (결의서구분 '일반대체')\n")
    assert len(skiplist.load()) == 2
    skiplist.clear()
    assert skiplist.load() == []                                        # 비우면 로그에서 다시 가져오지 않는다


def test_rows_match_by_document_number_or_project_and_resolution_number(isolated_home):
    settings.log_path().write_text(LOG, encoding="utf-8")
    items = skiplist.load()
    assert skiplist.matches(items, make_row(seq="1", docNo="202408470001-20250228-1"), "202408470001")
    assert not skiplist.matches(items, make_row(seq="1"), "202408470003")             # 다른 과제의 결의번호 1
    assert skiplist.add(make_row(seq="12", docNo="X-20260101-12", gubun="일반대체"), "청구서출력 없음", "202408470003") == (True, "")
    assert skiplist.add(make_row(seq="12", docNo="X-20260101-12", gubun="일반대체"), "청구서출력 없음", "202408470003")[0] is False
    assert skiplist.add(make_row(seq="13", gubun="카드청구"), "청구서출력 없음", "202408470003")[0] is False
    items = skiplist.load()
    assert skiplist.matches(items, make_row(seq="99", docNo="X-20260101-12"))               # 문서번호가 같으면
    assert not skiplist.matches(items, make_row(seq="12", docNo="Y-20260101-12"), "202408470003")   # 문서번호가 다르면 결의번호로 맞추지 않는다


def test_why_not():
    assert skiplist.why_not("예산잔액조정신청", "청구서출력 없음") == ""
    assert skiplist.why_not("대량청구", "청구서출력 없음")
    assert skiplist.why_not("", "청구서출력 없음") and skiplist.why_not("?", "x")
    assert skiplist.why_not("일반대체", "ERP 알림: 세션이 끝났습니다")
