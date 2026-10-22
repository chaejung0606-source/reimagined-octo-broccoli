"""파일 이름 짓기 · 비목 판정 · 저장 위치.

파일명:  0N_(YYMMDD) 적요_이체자_(금액).pdf   (설정에 따라 0N_ 없이도)
  0N     = 비목 번호. 못 정하면 00
  YYMMDD = 지출예정일. 이체일자가 아직 공란인 신규 건도 이 기준 — 기존 보관본과 같다.
  적요   = ERP 내용에서 선행 '0N_' 비목 접두어를 뗀 것
  이체자 = 1명이면 이름, 2명 이상이면 '첫이름 등 N명'
  금액   = 천 단위 콤마

비목 판정 순서: 적요 선행 0N_ → 적요 안 […] 비목명 → 상세 표 '비목' 열
               → 상세 전체 텍스트에서 금액 줄의 비목명. 못 정하면 '00. 미분류'.

대응자금 과제는 비목이 사업비와 다르다(담당자 2026-10-21) — 과제정보 → 예산 탭의 비목을 차례대로 01 · 02 … 로 번호를 붙이고
(row['budget']), 비목은 이름으로만 정한다(budget_code).
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


# 대응자금 과제 — 담당자 2026-10-21 "대응자금은 사업비와 비목이 다릅니다" · "과제정보-예산에서 확인하고 순서대로 숫자를 붙여주세요".
# 예산 탭 예산내역(실측 그림: 비목코드 A10110002 장학금 · A10110012 연구시설/장비비)의 차례가 번호다. 이름에 이 말이 든 과제가 그렇다.
# 연구지원비 과제(2025081N0001)도 그렇다 — 2026-10-22 첫 받기에서 청구서 15건이 모두 사업비 '01. 인건비' 로 들어갔다. 그 과제 청구서의 비목 표는
# 인건비 · 연구시설/장비비 · 연구활동비 셋이고(카드 결제 · 맥북 구입 · 학회 여비 · 강사료는 연구활동비 · 연구시설/장비비였다), 적요에 0N_ 이 없다.
OWN_BUDGET = ("대응자금", "연구지원비")


def own_budget(*names) -> bool:
    """과제 이름(과제 폴더 · ERP 과제명) 중에 '대응자금' · '연구지원비' 가 있는지 — 그 과제는 비목 번호를 예산 탭 차례로 붙인다."""
    flat = [re.sub(r"\s", "", str(n or "")) for n in names]
    return any(word in name for name in flat for word in OWN_BUDGET)


def budget_code(budget, remark: str, info: dict, amt) -> str:
    """예산 탭 비목([[비목코드, 비목명], …] 차례대로)에서 이 청구서의 번호('01' …). 못 정하면 ''.

    적요 앞의 '0N_' 은 사업비 번호일 수 있어 보지 않는다 — 상세 표 '비목' 열 → 적요 안 […] → 상세 글에서 금액 줄 → 상세 글 전체에 하나만
    나오는 비목 → 예산 비목이 하나뿐이면 그것. 둘 이상이 맞으면 고르지 않는다(엉뚱한 폴더보다 미분류가 낫다)."""
    items = [(i, normnm(bc).upper(), normnm(nm)) for i, (bc, nm) in enumerate(budget or [], 1)]

    def match(value) -> str:
        v = normnm(value)
        if len(v) < 2:
            return ""
        for keys in ([i for i, bc, _nm in items if bc and bc == v.upper()],
                     [i for i, _bc, nm in items if nm == v],
                     [i for i, _bc, nm in items if nm and (nm in v or v in nm)]):
            if len(set(keys)) == 1:
                return "%02d" % keys[0]
            if keys:
                return ""
        return ""

    for value in [info.get("bimok")] + re.findall(r"\[([^\]]{2,40})\]", remark or ""):
        code = match(value)
        if code:
            return code
    full = info.get("full") or ""
    try:
        money = "{:,}".format(abs(int(amt))) if amt else ""
    except (TypeError, ValueError):
        money = ""
    lines = [ln for ln in re.split(r"[\r\n]+", full) if money and money in ln] + [full]
    for text in lines:
        flat = normnm(text)
        hit = {i for i, _bc, nm in items if nm and nm in flat}
        if len(hit) == 1:
            return "%02d" % hit.pop()
    return "01" if len(items) == 1 else ""


def budget_label(name) -> str:
    """예산 비목 이름 → 폴더 이름 뒷부분. 사업비 폴더처럼 가운뎃점 · 빗금을 뗀다('연구시설/장비비' → '연구시설장비비')."""
    return safe_name(re.sub(r"[·ㆍ・/\\]", "", str(name or ""))) or "비목"


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
    if row.get("budget"):
        # 대응자금 — 비목이 사업비와 달라 사업비 이름표(BIMOK)로 정하지 않는다
        code = budget_code(row["budget"], remark, info, row.get("amt"))
    else:
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


def folder_name(code: str, budget=None) -> str:
    """비목 폴더 이름. budget(대응자금의 예산 탭 비목)이 있으면 'NN. 비목명' — 번호는 예산 탭 차례."""
    if budget:
        try:
            return "%s. %s" % (code, budget_label(budget[int(code) - 1][1])) if int(code) >= 1 else UNSORTED
        except (ValueError, IndexError, TypeError):
            return UNSORTED
    return BIMOK.get(code, UNSORTED)


def budget_folder(root: Path, code: str, budget) -> Path:
    """대응자금 비목 폴더 — 담당자가 이미 만든 같은 번호 · 같은 이름(띄어쓰기 · 가운뎃점 무시)의 폴더가 있으면 그것('02. 연구시설·장비비')."""
    name = folder_name(code, budget)
    if name != UNSORTED:
        want = normnm(name.split(" ", 1)[1])
        try:
            for entry in sorted(root.iterdir()):
                head, _, rest = entry.name.partition(".")
                if entry.is_dir() and head.strip() == code and normnm(rest) == want:
                    return entry
        except OSError:
            pass
    return root / name


def ensure_not_upload(path: Path) -> None:
    """`업로드/` 아래에는 절대 쓰지 않는다.

    업로드 폴더는 '플랫폼에 올렸음' 을 뜻하는 사용자의 표시다. 앱이 거기에
    파일을 두면 올리지 않은 건이 올린 것처럼 보여 누락으로 이어진다.
    """
    if UPLOAD_DIR in Path(path).parts:
        raise RuntimeError(f"'{UPLOAD_DIR}' 폴더에는 쓰지 않습니다: {path}")


MAX_PATH = 240       # 윈도우 경로 한도(259)보다 여유 있게 — 넘으면 저장은 되는데 파이썬이 못 찾아 '저장 실패' 가 됐다


def fit_name(fname: str, room: int) -> str:
    """파일 이름이 room 글자를 넘으면 적요 부분을 줄인다 — 앞의 '0N_(날짜) ' 와 뒤의 '_이체자_(금액)' 은 남긴다."""
    if len(fname) <= room:
        return fname
    base, ext = fname[:-4], fname[-4:]
    head_end = base.find(") ") + 2 if ") " in base else 0
    tail_at = base.rfind("_(")
    if tail_at > head_end:
        owner_at = base.rfind("_", head_end, tail_at)
        if owner_at > head_end:
            tail_at = owner_at
    else:
        tail_at = len(base)
    head, middle, tail = base[:head_end], base[head_end:tail_at], base[tail_at:]
    keep = room - len(ext) - len(head) - len(tail) - 1
    if keep < 8:
        return base[:max(room - len(ext), 1)] + ext
    return head + middle[:keep].rstrip() + "…" + tail + ext


def destination(out_root: str | Path, code: str, fname: str, budget=None) -> Path:
    """비목 폴더 바로 아래의 저장 경로. 같은 이름이 있으면 덮어쓰지 않고 _2, _3. 경로가 길면 적요를 줄인다.
    budget(대응자금의 예산 탭 비목)이 있으면 비목 폴더는 'NN. 비목명'(folder_name)."""
    folder = budget_folder(Path(out_root), code, budget) if budget else Path(out_root) / folder_name(code)
    fname = fit_name(fname, MAX_PATH - len(str(folder)) - 1 - 3)      # 3 = 겹칠 때 붙는 _NN
    dest = folder / fname
    if dest.exists():
        base = fname[:-4]
        n = 2
        while (folder / f"{base}_{n}.pdf").exists():
            n += 1
        dest = folder / f"{base}_{n}.pdf"
    # 저장 폴더 자체가 '업로드' 안에 잡혀 있어도 막는다 — 전에는 저장 폴더 아래만 보았다(2026-10-14 점검)
    ensure_not_upload(dest)
    return dest
