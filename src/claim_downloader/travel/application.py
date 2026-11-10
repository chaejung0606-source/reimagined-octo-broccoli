"""출장신청서 읽기 — 출장증빙을 만들 폴더를 고르면 그 안의 출장신청서에서 출장자 · 출장기간 · 출장지(목적지) · 목적을 읽는다. Qt 없음.

담당자 2026-11-10: "저장할 폴더를 고르면 그 안에 있는 출장신청서를 먼저 검토" · "출장자 구분하고" · "출장자별로 증빙 확인" ·
"출장신청서에 있는 목적지가 불분명할 경우 목적지를 입력해달라고 요청하기" · "출장신청서에 출장이 1건 이상이 있을 수 있는데
그럴땐 저장폴더명에 있는 날짜를 기준으로 출장증빙 생성" — 신청서의 출장을 모두 읽어(trips) 폴더 이름의 날짜가 든 출장을 고른다(select).

**출장신청서의 실제 모양은 아직 못 봤다**(이 환경에서는 담당자 PC 의 파일을 읽지 못한다 — CLAUDE.md 28절). 그래서 칸 이름(출장자 · 성명 ·
출장기간 · 일시 · 출장지 · 목적지 · 목적 …)을 글자 사이 띄어쓰기까지 받아 주며 찾고, 표처럼 '직급 이름' 이 나란히 적힌 줄에서도 이름을 줍는다.
읽은 값은 화면이 보여 주고 사람이 고친다 — 못 읽은 칸은 비워 두고 알린다(지어내지 않는다). 기록에는 이름을 남기지 않는다(사람 수 · 찾은 칸만).
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .model import _FULL_DATE, APPLICATION_WORDS, _make, pdf_text, split_places

# 파일 이름에 APPLICATION_WORDS(model — 띄어쓰기 무시)가 있으면 출장신청서로 본다 — 국내 출장신청서(MMDD).pdf · 출장명령서 · 출장계획서
READABLE = (".pdf", ".hwpx", ".txt")
UNREADABLE = (".hwp", ".doc", ".docx", ".jpg", ".jpeg", ".png")

# 칸 이름 — 긴 것부터 맞춘다(출장기간이 기간보다 먼저)
LABELS = {
    "travelers": ("출장자명", "출장자", "출장인원", "출장인", "동행자", "출장대상자", "성명"),
    "period": ("출장기간", "출장일시", "출장일자", "출장일정", "기간", "일시", "일정"),
    "place": ("출장지역", "출장장소", "출장지", "목적지", "출장처", "방문지", "방문처", "방문기관", "출장기관", "행선지", "용무지", "장소"),
    "purpose": ("출장목적", "출장사유", "목적", "용무", "사유"),
    "origin": ("출발지",),
}
# 표의 머리 줄('소속 직급 성명')이나 다른 칸에 쓰인 글자 — 이름으로 줍지 않는다
POSITIONS = ("교수", "부교수", "조교수", "연구교수", "초빙교수", "겸임교수", "명예교수", "강사", "연구원", "선임연구원", "책임연구원",
             "전임연구원", "연구보조원", "직원", "주무관", "팀장", "과장", "계장", "실장", "단장", "부단장", "센터장", "처장", "행정원",
             "행정직원", "조교", "학생", "대학원생", "학부생", "석사과정", "박사과정", "계약직", "사무원", "전문원", "전문위원", "연구교수",
             "교직원", "직급", "직위", "소속", "성명", "이름", "학과", "학번", "사번")
NOT_NAMES = set(POSITIONS) | {
    "출장자", "출장지", "출장비", "교통비", "숙박비", "식비", "일비", "합계", "기간", "목적", "장소", "일시", "결재", "기안", "기안자", "작성자",
    "신청자", "신청인", "담당", "담당자", "확인", "승인", "검토", "협조", "전결", "대결", "본인", "동행", "인원", "외", "명", "국내", "국외",
    "관내", "관외", "도내", "도외", "자차", "대중교통", "열차", "버스", "항공", "출발", "도착", "출발지", "목적지", "용무", "비고", "구분",
    "신청", "출장", "여비", "계", "금액", "내용", "사업단", "대학교", "강원대", "산학협력단", "해당없음", "없음", "있음", "오전", "오후",
}
ORG_TAILS = ("과", "팀", "처", "센터", "본부", "사업단", "대학", "학과", "학부", "대학교", "연구소", "학교", "위원회", "협력단", "캠퍼스", "기관")
# 결재 줄 — 여기 나오는 이름은 출장자가 아니다(기안자 · 단장 …)
APPROVAL_WORDS = ("결재", "기안", "검토", "협조", "승인", "전결", "대결", "작성자", "작성일", "신청자", "신청인", "수신", "발신", "시행")
# 목적지가 '분명하지 않은' 값 — 시 · 도 이름만이거나 묶음 말이면 네이버 지도에서 길을 찾을 수 없다(담당자 2026-11-10)
VAGUE_WORDS = ("관내", "관외", "도내", "도외", "국내", "국외", "기타", "해당없음", "미정", "일원", "일대", "등지", "각지", "인근")
REGION_TAIL = re.compile(r"(특별자치시|특별자치도|특별시|광역시|도|시|군|구)$")
MAX_PLACE = 60


@dataclass
class TripEntry:
    """신청서 안의 출장 하나 — 양식이 되풀이되거나(출장마다 한 장) 표에 출장이 줄마다 적힌 신청서가 있다."""
    start: date | None = None
    end: date | None = None
    places: list[str] = field(default_factory=list)
    purpose: str = ""
    origin: str = ""
    travelers: list[str] = field(default_factory=list)

    def label(self) -> str:
        if self.start:
            end = self.end or self.start
            period = f"{self.start:%Y-%m-%d}" + (f" ~ {end:%m-%d}" if end != self.start else "")
        else:
            period = "기간 모름"
        return f"{period} · {', '.join(self.places) or '출장지 모름'}"

    def overlaps(self, other: "TripEntry") -> bool:
        if not (self.start and other.start):
            return False
        return self.start <= (other.end or other.start) and other.start <= (self.end or self.start)


@dataclass
class Application:
    path: Path
    travelers: list[str] = field(default_factory=list)
    start: date | None = None
    end: date | None = None
    places: list[str] = field(default_factory=list)
    purpose: str = ""
    origin: str = ""
    expected: int | None = None        # '홍길동 외 2명' 처럼 적힌 사람 수 — 읽은 이름 수와 다르면 알린다
    found: list[str] = field(default_factory=list)      # 찾은 칸(출장자 · 출장기간 · 출장지 · 목적 · 출발지)
    notes: list[str] = field(default_factory=list)
    trips: list[TripEntry] = field(default_factory=list)   # 신청서에 적힌 출장들 — 둘 이상이면 폴더 이름의 날짜로 고른다
    chosen: int = 0
    everyone: list[str] = field(default_factory=list)      # 모든 출장의 출장자(고른 출장에 출장자가 따로 없을 때)
    shape: list[str] = field(default_factory=list)         # 못 읽은 칸이 있을 때 글 모양(이름 가림) — 기록에 남긴다

    @property
    def destination(self) -> str:
        return ", ".join(self.places)


# ── 찾기 · 글자 ─────────────────────────────────────────────────────────
def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def find(folder: Path) -> list[Path]:
    """폴더(아래 두 단계까지)에서 이름에 출장신청 · 출장명령 … 이 든 파일. 만든 출장증빙 · 임시 파일은 뺀다."""
    out = []
    folder = Path(folder)
    for path in sorted(folder.rglob("*")):
        try:
            depth = len(path.relative_to(folder).parts)
        except ValueError:
            continue
        if depth > 3 or not path.is_file() or path.name.startswith(("~$", ".")):
            continue
        stem = _squash(path.stem)
        if "출장증빙" in stem or not any(w in stem for w in APPLICATION_WORDS):
            continue
        if path.suffix.lower() in READABLE + UNREADABLE:
            out.append(path)
    # 읽을 수 있는 것을 먼저 — 같은 신청서를 한글 · PDF 둘로 두는 일이 많다
    return sorted(out, key=lambda p: (p.suffix.lower() not in READABLE, p.name))


def hwpx_text(path: Path) -> str:
    """한글 .hwpx(압축 XML)의 본문 글자 — 문단마다 한 줄, 표 칸은 띄어쓰기로."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = sorted(n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml$", n))
            chunks = [zf.read(n).decode("utf-8", "ignore") for n in names]
    except (OSError, zipfile.BadZipFile, KeyError):
        return ""
    text = "\n".join(chunks)
    text = re.sub(r"</hp:p>", "\n", text)
    text = re.sub(r"</hp:tc>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(a, b)
    return text


def read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_text(path, pages=6)
    if suffix == ".hwpx":
        return hwpx_text(path)
    if suffix == ".txt":
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
    return ""


# ── 칸 읽기 ─────────────────────────────────────────────────────────────
def _label_re(label: str) -> str:
    # PDF 는 '출 장 기 간' 처럼 글자 사이를 띄우기도 한다
    return r"\s*".join(re.escape(ch) for ch in label)


# 줄 머리의 번호 · 기호 — '1.' · '①' · '○' 와 공문의 '가.' '나)' 도(2026-11-10 실제 신청서에서 기간 · 출장지를 못 읽음)
_LEAD = r"^[\s\d.()\[\]①-⑳□■○●◎▶▷·\-*]*(?:[가나다라마바사아자차카타파하]\s*[.)]\s*)?"


def _match_label(line: str) -> tuple[str, str] | None:
    """줄 머리의 칸 이름 → (칸, 나머지 글자). 칸 이름 바로 뒤가 한글이면(예: '기간제') 칸이 아니다."""
    for key, labels in LABELS.items():
        for label in sorted(labels, key=len, reverse=True):
            m = re.match(_LEAD + _label_re(label) + r"(?![가-힣])\s*[:：]?\s*(.*)$", line)
            if m:
                return key, m.group(1).strip()
    return None


def _lines(text: str) -> list[str]:
    return [re.sub(r"[ \t 　]+", " ", line).strip() for line in (text or "").splitlines() if line.strip()]


def _is_label_line(line: str) -> bool:
    return _match_label(line) is not None


_OTHER_LABELS = tuple(_squash(w) for key in ("period", "place", "purpose") for w in LABELS[key] if len(w) > 2)


def _ends_people(line: str) -> bool:
    """출장자 칸 아래로 이어 읽다가 멈출 줄 — 날짜가 든 줄(출장 표의 줄) · 결재 줄 · 다른 칸 이름이 든 머리 줄."""
    squashed = _squash(line)
    return bool(_FULL_DATE.search(line)) or any(w in squashed for w in APPROVAL_WORDS) or any(w in squashed for w in _OTHER_LABELS)


def _value(lines: list[str], i: int, rest: str, more: int = 0, people: bool = False) -> str:
    """칸 값 — 같은 줄에 없으면 다음 줄. more 만큼 다음 줄을 더 붙인다(다음 칸 이름이 나오면 멈춘다 — 출장자 칸이면 날짜 줄 · 결재 줄에서도)."""
    parts = [rest] if rest else []
    j = i + 1
    if not rest and j < len(lines) and not _is_label_line(lines[j]):
        parts.append(lines[j])
        j += 1
    for _ in range(more):
        if j >= len(lines) or _is_label_line(lines[j]) or (people and _ends_people(lines[j])):
            break
        parts.append(lines[j])
        j += 1
    return " ".join(parts).strip()


_WIDE = str.maketrans("０１２３４５６７８９．～：（）－／", "0123456789.~:()-/")


def _normalize(text: str) -> str:
    """PDF 글자 고르기 — 전각 숫자 · 기호를 반각으로, 한 글자씩 띄운 숫자('2 0 2 6 . 1 1 . 1 0')는 붙인다(한글에서 PDF 로 저장하면 그렇게 나오기도 한다)."""
    text = (text or "").translate(_WIDE)
    if re.search(r"(?<!\d)\d \d \d \d(?!\d)", text):
        text = re.sub(r"(?<!\d)\d(?: \d)+(?!\d)", lambda m: m.group(0).replace(" ", ""), text)
    return text


# 해가 없는 기간 — '11. 10.(화) ~ 11. 12.(목)' · '11월 10일 ~ 12일' · '11.10 부터 11.12'
_MD_RANGE = re.compile(r"(?<![\d.])(\d{1,2})\s*[.월/]\s*(\d{1,2})\s*일?[^~∼〜\n]{0,24}?(?:[~∼〜]|부터)\s*(?:(\d{1,2})\s*[.월/]\s*)?(\d{1,2})(?!\d)")


def parse_period(text: str, year: int | None = None) -> tuple[date | None, date | None]:
    """'2026. 11. 10.(화) 09:00 ~ 2026. 11. 12.(목)' · '2026-11-10 ~ 11-12' · '2026.11.10' → (시작, 끝).
    해가 없는 꼴('11. 10. ~ 11. 12.')은 year(신청서의 다른 날짜 · 폴더 날짜의 해)가 있을 때만."""
    text = _normalize(text)
    full = [(_make(*(int(g) for g in m.groups())), m.end()) for m in _FULL_DATE.finditer(text or "")]
    full = [(d, end) for d, end in full if d]
    if not full:
        m = _MD_RANGE.search(text or "") if year else None
        if not m:
            return None, None
        start = _make(year, int(m.group(1)), int(m.group(2)))
        if start is None:
            return None, None
        month = int(m.group(3)) if m.group(3) else start.month
        end = _make(year, month, int(m.group(4)))
        if end and end < start:
            end = _make(year + 1, month, int(m.group(4)))
        return start, end or start
    start, after = full[0]
    if len(full) > 1:
        return start, full[1][0]
    # 끝 날에 해가 없는 꼴 — '~ 11. 12.' · '~ 11월 12일' · '~ 12일' · '부터 11. 12.'
    tail = (text or "")[after:]
    m = re.search(r"(?:[~∼〜]|부터)\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})", tail)
    if m:
        end = _make(start.year, int(m.group(1)), int(m.group(2)))
        if end and end < start:
            end = _make(start.year + 1, int(m.group(1)), int(m.group(2)))
        return start, end or start
    m = re.search(r"(?:[~∼〜]|부터)\s*(\d{1,2})\s*일", tail)
    if m:
        return start, _make(start.year, start.month, int(m.group(1))) or start
    return start, start


_RANGE = re.compile(r"(20\d{2}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}[^~∼〜\n]{0,24}[~∼〜][^\n]{0,30})")


def _names_in(text: str) -> list[str]:
    """글자에서 사람 이름(한글 2~4자)을 줍는다 — 직급 · 칸 이름 · 기관 이름은 뺀다."""
    out = []
    for token in re.split(r"[\s,，、·/()\[\]:：;]+", text or ""):
        token = token.strip()
        if not re.fullmatch(r"[가-힣]{2,4}", token):
            continue
        if token in NOT_NAMES or token.endswith(ORG_TAILS) or token.startswith(("출장", "외")):
            continue
        if token not in out:
            out.append(token)
    return out


_POSITION_ALT = "|".join(sorted((p for p in POSITIONS if p not in ("직급", "직위", "소속", "성명", "이름", "학과", "학번", "사번")),
                                key=len, reverse=True))
_POS_NAME = re.compile(rf"(?:{_POSITION_ALT})\s+([가-힣]{{2,4}})(?![가-힣])")
_NAME_POS = re.compile(rf"(?<![가-힣])([가-힣]{{2,4}})\s+(?:{_POSITION_ALT})(?![가-힣])")
_MORE = re.compile(r"외\s*(\d{1,2})\s*(?:명|인)")


def _names_by_position(lines: list[str]) -> list[str]:
    """표처럼 '연구원 홍길동' · '홍길동 연구원' 이 나란히 있는 줄에서 이름을 줍는다 — 결재 줄은 뺀다."""
    out = []
    for line in lines:
        if any(w in _squash(line) for w in APPROVAL_WORDS):
            continue
        for pattern in (_POS_NAME, _NAME_POS):
            for m in pattern.finditer(line):
                name = m.group(1)
                if name not in NOT_NAMES and not name.endswith(ORG_TAILS) and name not in out:
                    out.append(name)
    return out


def clean_place(value: str) -> list[str]:
    """출장지 칸 → 곳 목록. 괄호 속 설명 · 주소 꼬리는 그대로 두되 너무 긴 글은 자른다."""
    value = re.sub(r"\s+", " ", value or "").strip(" :：-")
    if not value:
        return []
    return [p[:MAX_PLACE].strip() for p in split_places(value) if p.strip()]


def vague_place(place: str) -> str:
    """목적지가 분명하지 않으면 그 까닭 — 네이버 지도에서 길을 찾을 곳(기관 · 건물 이름)이 아니라 시 · 도 이름뿐이거나 묶음 말이면.
    분명하면 ''. (담당자 2026-11-10 "목적지가 불분명할 경우 목적지를 입력해달라고 요청하기")"""
    text = (place or "").strip()
    if not text:
        return "출장신청서에서 목적지를 찾지 못했습니다"
    squashed = _squash(text)
    if any(w in squashed for w in VAGUE_WORDS) or re.search(r"외\s*\d*\s*(곳|개소|군데)", text):
        return f"목적지 '{text}' 가 여러 곳을 묶은 말이라 어디로 갔는지 분명하지 않습니다"
    words = [w for w in re.split(r"[\s,·]+", text) if w]
    if all(REGION_TAIL.search(w) or len(w) <= 2 for w in words) and len(squashed) <= 10:
        return f"목적지 '{text}' 가 지역 이름뿐이라 길찾기(네이버 지도)에 쓸 곳이 분명하지 않습니다"
    return ""


_NOT_PERIOD = ("신청일", "작성일", "기안일", "시행일", "접수", "등록일", "제출일", "결재일")


def _label_keys(line: str) -> list[str]:
    """줄 전체가 칸 이름들뿐이면 그 칸들(표의 머리 줄 '출장기간 출장지 출장목적'), 아니면 []."""
    keys, rest = [], line
    while rest.strip():
        hit = _match_label(rest)
        if not hit:
            return []
        keys.append(hit[0])
        if hit[1] == rest:
            return []
        rest = hit[1]
    return keys


def _header_runs(lines: list[str]) -> list[tuple[int, int, list[str]]]:
    """칸 이름만 있는 줄이 이어진 곳(표의 칸 이름이 먼저 다 나오고 값이 그 아래에 차례로 나오는 PDF) — (시작, 끝, 칸들)."""
    runs, i = [], 0
    while i < len(lines):
        keys, j = [], i
        while j < len(lines) and _label_keys(lines[j]):
            keys += _label_keys(lines[j])
            j += 1
        if len(keys) >= 2:
            runs.append((i, j, keys))
            i = j
        else:
            i += 1
    return runs


def _column_values(lines: list[str]) -> dict[str, str]:
    """칸 이름이 먼저 다 나오고 값이 아래에 차례로 나오는 표 — 값 줄을 칸 차례에 맞추되, 날짜가 든 줄을 기간 칸에 맞춘다."""
    out: dict[str, str] = {}
    for _start, end, keys in _header_runs(lines):
        values = []
        k = end
        while k < len(lines) and len(values) < len(keys) + 8 and not _label_keys(lines[k]):
            if not any(w in _squash(lines[k]) for w in APPROVAL_WORDS):
                values.append(lines[k])
            k += 1
        offset = 0
        if "period" in keys:
            dated = next((n for n, v in enumerate(values) if _FULL_DATE.search(_normalize(v)) or _MD_RANGE.search(_normalize(v))), None)
            if dated is not None:
                offset = dated - keys.index("period")
        for n, key in enumerate(keys):
            idx = n + offset
            if 0 <= idx < len(values) and key not in out:
                out[key] = values[idx]
    return out


def _period_block(lines: list[str]) -> tuple[date, date, int, int] | None:
    """여러 줄에 걸친 '날짜 … ~ … 날짜' — 표 칸 안에서 줄이 바뀌어 시작 날짜와 끝 날짜 사이에 옆 칸(출장지)의 글이 끼어드는 꼴.
    실제 신청서(2026-11-10 담당자 기록의 글 모양): '2026.10.20. (화) 09:00 <출장지 앞부분>' / '<출장지>' / '(..)' / '.~' / '2026.10.20. (화) 18:00'.
    시작 날짜 줄부터 8줄 안에 둘째 날짜가 있고 그 사이에 '~' · '부터' 가 있을 때만(시행일 같은 날짜와 섞지 않게). (시작, 끝, 시작 줄, 끝 줄)."""
    usable = [(n, _normalize(line)) for n, line in enumerate(lines)
              if not any(w in _squash(line) for w in APPROVAL_WORDS + _NOT_PERIOD)]
    for k, (n, line) in enumerate(usable):
        first = _FULL_DATE.search(line)
        if not first or re.search(r"[~∼〜]|부터", line[first.end():]):
            continue                                   # 그 줄에 '~' 까지 다 있으면 한 줄 기간(표의 줄마다 출장 등) — 여기서 다루지 않는다
        between = line[first.end():]
        for m, (n2, line2) in enumerate(usable[k + 1:k + 9]):
            if _match_label(line2) and not _FULL_DATE.search(line2):
                break                                  # 다음 칸(출장목적 …)으로 넘어갔다
            second = _FULL_DATE.search(line2)
            if second:
                between += " " + line2[:second.start()]
                if re.search(r"[~∼〜]|부터", between):
                    start, end = parse_period(line[first.start():] + " ~ " + line2[second.start():])
                    if start and end and end >= start and (end - start).days <= 60:
                        return start, end, n, n2
                break
            between += " " + line2
    return None


# 기간 칸 글 — 출장지 조각을 고를 때 뺀다
_PERIOD_BITS = re.compile(r"20\d{2}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}\s*[.일]?|\d{1,2}:\d{2}|\([월화수목금토일]\)|[~∼〜]|부터|까지|"
                          r"\(?\s*(?:당일|\d+\s*일간?|\d+\s*박\s*\d+\s*일)\s*\)?")


_YES_NO = {"예", "아니오", "아니요", "해당", "해당없음", "O", "X", "o", "x", "Y", "N", "유", "무"}


def _place_between(lines: list[str], first: int, last: int) -> list[str]:
    """머리 줄이 '… 출장기간 출장지' 인 표 — 기간 칸 오른쪽의 출장지 글이 기간 줄들 사이에 끼어 나온다. 그 조각들을 이어 출장지로.
    끝 날짜 줄 뒤로도 다음 칸 이름(출장목적 …)이 나오기 전까지 두 줄은 출장지가 이어진 것으로 본다."""
    pieces = []
    k = first
    while k < len(lines) and (k <= last or (k - last <= 2 and not _is_label_line(lines[k]))):
        if k > last and (_FULL_DATE.search(lines[k]) or any(w in _squash(lines[k]) for w in APPROVAL_WORDS)):
            break
        text = _PERIOD_BITS.sub(" ", _normalize(lines[k]))
        text = re.sub(r"\s+", " ", text).strip(" .,·-")
        # 출장지 오른쪽 칸(여비지급 대상여부 '예' · '아니오')이 같은 줄에 붙어 나온다 — 뺀다
        if re.search(r"[가-힣A-Za-z]", text) and text not in _YES_NO:
            pieces.append(text)
        k += 1
    # 표 칸 안에서 줄이 바뀐 것은 낱말 가운데서도 바뀐다('강원가명정보' / '활용지원센터') — 한글끼리는 붙이고, 괄호 앞은 띄운다
    place = ""
    for piece in pieces:
        if place and not (re.search(r"[가-힣A-Za-z0-9]$", place) and re.match(r"[가-힣A-Za-z0-9]", piece)):
            place += " "
        place += piece
    place = re.sub(r"\s*\(\s*\)\s*", " ", place).strip()
    return clean_place(place) if place else []


def _find_period(lines: list[str], year: int | None) -> tuple[date | None, date | None]:
    """칸 이름으로 못 찾은 기간 — ① 한 줄의 '날짜 ~ 날짜' ② 몇 줄에 나뉜 '날짜 … ~ … 날짜' ③ 해 없는 '11. 10. ~ 11. 12.'. 신청일 · 결재 줄은 뺀다."""
    usable = [_normalize(line) for line in lines
              if not any(w in _squash(line) for w in APPROVAL_WORDS + _NOT_PERIOD)]
    for line in usable:
        m = _RANGE.search(line)
        if m:
            found = parse_period(m.group(1))
            if found[0]:
                return found
    block = _period_block(lines)
    if block:
        return block[0], block[1]
    for i in range(len(usable)):
        joined = " ".join(usable[i:i + 3])
        if len(_FULL_DATE.findall(joined)) >= 2 and (_FULL_DATE.search(usable[i])):
            found = parse_period(joined)
            if found[0] and found[1] and found[1] >= found[0] and (found[1] - found[0]).days <= 60:
                return found
    for line in usable:
        if _MD_RANGE.search(line):
            found = parse_period(line, year)
            if found[0]:
                return found
    return None, None


def _header_order(lines: list[str]) -> tuple[int, list[str]] | None:
    """칸 이름이 한 줄에 여럿 든 머리 줄('소속 직급 성명 … 출장기간 출장지') — (줄 번호, 그 줄의 칸들 차례)."""
    for n, line in enumerate(lines):
        squashed = _squash(line)
        keys = []
        for key, labels in LABELS.items():
            spots = [squashed.find(_squash(w)) for w in labels if len(w) >= 2 and _squash(w) in squashed]
            if spots:
                keys.append((min(spots), key))
        if len(keys) >= 2 and {"period", "place"} <= {k for _, k in keys}:
            return n, [k for _, k in sorted(keys)]
    return None


def _parse_lines(lines: list[str], path: Path | None = None) -> Application:
    """출장 하나의 글 줄들 → Application. 칸 이름이 있으면 그 값, 없으면 표 모양(직급 + 이름)과 날짜 범위로."""
    app = Application(path=path or Path("출장신청서"))
    traveler_values: list[str] = []
    in_header = {n for start, end, _keys in _header_runs(lines) for n in range(start, end)}
    for i, line in enumerate(lines):
        if i in in_header:
            continue                                  # 표의 칸 이름 줄 — 값은 _column_values 가 맞춘다
        hit = _match_label(line)
        if not hit:
            continue
        key, rest = hit
        if key == "travelers":
            # 출장자 칸 아래로 표가 이어지는 일이 많다 — 다음 칸 이름이 나올 때까지 몇 줄 더
            traveler_values.append(_value(lines, i, rest, more=8, people=True))
        elif key == "period" and app.start is None:
            value = _value(lines, i, rest, more=1)
            start, end = parse_period(value)
            if start:
                app.start, app.end = start, end
                app.found.append("출장기간")
        elif key == "place" and not app.places:
            places = clean_place(_value(lines, i, rest))
            if places:
                app.places = places
                app.found.append("출장지")
        elif key == "purpose" and not app.purpose:
            app.purpose = _value(lines, i, rest)[:120]
            if app.purpose:
                app.found.append("목적")
        elif key == "origin" and not app.origin:
            app.origin = _value(lines, i, rest)[:MAX_PLACE]
            if app.origin:
                app.found.append("출발지")
    columns = _column_values(lines) if in_header else {}
    if columns.get("travelers"):
        traveler_values.append(columns["travelers"])
    if app.start is None and columns.get("period"):
        start, end = parse_period(columns["period"])
        if start:
            app.start, app.end = start, end
            app.found.append("출장기간")
    if not app.places and columns.get("place") and not _FULL_DATE.search(columns["place"]):
        app.places = clean_place(columns["place"])
        if app.places:
            app.found.append("출장지")
    if not app.purpose and columns.get("purpose"):
        app.purpose = columns["purpose"][:120]
        app.found.append("목적")
    for value in traveler_values:
        more = _MORE.search(value)
        if more and app.expected is None:
            app.expected = 1 + int(more.group(1))
        for name in _names_in(_MORE.sub(" ", value)):
            if name not in app.travelers:
                app.travelers.append(name)
    if not app.travelers:
        app.travelers = _names_by_position(lines)
    if app.travelers:
        app.found.insert(0, "출장자")
    if app.start is None:
        # 칸 이름으로 못 찾았으면 날짜 범위로 — 해가 없는 꼴은 신청서에 적힌 다른 날짜(신청일 등)의 해로
        years = [int(m.group(1)) for line in lines for m in _FULL_DATE.finditer(_normalize(line))]
        app.start, app.end = _find_period(lines, years[0] if years else None)
        if app.start:
            app.found.append("출장기간")
    if not app.places:
        # 머리 줄이 '… 출장기간 출장지' 인 표 — 출장지 글은 기간 칸의 줄들 사이에 끼어 나온다(2026-11-10 실제 신청서)
        header = _header_order(lines)
        block = _period_block(lines[header[0] + 1:]) if header else None
        if header and block and header[1].index("place") == header[1].index("period") + 1:
            first, last = block[2] + header[0] + 1, block[3] + header[0] + 1
            app.places = _place_between(lines, first, last)
            if app.places:
                app.found.append("출장지")
    if not app.travelers:
        app.notes.append("출장자 이름을 찾지 못했습니다 — 직접 적어 주세요")
    elif app.expected and app.expected != len(app.travelers):
        app.notes.append(f"신청서에 {app.expected}명으로 적혀 있는데 이름은 {len(app.travelers)}개를 읽었습니다 — 출장자를 확인하세요")
    if app.start is None:
        app.notes.append("출장기간을 찾지 못했습니다 — 직접 고르세요")
    if app.end and app.start and app.end < app.start:
        app.start, app.end = app.end, app.start
    return app


def _entry(app: Application) -> TripEntry:
    return TripEntry(app.start, app.end, list(app.places), app.purpose, app.origin, list(app.travelers))


def _sections(lines: list[str]) -> list[list[str]]:
    """같은 칸(기간 · 출장지 · 출장자)이 다시 나오거나 기간 뒤에 출장자 칸이 나오면 다음 출장의 양식으로 본다."""
    out: list[list[str]] = [[]]
    seen: set[str] = set()
    for line in lines:
        hit = _match_label(line)
        key = hit[0] if hit else ""
        if key and out[-1] and ((key in seen and key in ("period", "place", "travelers")) or (key == "travelers" and "period" in seen)):
            out.append([])
            seen = set()
        if key:
            seen.add(key)
        out[-1].append(line)
    return out


def _groups(lines: list[str]) -> list[list[str]]:
    """양식 조각을 출장마다 묶는다 — 기간이 없는 조각은 앞 출장에(맨 앞이면 첫 출장에) 붙인다."""
    groups: list[list[str]] = []
    pending: list[str] = []
    for section in _sections(lines):
        if _parse_lines(section).start is None:
            if groups:
                groups[-1] += section
            else:
                pending += section
        else:
            groups.append(pending + section)
            pending = []
    return groups or [pending]


# 표에 출장이 줄마다 적힌 신청서 — 줄 하나에 '날짜 ~ 날짜'(와 출장지)
_ROW = re.compile(r"20\d{2}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}\s*[.일]?[^~∼〜\n]{0,24}?[~∼〜]\s*(?:20\d{2}\s*[.\-/년]\s*)?"
                  r"(?:\d{1,2}\s*[.\-/월]\s*)?\d{1,2}\s*[.일]?(?:\s*\([월화수목금토일]\))?(?:\s*\d{1,2}:\d{2})?")
ROW_SKIP = ("숙박", "신청일", "작성일", "등록일", "접수", "제출")
ROW_PLACE_MAX = 25


def _row_trips(lines: list[str], names: list[str]) -> list[TripEntry]:
    out = []
    for line in lines:
        squashed = _squash(line)
        if any(w in squashed for w in APPROVAL_WORDS + ROW_SKIP):
            continue
        hit = _match_label(line)
        if hit and hit[0] != "period":
            continue
        m = _ROW.search(line)
        if not m:
            continue
        start, end = parse_period(m.group(0))
        if not start:
            continue
        rest = hit[1] if hit else line
        rest = rest.replace(m.group(0), " ")
        rest = re.sub(r"\d{1,2}:\d{2}|\([월화수목금토일]\)|(?<![가-힣])\d+(?![가-힣])", " ", rest)
        for name in names:
            rest = rest.replace(name, " ")
        rest = re.sub(r"\s+", " ", rest).strip(" |:：-")
        out.append(TripEntry(start, end, clean_place(rest) if 0 < len(rest) <= ROW_PLACE_MAX else []))
    return out


def _add_trip(trips: list[TripEntry], trip: TripEntry) -> None:
    """기간이 겹치는 출장(같은 출장의 일정 줄 · 다른 사람의 신청서)은 하나로 — 출장자를 모으고 빈 칸을 채운다."""
    same = next((t for t in trips if t.overlaps(trip)), None) if trip.start else (trips[0] if trips else None)
    if same is None:
        trips.append(trip)
        return
    for name in trip.travelers:
        if name not in same.travelers:
            same.travelers.append(name)
    same.places = same.places or list(trip.places)
    same.purpose = same.purpose or trip.purpose
    same.origin = same.origin or trip.origin
    if same.start is None:
        same.start, same.end = trip.start, trip.end


def parse_text(text: str, path: Path | None = None) -> Application:
    """출장신청서 글자 → Application. 출장이 여럿이면(양식이 되풀이되거나 표에 줄마다) trips 에 모두 — 고르기는 select."""
    lines = _lines(_normalize(text))
    parts = [_parse_lines(group, path) for group in _groups(lines)]
    app = parts[0]
    trips: list[TripEntry] = []
    for part in parts:
        if part.start or not trips:
            _add_trip(trips, _entry(part))
    if len(parts) == 1:
        rows = _row_trips(lines, app.travelers)
        if len({r.start for r in rows}) > 1:
            for row in rows:
                _add_trip(trips, row)
    everyone = []
    for part in parts:
        everyone += [n for n in part.travelers if n not in everyone]
        app.found += [f for f in part.found if f not in app.found]
        app.expected = app.expected or part.expected
    app.trips, app.everyone = trips, everyone
    if len(trips) > 1:
        app.notes = [n for n in app.notes if not n.startswith("출장기간을 찾지")]
        if not app.travelers:
            app.travelers = list(everyone)
            app.notes = [n for n in app.notes if not n.startswith("출장자 이름을 찾지")] if everyone else app.notes
    return app


# ── 출장이 여럿일 때 — 저장 폴더 이름의 날짜로 ───────────────────────────
_FOLDER_DATES = (
    (re.compile(r"(20\d{2})\s*[.\-/_년]\s*(\d{1,2})\s*[.\-/_월]\s*(\d{1,2})"), lambda g, y: (int(g[0]), int(g[1]), int(g[2]))),
    (re.compile(r"(?<!\d)(\d{2})\s*[.\-_]\s*(\d{1,2})\s*[.\-_]\s*(\d{1,2})(?!\d)"), lambda g, y: (2000 + int(g[0]), int(g[1]), int(g[2]))),
    (re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)"), lambda g, y: (2000 + int(g[0]), int(g[1]), int(g[2]))),
    (re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일?"), lambda g, y: (y, int(g[0]), int(g[1]))),
    (re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?![\d])"), lambda g, y: (y, int(g[0]), int(g[1]))),
    (re.compile(r"(?<!\d)(\d{2})(\d{2})(?!\d)"), lambda g, y: (y, int(g[0]), int(g[1]))),
)


def folder_date(name: str, year: int) -> date | None:
    """폴더 이름의 날짜 — '출장비 지급(26.05.28. 삼척)' · '26.08.26-30. 학회' · '2026-11-10 원주' · '1110 원주' · '11월 10일'.
    해가 없으면 year(신청서의 해)."""
    for pattern, parts in _FOLDER_DATES:
        for m in pattern.finditer(name or ""):
            found = _make(*parts(m.groups(), year))
            if found:
                return found
    return None


def choose(trips: list[TripEntry], folder: Path | str) -> tuple[int, str]:
    """출장 여럿 중 하나 — 폴더 이름(없으면 위 폴더 이름)의 날짜가 시작일인 출장, 없으면 그 날짜가 기간에 든 출장, 없으면 가장 가까운 출장.
    (고른 차례, 화면 · 기록에 남길 알림)."""
    if len(trips) < 2:
        return 0, ""
    year = next((t.start.year for t in trips if t.start), date.today().year)
    folder = Path(folder)
    day, where = None, ""
    for candidate in (folder.name, folder.parent.name):
        day = folder_date(candidate, year)
        if day:
            where = candidate
            break
    count = len(trips)
    if day is None:
        return 0, (f"출장신청서에 출장이 {count}건 있는데 폴더 이름에 날짜가 없어 첫 출장({trips[0].label()})으로 정했습니다 — "
                   "다른 출장이면 위 '신청서의 출장' 칸에서 고르거나 폴더 이름에 출장 날짜(예: 26.11.10)를 넣어 주세요")
    exact = [i for i, t in enumerate(trips) if t.start == day]
    inside = [i for i, t in enumerate(trips) if t.start and t.start <= day <= (t.end or t.start)]
    if exact or inside:
        i = (exact or inside)[0]
        return i, f"출장신청서의 출장 {count}건 중 폴더 이름('{where}')의 날짜 {day:%Y-%m-%d} 출장({trips[i].label()})으로 만듭니다"
    dated = [i for i, t in enumerate(trips) if t.start]
    if not dated:
        return 0, f"출장신청서의 출장 {count}건에 기간이 없어 첫 출장으로 정했습니다 — 출장기간을 확인하세요"
    i = min(dated, key=lambda k: abs((trips[k].start - day).days))
    return i, (f"폴더 이름의 날짜 {day:%Y-%m-%d} 와 맞는 출장이 신청서에 없어 가장 가까운 출장({trips[i].label()})으로 정했습니다 — "
               "'신청서의 출장' 칸에서 확인하세요")


def apply_trip(app: Application, index: int) -> Application:
    """고른 출장의 기간 · 출장지 · 목적 · 출장자를 앞에 둔다(화면이 읽는 칸)."""
    if not app.trips:
        return app
    index = max(0, min(index, len(app.trips) - 1))
    trip = app.trips[index]
    app.chosen = index
    app.start, app.end = trip.start, trip.end
    app.places = list(trip.places)
    app.purpose = trip.purpose
    app.origin = trip.origin or app.origin
    app.travelers = list(trip.travelers or app.everyone or app.travelers)
    return app


def select(app: Application | None, folder: Path | str) -> Application | None:
    """신청서에 출장이 여럿이면 저장 폴더 이름의 날짜로 하나를 고른다(담당자 2026-11-10). 하나면 그대로."""
    if app is None or len(app.trips) < 2:
        return app
    index, note = choose(app.trips, folder)
    apply_trip(app, index)
    if note:
        app.notes.insert(0, note)
    return app


# 글 모양에 남길 낱말 — 칸 이름 · 직급 · 흔한 양식 글자(사람 이름 · 곳 이름은 □ 로)
_KEEP = ({w for words in LABELS.values() for w in words} | set(POSITIONS) | NOT_NAMES | set(VAGUE_WORDS) | set(APPROVAL_WORDS)
         | set(_NOT_PERIOD) | {"신청서", "출장신청서", "출장명령서", "출장계획서", "일간", "부터", "까지", "요일", "박", "일", "월", "년", "시", "분",
                                "당일", "비고", "출장비고", "출장구분", "교통수단", "자가용", "관용차", "숙박", "부서", "학과", "대학교", "캠퍼스",
                                "본관", "회의실", "센터", "아래", "다음", "같이"}
         | set("월화수목금토일"))
_LABEL_CHARS = set("".join(w for words in LABELS.values() for w in words))


def shape(text: str, limit: int = 45) -> list[str]:
    """신청서의 글 모양 — 못 읽은 칸이 있을 때 기록에 남겨 어떤 꼴인지 본다(담당자 2026-11-10 "출장기간과 목적지를 못 읽네요").
    칸 이름 · 직급 · 양식 글자 · 숫자 · 기호만 남기고 다른 한글(이름 · 곳 · 목적)은 □, 7자리 넘는 숫자는 #."""
    def mask(m: re.Match) -> str:
        word = m.group(0)
        if word in _KEEP or (len(word) == 1 and word in _LABEL_CHARS):
            return word
        for keep in _KEEP:
            if len(keep) >= 2 and word.startswith(keep) and len(word) - len(keep) <= 1:
                return word
        return "□" * len(word)
    out = []
    for line in _lines(_normalize(text))[:limit]:
        line = re.sub(r"[가-힣]+", mask, line)
        line = re.sub(r"[A-Za-z]{2,}", lambda m: "a" * len(m.group(0)), line)
        out.append(re.sub(r"\d{7,}", lambda m: "#" * len(m.group(0)), line)[:140])
    return out


def read(path: Path) -> Application:
    suffix = path.suffix.lower()
    if suffix not in READABLE:
        app = Application(path=path)
        app.notes.append(f"{path.name}: {'한글(.hwp)' if suffix == '.hwp' else suffix} 파일은 앱이 읽지 못합니다 — PDF(또는 .hwpx)로 저장해 같은 폴더에 두면 읽습니다")
        return app
    text = read_text(path)
    if not text.strip():
        app = Application(path=path)
        app.notes.append(f"{path.name}: 글자를 읽지 못했습니다(스캔한 그림 PDF 일 수 있습니다) — 출장 정보를 직접 적어 주세요")
        return app
    app = parse_text(text, path)
    if app.start is None or not app.places:
        app.shape = shape(text)
    return app


def merge(apps: list[Application]) -> Application | None:
    """신청서가 여럿이면(사람마다 한 장 · 출장마다 한 장) 출장을 모두 모은다 — 기간이 겹치는 것은 한 출장(출장자를 모음).
    출장이 하나로 모이면 기간 · 출장지가 그것이고, 여럿이면 select 가 폴더 이름의 날짜로 고른다."""
    if not apps:
        return None
    readable = [a for a in apps if a.found] or apps
    out = Application(path=readable[0].path)
    for app in apps:
        trips = app.trips or ([_entry(app)] if (app.start or app.places or app.travelers) else [])
        for trip in trips:
            same = next((t for t in out.trips if t.overlaps(trip)), None) if trip.start else None
            if same and trip.places and same.places and trip.places != same.places:
                out.notes.append(f"{app.path.name}: 출장지가 다릅니다({', '.join(trip.places)})")
            _add_trip(out.trips, TripEntry(trip.start, trip.end, list(trip.places), trip.purpose, trip.origin, list(trip.travelers)))
        for name in app.everyone or app.travelers:
            if name not in out.everyone:
                out.everyone.append(name)
        out.expected = out.expected or app.expected
        for item in app.found:
            if item not in out.found:
                out.found.append(item)
    apply_trip(out, 0)
    if len(out.trips) == 1 and not out.travelers:
        out.travelers = list(out.everyone)
    for app in apps:
        for note in app.notes:
            if note not in out.notes and not (out.travelers and note.startswith("출장자 이름을 찾지")) \
                    and not (out.start and note.startswith("출장기간을 찾지")):
                out.notes.append(note)
    return out


def log_line(app: Application, files: list[Path]) -> str:
    """기록 한 줄 — 이름은 남기지 않는다(사람 수 · 찾은 칸 · 기간 · 출장지만)."""
    period = f"{app.start:%Y-%m-%d}~{(app.end or app.start):%Y-%m-%d}" if app.start else "기간 모름"
    trips = f" · 신청서의 출장 {len(app.trips)}건 중 {app.chosen + 1}번째" if len(app.trips) > 1 else ""
    return (f"출장신청서 읽음: {', '.join(p.name for p in files)} — 출장자 {len(app.travelers)}명 · {period} · "
            f"출장지 '{app.destination or '모름'}' · 찾은 칸: {', '.join(app.found) or '없음'}{trips}")
