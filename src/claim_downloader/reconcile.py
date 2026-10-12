"""ERP 청구내역 엑셀과 대조해 누락 찾기 (선택 기능).

엑셀의 승인 건 중 받은 기록에 없는 문서번호를 알려 준다. 여기서도 문서번호로만
맞춘다.
"""
from __future__ import annotations

import os
from collections.abc import Callable


def reconcile(excel_path: str, done: set[str], log: Callable[[str], None]) -> list[dict]:
    if not excel_path:
        return []
    if not os.path.exists(excel_path):
        log("누락검토 건너뜀 — 엑셀 파일이 없습니다: %s" % excel_path)
        return []
    try:
        import pandas as pd
    except ImportError:
        log("누락검토 건너뜀(pandas 없음). pip install pandas xlrd openpyxl")
        return []
    try:
        df = pd.read_excel(excel_path, dtype=str).fillna("")
        df.columns = [str(c).strip() for c in df.columns]
        ap = df[(df["진행구분"].str.strip() == "승인") & (df["문서번호"].str.strip() != "")
                & (df["지출일자"].str.strip() != "")]
        ap = ap[~ap["결의서구분"].str.contains("반납|자금대체", na=False)]
        miss = ap[~ap["문서번호"].str.strip().isin(done)]
    except Exception as e:     # noqa: BLE001 — 엑셀 양식이 달라도 받기 결과는 그대로 둔다
        log("누락검토 오류: %s" % e)
        return []
    log("── 누락검토: 승인 %d건 중 기록에 없는 %d건" % (len(ap), len(miss)))
    out = []
    for _, r in miss.iterrows():
        log("   누락 문서번호 %s | %s | %s" % (r["문서번호"], r.get("금액", ""), str(r.get("내용", ""))[:40]))
        out.append({"docNo": r["문서번호"], "amt": r.get("금액", ""), "cont": r.get("내용", "")})
    return out
