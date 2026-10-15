"""문제 보내기 — 가린 기록에 개인정보가 남지 않는지. 기록 줄은 앱이 실제로 남기는 모양(scholarship · session 의 log 글)을 본떴다.
이름 · 번호는 모두 가짜다."""

from claim_downloader import settings, share_log

LOG = """\
05:01:02 장학금 청구 시작 — 2명
05:01:02 ── 1. 홍길동 (학번 202600001 · 300,000원)
05:01:03 소득자 검색(인적정보, 학번): '202600001' → 1행
05:01:03 소득자 자동 선택: 홍길동(202600001) — 학번 일치
05:01:04 소득자를 고른 뒤 ERP 계좌: 은행 국민은행 · 계좌 110594395796 · 예금주 홍길동 · 예금주조회 성공:홍길동
05:01:05 계좌 불일치: 명단 국민 110-594-395796 / ERP 국민은행 1234567890123 — 개별증빙 PDF 1개에서 계좌를 찾지 못함
05:01:06   적요: 02_2026년도 7월 (가)형 근로장학금_홍길동
05:01:07 ── 2. 바트바야르 (학번 202600002 · 240,000원)
05:01:07 예금주조회 결과: 성공:SUNATULLAEV GO
05:01:07 외국인 학생으로 봄: 2. 바트바야르 (주민번호 뒷자리 첫 숫자 7)
05:01:08 주민번호 990101-1234567 / ######-3******
05:01:09 [1/3] No 5 (결의 324) · 02_(261012) 2026년도 7월 근로장학금_김철수 등 3명_(900,000).pdf
05:01:10 문서번호 산학-20261008-0001 · 결의번호 324 · 2026-10-14
05:01:11 C:\\Users\\chaejung\\Desktop\\★★지출진행\\개별증빙\\이영희.pdf
05:01:12 메일 someone@kangwon.ac.kr · 전화 010-1234-5678
05:01:13 신청 전 확인: 1. 홍길동 — 첨부서류에서 계좌를 읽지 못해 명단 엑셀의 계좌로 넣음
"""


def test_mask_hides_personal_values_and_keeps_diagnosis():
    out = share_log.mask_text(LOG, names=["이영희"])
    for secret in ("홍길동", "바트바야르", "SUNATULLAEV", "김철수", "이영희", "chaejung", "202600001", "110594395796",
                   "110-594-395796", "1234567890123", "990101", "1234567", "someone@", "1234-5678"):
        assert secret not in out, secret
    # 진단에 쓰는 것은 그대로 — 단계 · 금액 · 결의번호 · 문서번호 · 날짜 · 계좌 끝 4자리(명단과 ERP 가 같은지 보려고)
    for kept in ("300,000원", "결의번호 324", "산학-20261008-0001", "2026-10-14", "5796", "→ 1행", "kangwon.ac.kr", "2026*****"):
        assert kept in out, kept
    assert "홍○○" in out and "02_2026년도 7월 (가)형 근로장학금_홍○○" in out


def test_build_writes_shareable_copy(tmp_path):
    settings.log_path().write_text(LOG, encoding="utf-8")
    text, path = share_log.build(names=[], version="abc123")
    assert path.name == "_공유용로그.txt" and path.read_text(encoding="utf-8") == text
    assert text.startswith("COSS 업무데스크 공유용 기록") and "abc123" in text and "홍길동" not in text


def test_build_without_log_returns_empty():
    text, _path = share_log.build()
    assert text == ""
