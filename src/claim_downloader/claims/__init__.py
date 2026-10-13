"""일반청구 작성 — 지출 1건의 자료 폴더에서 값을 뽑아 ERP 일반청구 화면에 채운다. 저장·신청은 사람이.

    지출 폴더 + 규칙(rules.py)  ──[ extract.py: Claude Code ]──▶  dict(schema.py)
         ──▶ 화면에서 사람이 고침 ──▶ form.py 가 ERP 작성 화면에 채움 ──▶ 요약 ──▶ 사람이 [저장]·[신청]

회의록 생성(minutes/)과 같은 구조다. 다른 점은 결과가 문서가 아니라 ERP 화면의 값이라는 것뿐.
안전 원칙(CLAUDE.md 9절): 저장·신청·삭제·초기화는 코드가 절대 누르지 않는다(form.FORBIDDEN_TEXTS,
tests/test_safety.py). 기본은 미리 보기(dry-run). 채운 값과 금액은 로그에 남긴다.

실측(CLAUDE.md 14절, 2026-10-13)에 없는 것 — 입금처 돋보기 팝업 · 첨부 팝업 — 은 사람이 한다.
팝업 실측이 오면 form.pick_payee 자리에 끼운다.
"""
from .process import ExtractResult, process_folder, run

__all__ = ["ExtractResult", "process_folder", "run"]
