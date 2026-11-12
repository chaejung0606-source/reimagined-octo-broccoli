"""학생이 낸 회의록 PDF 의 글자 — 회의일시 · 장소 · 주제 · 안건 · 내용 · 참석자(학번)를 앱이 직접 읽는다.

담당자 2026-11-12(WE-Meet 회의비 11건 미리 보기 그림 — 모두 'AI 가 읽는 중' 이라 회의 시각 · 장소 · 참석자가 비었다 — 와 회의록 그림):
"아직 못읽는 것 같습니다" · "회의록". 그 회의록은 한글에서 PDF(PDF/A)로 저장한 표 양식이라 글자가 들어 있다 —
'회의 일시 | 장 소', '팀 명', '참 석 자'(구분 | 이름 | 학과 | 학번 | 연락처), '회의 주제', '안 건', '회의 내용'. AI 를 기다리지 않고 이 글자에서 칸을 읽는다.
못 읽은 칸만 AI(card_ai)가 채운다.

실제 PDF 의 글자 배치는 아직 못 봤다(클라우드 세션은 담당자 PC 파일을 못 읽는다). 한글 PDF 를 pypdf 로 읽으면 표 칸 차례로 나오고,
한 줄에 칸 여럿이 이어지기도(같은 높이) 칸마다 줄이 바뀌기도 한다(28절 출장신청서). 그래서 칸 이름(글자 사이 띄어쓰기 봐 줌)의 자리로 값을 자르고,
참석자 표는 머리글의 열 차례대로 칸 종류(이름 · 번호 · 전화 …)를 보며 줄을 나눈다. 못 읽으면 shape() 를 기록에 남겨 꼴을 본다.
Qt · pypdf 없음 — 글자만 받는다(card.py 가 읽는다).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import idnums

# 칸 이름 — 긴 것 먼저(‘회의 일시’ 가 ‘일시’ 보다). 짧은 이름은 줄 머리이거나 앞뒤가 띄어쓰기일 때만(본문의 낱말과 헷갈리지 않게)
FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("when", ("회의일시", "회의일자", "개최일시", "회의날짜", "일시", "일자", "날짜")),
    ("place", ("회의장소", "개최장소", "장소")),
    ("team", ("팀명", "팀이름", "소학회명", "동아리명", "학회명", "프로젝트명")),
    ("people", ("참석자명단", "참석자현황", "참석인원", "참석자", "참여자")),
    ("topic", ("회의주제", "회의명", "회의목적", "주제", "목적")),
    ("agenda", ("회의안건", "안건")),
    ("content", ("회의내용및결과", "회의내용", "논의내용", "주요내용", "논의사항", "회의결과", "내용")),
)
# 회의 내용 뒤에 오는 칸 — 줄 머리에 오면 내용은 거기까지
# 긴 것은 줄 머리에 오면 거기까지, 짧은 것('기타' · '사진' …)은 그 낱말만 있는 줄일 때만(본문이 '사진 촬영은 …' 으로 시작할 수 있다)
TAILS = ("결정사항", "향후계획", "향후일정", "향후추진계획", "추진계획", "기타사항", "회의사진", "활동사진", "작성자", "작성일", "확인자",
         "참석자서명", "회의결과사진")
SHORT_TAILS = ("기타", "비고", "첨부", "붙임", "사진", "서명")
STRONG = {"회의일시", "회의일자", "개최일시", "회의날짜", "회의장소", "개최장소", "팀명", "팀이름", "소학회명", "동아리명", "학회명", "프로젝트명",
          "참석자명단", "참석자현황", "참석인원", "참석자", "참여자", "회의주제", "회의명", "회의목적", "회의안건", "회의내용및결과", "회의내용",
          "논의내용", "주요내용", "논의사항", "회의결과"}

# 참석자 표 머리글 — 열 종류
HEADS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("name", ("성명", "이름")),
    ("no", ("학번/사번", "학번", "사번", "직번", "교번", "학생번호")),
    ("org", ("소속(학과)", "학과(부서)", "소속기관", "소속", "학과", "학부", "부서", "전공", "기관")),
    ("role", ("구분", "직위", "직급", "역할", "신분", "직책")),
    ("phone", ("연락처", "전화번호", "휴대폰", "핸드폰", "전화")),
    ("mail", ("이메일", "메일", "e-mail", "email")),
    ("sign", ("서명", "비고", "확인")),
    ("seq", ("연번", "순번", "번호", "no", "No", "NO")),
)
ROLE_WORDS = {"지도교수", "교수", "담당교수", "책임교수", "참여교수", "연구교수", "대학원생", "학부생", "학생", "재학생", "졸업생", "팀장", "팀원",
              "부팀장", "조장", "조원", "회장", "부회장", "총무", "간사", "위원장", "위원", "연구원", "책임연구원", "조교", "멘토", "멘티",
              "직원", "교직원", "외부위원", "외부전문가", "전문가", "강사", "담당자", "교원", "박사", "석사", "학부", "참석자", "기업",
              "산업체", "대표", "부대표", "서기", "리더", "팀리더", "구성원", "참여학생", "참여자", "자문위원",
              "지도", "참여", "외부", "내부", "책임", "공동"}       # '지도 교수' 처럼 띄운 구분의 앞 낱말
ORG_TAILS = ("학과", "학부", "대학", "대학원", "전공", "센터", "사업단", "공학", "연구소", "본부", "회사", "학교", "캠퍼스", "㈜")
ORG_TAILS_SHORT = ("과", "원", "단", "처", "실", "팀")     # 이름 끝 글자일 수도 있어(김지원) 네 글자 넘을 때만
PHONE_RE = re.compile(r"(?<![\d\-])\(?0\d{1,2}\)?[-.\s]?\d{3,4}[-.\s]?\d{4}(?![\d\-])")
NUMBER_CELL_RE = re.compile(r"\(?(\d{6,13})\)?")
DASH_RE = re.compile(r"[-–—―=xX×/]|없음|해당없음")
DATE_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
SHORT_DATE_RE = re.compile(r"(?<!\d)(\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})(?!\d)")
TIME_RE = re.compile(r"(\d{1,2})\s*(?::|시)\s*(\d{2})?")
BULLET_RE = re.compile(r"^\s*(?:[▪■□●○◦•·\-–※▶►◆◇]+|\d{1,2}[.)]|[가-하][.)]|\(\d{1,2}\))\s*")
PAGE_LINE_RE = re.compile(r"^\s*[-–]?\s*\d{1,3}\s*[-–]?\s*$|^\s*\d{1,3}\s*/\s*\d{1,3}\s*$")
_WIDE = str.maketrans({chr(0xFF10 + i): str(i) for i in range(10)} | {"：": ":", "（": "(", "）": ")", "－": "-", "～": "~", "．": ".",
                                                                       " ": " ", "　": " "})
CONTENT_LIMIT = 1500           # 회의내용이 이보다 길면 앞부분만(문장 끝에서) — ERP 칸 한도는 모른다


@dataclass
class Parsed:
    used: dt.date | None = None
    start: str = ""
    end: str = ""
    place: str = ""
    topic: str = ""
    agenda: str = ""               # ERP 회의목적(#CFRC_PURS) 에 넣을 한 줄 — 주제가 있으면 주제, 없으면 안건
    content: list[str] = field(default_factory=list)
    people: list[tuple[str, str, str]] = field(default_factory=list)      # (소속, 이름, 학번 · 사번)
    found: list[str] = field(default_factory=list)                        # 찾은 칸 이름(값 없이 — 기록용)
    notes: list[str] = field(default_factory=list)

    def score(self) -> int:
        return sum(bool(x) for x in (self.used or self.start, self.place, self.agenda, self.content, self.people))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def normalize(text: str) -> str:
    text = str(text or "").translate(_WIDE)
    # 글꼴에 없는 글자(쌍점 · 하이픈)가 제어 문자나 사용자 정의 영역 글자로 읽히기도 한다 — '17\x1b00' · '17\ue09200' → '1700'
    # (시각 · 전화로 다시 읽는다)
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f\ue000-\uf8ff]", "", text)
    if re.search(r"(?<!\d)\d \d \d \d(?!\d)", text):             # 한 글자씩 띄운 숫자
        text = re.sub(r"(?<!\d)\d(?: \d)+(?!\d)", lambda m: m.group(0).replace(" ", ""), text)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())


def _word_re(word: str) -> str:
    return r"\s*".join(re.escape(c) for c in word)


_LABELS = sorted(((key, word) for key, words in FIELDS for word in words), key=lambda kw: -len(kw[1]))
_LABEL_RE = re.compile("|".join(f"(?P<l{n}>{_word_re(word)})" for n, (_k, word) in enumerate(_LABELS)))
_TAIL_RE = re.compile(r"^\s*(?:" + "|".join(_word_re(w) for w in sorted(TAILS, key=len, reverse=True)) + r")(?=\s|[:：]|$)")
_SHORT_TAIL_RE = re.compile(r"^\s*(?:" + "|".join(_word_re(w) for w in SHORT_TAILS) + r")\s*(?:[:：].*)?$")


def _hits(text: str) -> list[tuple[int, int, str, str]]:
    """칸 이름의 자리 (시작, 끝, 열쇠, 칸 이름) — 열쇠마다 하나(긴 칸 이름 '회의 일시' 가 있으면 그것, 없으면 처음 짧은 것),
    회의 내용 칸 뒤의 것은 보지 않는다(본문)."""
    found: list[tuple[int, int, str, str, bool]] = []
    pos = 0
    while True:
        m = _LABEL_RE.search(text, pos)
        if not m:
            break
        pos = m.start() + 1
        key, word = _LABELS[int(m.lastgroup[1:])]
        before = text[m.start() - 1] if m.start() else "\n"
        after = text[m.end()] if m.end() < len(text) else "\n"
        if re.match(r"[가-힣A-Za-z]", before) or re.match(r"[가-힣A-Za-z]", after):
            continue                                       # 더 긴 낱말의 일부('회의장소는' · '작성일자')
        strong = word in STRONG
        line_head = not text[text.rfind("\n", 0, m.start()) + 1:m.start()].strip()
        if not strong and not line_head:
            # 짧은 칸 이름이 줄 가운데 — 앞뒤가 띄어쓰기(또는 쌍점)일 때만, '내용' 은 줄 머리에서만
            if key == "content" or not before.isspace() or not (after.isspace() or after in ":："):
                continue
        found.append((m.start(), m.end(), key, word, strong))
        pos = m.end()
    contents = [h for h in found if h[2] == "content"]
    content = next((h for h in contents if h[4]), contents[0] if contents else None)
    limit = content[0] if content else len(text)
    chosen = [content[:4]] if content else []
    for key, _words in FIELDS:
        if key == "content":
            continue
        mine = [h for h in found if h[2] == key and h[0] < limit]
        pick = next((h for h in mine if h[4]), mine[0] if mine else None)
        if pick:
            chosen.append(pick[:4])
    chosen.sort()
    # 겹친 것(한 칸 이름 안의 짧은 이름)은 앞의 것만
    out: list[tuple[int, int, str, str]] = []
    for hit in chosen:
        if out and hit[0] < out[-1][1]:
            continue
        out.append(hit)
    return out


def _value(text: str, hits, index: int) -> str:
    start = hits[index][1]
    end = hits[index + 1][0] if index + 1 < len(hits) else len(text)
    return text[start:end].strip(" \n:：")


def _when(value: str) -> tuple[dt.date | None, str, str]:
    day = None
    hit = DATE_RE.search(value)
    rest = value
    if hit:
        try:
            day = dt.date(int(hit.group(1)), int(hit.group(2)), int(hit.group(3)))
        except ValueError:
            day = None
        rest = value[hit.end():]
    else:
        short = SHORT_DATE_RE.search(value)
        if short:
            try:
                day = dt.date(2000 + int(short.group(1)), int(short.group(2)), int(short.group(3)))
            except ValueError:
                day = None
            rest = value[short.end():]
    pm = "오후" in rest and "오전" not in rest
    times = []
    for h, m in TIME_RE.findall(rest):
        hour = int(h)
        if pm and hour < 12:
            hour += 12
        if hour < 24:
            times.append(f"{hour:02d}:{m or '00'}")
    if not times:
        # 글꼴에 쌍점이 없으면 '17:00' 이 '1700' 으로 읽히기도 한다(PDF 글꼴)
        times = [f"{h}:{m}" for h, m in re.findall(r"(?<![\d.])([01]\d|2[0-3])([0-5]\d)(?![\d.])", rest)]
    return day, times[0] if times else "", times[1] if len(times) > 1 else ""


def _one_line(value: str) -> str:
    parts = [BULLET_RE.sub("", line).strip() for line in value.splitlines()]
    return " ".join(p for p in parts if p)


def _agenda(value: str) -> str:
    """안건 칸 — '▪안건1: …' 줄마다 머리를 떼고 ' / ' 로 이음."""
    items = []
    for line in value.splitlines():
        line = BULLET_RE.sub("", line).strip()
        line = re.sub(r"^안\s*건\s*\d*\s*[:：.)]\s*", "", line)
        if not line:
            continue
        if items and not BULLET_RE.match(line) and not re.match(r"^안\s*건", line) and len(items[-1]) > 25:
            items[-1] += " " + line                        # 앞 안건이 줄을 넘김
        else:
            items.append(line)
    return " / ".join(items)


def _content(text: str) -> tuple[list[str], bool]:
    lines = []
    for line in text.splitlines():
        if _TAIL_RE.match(line) or _SHORT_TAIL_RE.match(line):
            break
        if PAGE_LINE_RE.match(line) or not line.strip():
            continue
        lines.append(line.strip())
    if not lines:
        return [], False
    longest = max(len(line) for line in lines)
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if re.search(r"(?:다|음|함|됨|요|임)\s*[.。]$|[.。]$", line) and len(line) < longest * 0.85:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    total, out, cut = 0, [], False
    for para in paragraphs:
        if total + len(para) > CONTENT_LIMIT:
            room = CONTENT_LIMIT - total
            head = para[:room]
            end = max(head.rfind(". "), head.rfind("다."))
            if end > 40:
                out.append(head[:end + (2 if head[end:end + 2] == "다." else 1)].strip())
            cut = True
            break
        out.append(para)
        total += len(para)
    return out, cut


# ── 참석자 표 ──────────────────────────────────────────────────────
def _head_kind(token: str) -> str:
    t = token.strip().lower()
    for kind, words in HEADS:
        if t in {w.lower() for w in words}:
            return kind
    return ""


def _merge_spaced(tokens: list[str]) -> list[tuple[str, int]]:
    """'이 름' · '연 락 처' 처럼 한 글자씩 띄운 머리글을 붙인다(머리글 낱말이 될 때만). (낱말, 원래 목록에서 그다음 자리)."""
    out: list[tuple[str, int]] = []
    i = 0
    while i < len(tokens):
        merged = False
        if len(tokens[i]) == 1:
            for n in (4, 3, 2):
                if i + n <= len(tokens) and all(len(t) == 1 for t in tokens[i:i + n]):
                    word = "".join(tokens[i:i + n])
                    if _head_kind(word) or word == "참석자":
                        out.append((word, i + n))
                        i += n
                        merged = True
                        break
        if not merged:
            out.append((tokens[i], i + 1))
            i += 1
    return out


def _is_name(token: str) -> bool:
    t = token.strip()
    if t in ROLE_WORDS or t.endswith(("교수", "학생", "조교")) or _head_kind(t):
        return False
    if re.fullmatch(r"[가-힣]{2,5}", t):
        return not (t.endswith(ORG_TAILS) or (len(t) > 3 and t.endswith(ORG_TAILS_SHORT)))
    return False


def _is_number(token: str) -> bool:
    hit = NUMBER_CELL_RE.fullmatch(token.strip())
    return bool(hit) and not idnums._phone_like(hit.group(1))


def _is_dash(token: str) -> bool:
    return bool(DASH_RE.fullmatch(token.strip()))


def _is_phone(token: str) -> bool:
    # 글꼴에 하이픈이 없으면 '010-1111-2222' 가 '01011112222' 로 읽히기도 한다
    return bool(PHONE_RE.fullmatch(token.strip()) or re.fullmatch(r"0\d{8,10}", token.strip()))


def _people(region: str, value: str = "") -> tuple[list[tuple[str, str, str]], str]:
    """참석자 칸의 글 → (소속, 이름, 번호) 줄들과 읽은 방법('표' · '이름 나열' · ''). region 은 표를 찾을 넓은 글, value 는 '참석자' 칸의 값만."""
    raw = region.split()
    merged = _merge_spaced(raw)
    # 머리글 — 처음 나오는 머리글 낱말이 이어진 무리(이름 열이 있어야). 띄운 글자는 머리글에서만 붙인다(학과 칸 '데 이 터 …' 는 그대로)
    start = next((i for i, (t, _e) in enumerate(merged) if _head_kind(t)), None)
    cols: list[str] = []
    if start is not None:
        i = start
        while i < len(merged) and _head_kind(merged[i][0]):
            cols.append(_head_kind(merged[i][0]))
            i += 1
        if "name" in cols:
            rest = raw[merged[i - 1][1]:]
            # 합친 '참 석 자' 칸 이름이 표 가운데에 읽혔으면 뺀다
            words = _merge_spaced(rest)
            tokens = [w for w, _e in words if w != "참석자"] if any(w == "참석자" for w, _e in words) else rest
            rows = _table_rows(tokens, cols)
            if rows:
                return rows, "표"
    # 표가 아니면 '홍길동, 김철수(컴퓨터공학과) …' 처럼 이름을 늘어놓은 것
    rows = []
    for token in re.split(r"[,、·/\s]+", value or region):
        token = re.sub(r"[()\[\]]", " ", token).strip()
        name = token.split(" ")[0] if token else ""
        if _is_name(name) and name not in [r[1] for r in rows]:
            rows.append(("", name, ""))
    return (rows, "이름 나열") if len(rows) >= 2 else ([], "")


def _table_rows(tokens: list[str], cols: list[str]) -> list[tuple[str, str, str]]:
    """머리글 열 차례로 칸 종류를 보며 줄을 나눈다 — 빈 칸(학번 없음 등)은 그 종류의 낱말이 안 오면 건너뛴다."""
    rows: list[tuple[str, str, str]] = []
    i, guard = 0, 0
    while i < len(tokens) and len(rows) < 80 and guard < 400:
        guard += 1
        start = i
        cells: dict[str, str] = {}
        for n, kind in enumerate(cols):
            if i >= len(tokens):
                break
            tok = tokens[i]
            nxt = cols[n + 1] if n + 1 < len(cols) else ""
            if kind == "seq":
                if re.fullmatch(r"\d{1,3}", tok):
                    i += 1
            elif kind == "role":
                if not _is_name(tok) or (i + 1 < len(tokens) and _is_name(tokens[i + 1]) and nxt == "name"):
                    taken = [tok]
                    i += 1
                    # '지도 교수' 처럼 두 낱말 — 다음 것도 이름이 아니고 그다음이 이름일 때
                    if nxt == "name" and i + 1 < len(tokens) and not _is_name(tokens[i]) and _is_name(tokens[i + 1]) \
                            and not _is_number(tokens[i]) and not _is_phone(tokens[i]):
                        taken.append(tokens[i])
                        i += 1
                    cells["role"] = " ".join(taken)
            elif kind == "name":
                if _is_name(tok):
                    cells["name"] = tok
                    i += 1
                elif re.fullmatch(r"[A-Za-z][A-Za-z.\-']*", tok):             # 외국인 이름 — 영문 낱말이 이어진 것
                    taken = []
                    while i < len(tokens) and re.fullmatch(r"[A-Za-z][A-Za-z.\-']*", tokens[i]):
                        taken.append(tokens[i])
                        i += 1
                    cells["name"] = " ".join(taken)
                else:
                    break
            elif kind == "org":
                taken = []
                while i < len(tokens):
                    t = tokens[i]
                    if taken and (_is_number(t) or _is_phone(t) or (_is_dash(t) and nxt in ("no", "phone"))):
                        break
                    if taken and nxt in ("", "role") and (t in ROLE_WORDS or (nxt == "" and _is_name(t))):
                        break
                    if taken and nxt == "name" and _is_name(t):
                        break
                    if not taken and (_is_number(t) or _is_phone(t)):
                        break
                    if not taken and _is_dash(t):
                        i += 1
                        break
                    taken.append(t)
                    i += 1
                    # 마지막 열이면 한 낱말. 한 글자씩 띄워 읽힌 학과('데 이 터 사 이 언 스 학 과')는 길게
                    if nxt == "" or len(taken) >= (16 if all(len(x) == 1 for x in taken) else 4):
                        break
                cells["org"] = "".join(taken) if taken and all(len(t) == 1 for t in taken) else " ".join(taken)
            elif kind == "no":
                if _is_number(tok):
                    cells["no"] = idnums.clean(tok)
                    i += 1
                elif _is_dash(tok):
                    i += 1
            elif kind == "phone":
                if _is_phone(tok) or _is_dash(tok):
                    i += 1
            elif kind == "mail":
                if "@" in tok:
                    i += 1
            # sign · 그 밖 — 글자가 없는 칸이 많아 건너뛴다
        if cells.get("name"):
            rows.append((cells.get("org", ""), cells["name"], cells.get("no", "")))
        if i == start:
            i += 1                                         # 한 줄도 못 읽으면 한 낱말 넘겨 다시 맞춘다
    return rows


# ── 전체 ───────────────────────────────────────────────────────────
def looks_like(text: str, name: str = "") -> bool:
    """회의록 PDF 같은가 — 이름에 '회의록', 또는 첫머리에 '회의록' 이 있고 회의일시 · 참석자 · 회의내용 칸 가운데 둘. 공문(수신 · 시행)은 아니다."""
    flat = _squash(text[:3000])
    if not flat:
        return False
    if "회의록" in name.replace(" ", ""):
        return True
    if "공문" in name or ("수신" in flat[:400] and ("시행" in flat or "발신" in flat)):
        return False
    labels = sum(any(w in flat for w in words) for words in (("회의일시", "일시"), ("참석자",), ("회의내용", "논의내용", "주요내용")))
    return "회의록" in flat[:300] and labels >= 2


def parse(text: str) -> Parsed:
    text = normalize(text)
    out = Parsed()
    hits = _hits(text)
    values = {key: _value(text, hits, n) for n, (_s, _e, key, _w) in enumerate(hits) if key != "content"}
    if "when" in values:
        out.used, out.start, out.end = _when(values["when"])
    if "place" in values:
        out.place = _one_line(values["place"])[:120]
        if DATE_RE.search(out.place) or TIME_RE.fullmatch(out.place):
            out.place = ""
    if "topic" in values:
        out.topic = _one_line(values["topic"])[:200]
    if "agenda" in values:
        out.agenda = _agenda(values["agenda"])[:300]
    if not out.agenda and out.topic:
        out.agenda = out.topic
    elif out.topic:
        out.agenda = out.topic                             # 회의목적은 한 줄 — 주제가 있으면 주제
    content = next((n for n, h in enumerate(hits) if h[2] == "content"), None)
    if content is not None:
        out.content, cut = _content(text[hits[content][1]:])
        if cut:
            out.notes.append(f"회의내용이 길어 앞 {CONTENT_LIMIT}자 안쪽만 넣음")
    if "people" in values:
        # 표 머리글 · 줄이 '참 석 자' 칸 이름보다 앞에 읽혔을 수 있어(합친 칸) 앞 칸의 값부터 본다 — 머리글 낱말에서 시작하므로 앞 값은 건너뛴다
        n = next(k for k, h in enumerate(hits) if h[2] == "people")
        wide = text[hits[n - 1][1] if n else 0:hits[n + 1][0] if n + 1 < len(hits) else len(text)]
        out.people, how = _people(wide, values["people"])
        if how:
            out.found.append(f"참석자({how} {len(out.people)}명 · 번호 {sum(1 for p in out.people if p[2])}명)")
    for key, label in (("when", "일시"), ("place", "장소"), ("topic", "주제"), ("agenda", "안건")):
        if key in values and (key != "when" or out.used or out.start):
            out.found.append(label)
    if out.content:
        out.found.append("내용")
    return out


def shape(text: str, limit: int = 40) -> list[str]:
    """회의록 PDF 의 글 모양 — 칸을 못 읽었을 때 기록에 남긴다. 칸 이름 · 머리글 · 숫자 꼴만 두고 다른 한글은 □, 영문은 a, 7자리 넘는 숫자는 #."""
    keep = {w for _k, words in FIELDS for w in words} | {w for _k, words in HEADS for w in words} | set(TAILS) | set(SHORT_TAILS) | ROLE_WORDS | {"회의록", "회의", "양식"}
    chars = set("".join(keep))

    def mask(m: re.Match) -> str:
        word = m.group(0)
        if word in keep or (len(word) == 1 and word in chars):
            return word
        return "□" * len(word)
    out = []
    for line in [line for line in normalize(text).splitlines() if line.strip()][:limit]:
        line = PHONE_RE.sub(lambda m: re.sub(r"\d", "9", m.group(0)), line)
        line = re.sub(r"[가-힣]+", mask, line)
        line = re.sub(r"[A-Za-z]{2,}", lambda m: "a" * len(m.group(0)), line)
        out.append(re.sub(r"\d{7,}", lambda m: "#" * len(m.group(0)), line)[:140])
    return out
