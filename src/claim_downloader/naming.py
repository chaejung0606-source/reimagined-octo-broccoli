"""파일 이름 짓기 · 비목 판정 · 저장 위치.

파일명:  0N_(YYMMDD) 적요_이체자_(금액).pdf   (설정에 따라 0N_ 없이도)
  0N     = 비목 번호. 못 정하면 00
  YYMMDD = 지출예정일. 이체일자가 아직 공란인 신규 건도 이 기준 — 기존 보관본과 같다.
  적요   = ERP 내용에서 선행 '0N_' 비목 접두어를 뗀 것
  이체자 = 1명이면 이름, 2명 이상이면 '첫이름 등 N명'
  금액   = 천 단위 콤마

비목 판정 순서: 적요 선행 0N_ → 적요 안 […] 비목명 → 상세 표 '비목' 열
               → 상세 전체 텍스트에서 금액 줄의 비목명. 못 정하면 '00. 미분류'.
"""
from __future__ import annotations

import re
from pathlib import Path

BIMOK = {
    "01": "01. 인건비", "02": "02. 장학금",
    "03": "03. 교육연구프로그램개발운영비", "04": "04. 교육연구환경개선비",
    "05": "05. 실험실습장비및기자재구입운영비", "06": "06. 지역연계협업지원비",
    "07": "07. 기업지원협력활동비", "08": "08. 성과활용확산지원비",
    "09": "09. 그 밖의사업운영경비", "10": "10. 간접비",
}
UNSORTED = "00. 미분류"

BIMOK_NM = {
    "01": "인건비", "02": "장학금", "03": "교육·연구프로그램 개발·운영비",
    "04": "교육·연구 환경개선비", "05": "실험·실습장비 및 기자재 구입·운영비",
    "06": "지역 연계·협업 지원비", "07": "기업 지원·협력 활동비",
    "08": "성과 활용·확산 지원비", "09": "그 밖의 사업운영 경비", "10": "간접비",
}
BIMOK_ALT = {
    "03": ["교육연구프로그램개발운영비"], "04": ["교육연구환경개선비"],
    "05": ["실험실습장비및기자재구입운영비"], "06": ["지역연계협업지원비", "지자체연계협업비용"],
    "07": ["기업지원협력활동비"], "08": ["성과활용확산지원비"], "09": ["그밖의사업운영경비", "기타운영경비"],
}

# 사용자가 플랫폼 업로드를 마친 파일을 옮겨 두는 폴더. 앱은 읽기만 한다.
UPLOAD_DIR = "업로드"

MAX_NAME = 180


def normnm(s) -> str:
    return re.sub(r"[\s·ㆍ・.,\-()\[\]{}_/\\]", "", str(s or ""))


_BK = {k: [normnm(nm)] + [normnm(x) for x in BIMOK_ALT.get(k, [])] for k, nm in BIMOK_NM.items()}


def code_of(nm) -> str:
    """비목명(띄어쓰기·가운뎃점이 제각각) → 비목 코드."""
    n = normnm(nm)
    if not n:
        return ""
    for k, arr in _BK.items():
        if n in arr:
            return k
    for k, arr in _BK.items():
        for b in arr:
            if b and (b.startswith(n) or n.startswith(b)):
                return k
    for k, arr in _BK.items():
        for b in arr:
            if b and b in n:
                return k
    return ""


def code_from_doctext(full: str, amt) -> str:
    """상세화면 전체 텍스트에서 (금회청구액과 같은 줄의) 비목명으로 코드 추정.

    줄을 못 찾으면 화면 전체에서 비목명이 딱 하나만 나올 때만 쓴다. 둘 이상이면
    추측하지 않고 미분류로 둔다 — 엉뚱한 폴더에 들어가면 찾기가 더 어렵다.
    """
    try:
        money = "{:,}".format(abs(int(amt))) if amt else ""
    except (TypeError, ValueError):
        money = ""
    if money:
        for ln in re.split(r"[\r\n]+", full or ""):
            if money in ln:
                fl = normnm(ln)
                for k, arr in _BK.items():
                    if any(b in fl for b in arr):
                        return k
    flat = normnm(full)
    hit = [k for k, arr in _BK.items() if any(b in flat for b in arr)]
    return hit[0] if len(hit) == 1 else ""


def safe_name(s) -> str:
    """윈도우 파일명 금지문자는 공백으로. '(9/11)' → '(9 11)'."""
    s = re.sub(r'[\\/:*?"<>|]', " ", str(s))
    return re.sub(r"\s+", " ", s).strip()


def fmt_owners(owners) -> str:
    if not owners:
        return ""
    if len(owners) == 1:
        return owners[0]
    return "%s 등 %d명" % (owners[0], len(owners))


def build_name(row: dict, info: dict, name_date_first: bool = False) -> tuple[str, str]:
    """(비목 코드, 파일명). 코드를 못 정하면 '00'."""
    remark = row.get("cont") or ""
    code = ""
    m = re.match(r"^\s*(0[1-9]|10)\s*[._,\-]\s*", remark)
    if m:
        code = m.group(1)
        remark = remark[m.end():].strip()
    if not code:
        for b in re.findall(r"\[([^\]]{2,40})\]", remark):
            code = code_of(b)
            if code:
                break
    if not code and info.get("bimok"):
        code = code_of(info["bimok"])
    if not code:
        code = code_from_doctext(info.get("full", ""), row.get("amt"))

    dm = re.search(r"(20\d{2})[-./]?(\d{2})[-./]?(\d{2})", str(row.get("expDt") or ""))
    ymd = (dm.group(1)[2:] + dm.group(2) + dm.group(3)) if dm else "------"
    amt = ""
    if row.get("amt"):
        try:
            amt = "{:,}".format(abs(int(row["amt"])))
        except (TypeError, ValueError):
            amt = ""
    owners = fmt_owners(info.get("owners"))

    pre = "" if name_date_first else ((code or "00") + "_")
    s = pre + "(" + ymd + ") " + safe_name(remark)
    if owners:
        s += "_" + safe_name(owners)
    if amt:
        s += "_(" + amt + ")"
    return (code or "00"), s[:MAX_NAME] + ".pdf"


def folder_name(code: str) -> str:
    return BIMOK.get(code, UNSORTED)


def ensure_not_upload(path: Path) -> None:
    """`업로드/` 아래에는 절대 쓰지 않는다.

    업로드 폴더는 '플랫폼에 올렸음' 을 뜻하는 사용자의 표시다. 앱이 거기에
    파일을 두면 올리지 않은 건이 올린 것처럼 보여 누락으로 이어진다.
    """
    if UPLOAD_DIR in Path(path).parts:
        raise RuntimeError(f"'{UPLOAD_DIR}' 폴더에는 쓰지 않습니다: {path}")


def destination(out_root: str | Path, code: str, fname: str) -> Path:
    """비목 폴더 바로 아래의 저장 경로. 같은 이름이 있으면 덮어쓰지 않고 _2, _3."""
    folder = Path(out_root) / folder_name(code)
    dest = folder / fname
    if dest.exists():
        base = fname[:-4]
        n = 2
        while (folder / f"{base}_{n}.pdf").exists():
            n += 1
        dest = folder / f"{base}_{n}.pdf"
    ensure_not_upload(dest.relative_to(out_root))
    return dest
