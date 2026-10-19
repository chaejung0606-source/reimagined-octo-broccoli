"""일반청구 추출 규칙 — AI 가 폴더에서 무엇을 어떻게 뽑을지. 담당자가 고쳐 쓴다.

회의록 규칙(minutes/rules.py)과 같은 방식: ~/.claim-downloader/일반청구규칙.txt 가 담당자 파일,
일반청구규칙.기본값.txt 가 기준. 둘이 같으면 손대지 않은 것으로 보고 업데이트 때 최신 기본 규칙으로
갈고, 다르면 담당자가 고친 것으로 보고 둔다. 플랫폼별로 규칙을 따로 두지 않는다.
"""
from __future__ import annotations

import traceback

from .. import settings
from ..minutes.logbook import log
from ..minutes.textfile import _read_text

RULES_HEADER = (
    "# 일반청구 추출 규칙\n"
    "# 이 파일을 고치면 지출 폴더에서 값을 뽑는 기준이 바뀝니다.\n"
    "# 저장만 하면 다음 [내용 읽기] 부터 바로 반영됩니다. (프로그램을 다시 켜지 않아도 됨)\n"
    "# '#' 으로 시작하는 줄은 설명이라 무시됩니다.\n"
    "# 기본값으로 되돌리려면 이 파일을 지우고 프로그램을 다시 켜세요.\n"
    "\n"
)

RULES_DEFAULT = """- 지출 1건 = 폴더 1개. 폴더 바로 아래의 서류(지출품의서·내부결재, 세금계산서, 견적서·거래명세서, 사업자등록증, 통장사본 등)를 모두 읽고 아래 값을 찾는다. 하위 폴더는 보지 않는다.
- 적요(summary): 'NN_내용' 형식. NN 은 비목 번호 — 01 인건비 · 02 장학금 · 03 교육·연구프로그램개발·운영비 · 04 교육·연구환경개선비 · 05 실험·실습장비및기자재구입·운영비 · 06 지자체 연계ㆍ협업비용 · 07 기업지원·협력활동비 · 08 성과활용·확산지원비 · 09 기타운영경비 · 10 간접비. 내용은 지출품의서의 제목(건명)을 따른다. 예: '09_2026년 사업단 정수기 임차료(9월)'. 60자 안.
- 비목(expCategory): 위 보기 이름 중 하나를 그대로 적는다. 지출품의서에 적힌 비목을 우선한다.
- 세목(expDetail): 서류에 세목이 있으면 그대로, 없으면 빈 문자열.
- 증빙구분(evidence): 사업자 지출로 세금계산서가 있으면 '세금계산서'(면세 전자계산서면 '계산서'), 그 밖(개인 계좌이체 등)은 모두 '기타'. 카드 결제는 카드청구로 따로 넣으므로 '법인카드' · '개인카드' 는 고르지 않는다.
- 지출일자(expenseDate): 세금계산서(또는 계산서)의 작성일. 'YYYY-MM-DD'. 없으면 빈 문자열.
- 청구액(amount)은 세금계산서의 합계 금액(공급가액+세액). 공급가액(supplyAmount)·부가세(taxAmount)도 세금계산서에서. 숫자만 적는다(콤마·'원' 없이). 서류마다 금액이 다르면 notes 에 어떤 서류가 어떻게 다른지 적는다.
- 입금처(payeeName): 세금계산서의 공급자 상호. 사업자등록번호(payeeBizNo)는 '000-00-00000' 형식.
- 은행(bank)·계좌번호(accountNo)·예금주(owner): 통장사본, 없으면 세금계산서·견적서에 적힌 입금 계좌. 예금주가 거래처 상호와 다르면 notes 에 적는다.
- 결제방법(settleMethod): 서류에 다른 표시가 없으면 '계좌이체'.
- 첨부(attachments): ERP 에 올릴 만한 파일의 이름 목록. 폴더 안의 실제 파일 이름만 적는다.
- 못 찾은 값은 빈 문자열(금액은 null)로 둔다. 추측 금지. 지어내지 않는다."""


def load_rules() -> str:
    """일반청구규칙.txt 가 있으면 그 내용을 쓴다. 손대지 않은 파일은 최신 기본 규칙으로 갈아 둔다."""
    path = str(settings.claims_rules_path())
    base = str(settings.claims_rules_base_path())
    try:
        import os
        if os.path.exists(path):
            cur = _read_text(path)
            was = _read_text(base) if os.path.exists(base) else ""
            if cur.strip() and cur.strip() != was.strip():
                body = "\n".join(l for l in cur.splitlines()
                                 if not l.lstrip().startswith("#")).strip()
                if body:
                    return body          # 담당자가 고친 규칙
        for p in (path, base):
            with open(p, "w", encoding="utf-8") as f:
                f.write(RULES_HEADER + RULES_DEFAULT + "\n")
    except Exception:
        log("일반청구 규칙 파일 처리 실패\n" + traceback.format_exc())
    return RULES_DEFAULT
