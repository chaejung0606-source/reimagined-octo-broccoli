"""출장증빙 — 지원 항목별 증빙과 출장 정보에서 쪽 짜임 · 숙박 지원금액을 정한다. Qt 없음.

담당자가 손으로 만들던 '<이름> 출장증빙.pdf' 의 모양(2026-10-27 그림 · 설명, CLAUDE.md 28절)을 그대로 옮긴다:
- 쪽 차례는 **체류 → 교통비 → 숙박**(담당자 지정).
- 체류: 출장이 7일 이하면 **한 쪽을 칸으로 나눠** 모든 날을 담고, 8일 이상이면 일자마다 한 쪽.
- 대중교통: (일자, 이동편)마다 한 쪽 — 같은 날이라도 열차 → 고속버스처럼 이동편이 바뀌면 나눈다. 머리 줄에 일자와 금액.
- 자차: 한 쪽에 하이패스 영수증을 **이용일자별로** 묶어 그날 금액을 적고(담당자 "이용일자별로 나눠서 금액을 작성"), 아래에 이동경로(편도 · 왕복 km)와 지도.
- 숙박: 영수증마다 숙박기간과 지원금액. 결제액이 공무원 여비 기준 상한을 넘으면 지원금액은 상한금액.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

WEEKDAYS = "월화수목금토일"

# 공무원 여비 규정 별표 2(국내 여비 지급표) 숙박비 상한액 — 2023-03-02 개정부터 1박(1일)당 실비 상한. 2인 이상 공동숙박이면 상한 × 인원(인사혁신처 해석).
# 담당자가 '공무원 여비 기준을 참고' 하라고 했다(2026-10-27). 규정이 바뀌면 이 표만 고친다 — 화면에서 출장마다 고칠 수도 있다.
LODGING_CAPS = {"서울특별시": 100_000, "광역시": 80_000, "그 밖의 지역": 70_000}
METROS = ("부산", "대구", "인천", "광주", "대전", "울산")

STAY, PUBLIC, TOLL, LODGING = "stay", "public", "toll", "lodging"
KIND_NAMES = {STAY: "체류", PUBLIC: "대중교통", TOLL: "자차(하이패스)", LODGING: "숙박"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
FILE_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}

# 체류를 한 쪽에 칸으로 나눠 담는 출장 일수(이하) — 담당자 "출장일이 7일 이하일 경우 칸을 나눠서 한페이지에"
ONE_PAGE_STAY_DAYS = 7


@dataclass
class Evidence:
    path: Path
    day: date | None = None
    amount: int | None = None
    mode: str = ""          # 대중교통 이동편(열차 · 고속버스 …)
    nights: int = 1         # 숙박 영수증 하나가 덮는 박 수


@dataclass
class Trip:
    name: str = ""
    start: date | None = None
    end: date | None = None
    origin: str = ""
    destination: str = ""
    region: str = ""        # 숙박 상한 지역 구분 — 비우면 출장지로 정한다
    lodging_cap: int | None = None   # 1박 상한을 손으로 정했으면
    people: int = 1         # 공동숙박 인원
    stay: list[Evidence] = field(default_factory=list)
    public: list[Evidence] = field(default_factory=list)
    tolls: list[Evidence] = field(default_factory=list)
    lodging: list[Evidence] = field(default_factory=list)
    route_map: Path | None = None
    km_go: float | None = None
    km_back: float | None = None

    @property
    def days(self) -> int:
        if self.start and self.end:
            return (self.end - self.start).days + 1
        dates = sorted(e.day for e in self.stay if e.day)
        return (dates[-1] - dates[0]).days + 1 if dates else len(self.stay)

    def cap_region(self) -> str:
        return self.region or lodging_region(self.destination)

    def cap(self) -> int:
        return self.lodging_cap if self.lodging_cap else LODGING_CAPS[self.cap_region()]


# ── 글자 ────────────────────────────────────────────────────────────────
def korean_date(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일"


def won(n: int | None) -> str:
    return f"{n:,}원" if n is not None else "금액 없음"


def km(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:g}km" if value != int(value) else f"{int(value)}km"


def lodging_region(place: str) -> str:
    text = re.sub(r"\s", "", place or "")
    if "서울" in text:
        return "서울특별시"
    if any(city in text for city in METROS):
        return "광역시"
    return "그 밖의 지역"


def lodging_support(ev: Evidence, cap: int, people: int = 1) -> tuple[int, int]:
    """(지원금액, 상한) — 상한 = 1박 상한 × 박 수 × 공동숙박 인원. 결제액이 넘으면 상한금액으로."""
    limit = cap * max(1, ev.nights) * max(1, people)
    paid = ev.amount or 0
    return min(paid, limit), limit


def stay_period(ev: Evidence) -> str:
    if not ev.day:
        return f"{ev.nights}박"
    out = ev.day + timedelta(days=max(1, ev.nights))
    tail = f"{out.month}월 {out.day}일" if out.year == ev.day.year else f"{out.year}년 {out.month}월 {out.day}일"
    return f"{ev.day.year}년 {ev.day.month}월 {ev.day.day}일 ~ {tail}({ev.nights}박)"


# ── 파일에서 일자 · 금액 짐작(사람이 화면에서 고친다) ─────────────────────────
_FULL_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_SHORT_DATE = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)|(?<!\d)(\d{1,2})[.\-](\d{1,2})(?!\d)|(?<![\d.])(\d{2})(\d{2})(?![\d,])")
_AMOUNT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{3,7})\s*원")


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def guess_day(text: str, year: int) -> date | None:
    match = _FULL_DATE.search(text)
    if match:
        return _make(*(int(g) for g in match.groups()))
    for match in _SHORT_DATE.finditer(text):
        g = match.groups()
        if g[0]:
            found = _make(2000 + int(g[0]), int(g[1]), int(g[2]))
        elif g[3]:
            found = _make(year, int(g[3]), int(g[4]))
        else:
            found = _make(year, int(g[5]), int(g[6]))
        if found:
            return found
    return None


def guess_amount(text: str) -> int | None:
    values = [int(v.replace(",", "")) for v in _AMOUNT.findall(text)]
    return max(values) if values else None


def pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:2])
    except Exception:
        return ""


def guess(path: Path, year: int) -> Evidence:
    """파일 이름 → (PDF 면) 글자 차례로 일자 · 금액을 짐작한다. 그림 영수증은 이름에 적힌 것만 — 화면에서 고친다."""
    stem = path.stem
    day, amount = guess_day(stem, year), guess_amount(stem)
    if (day is None or amount is None) and path.suffix.lower() == ".pdf":
        text = pdf_text(path)
        day = day or guess_day(text, year)
        amount = amount or guess_amount(text)
    return Evidence(path=path, day=day, amount=amount)


# ── 쪽 짜임 ─────────────────────────────────────────────────────────────
@dataclass
class Block:
    images: list[Path]
    captions: list[str] = field(default_factory=list)   # 그림마다 위에 적는 글(체류 칸의 일자)
    title: list[str] = field(default_factory=list)      # 그림 묶음 위의 줄(자차의 일자 · 금액, 이동경로)
    cols: int = 3
    fill: bool = False      # 남은 높이를 다 쓴다(체류 한 쪽 · 지도)


@dataclass
class Page:
    head: list[str]         # 머리 줄 칸 — 첫 칸은 왼쪽 '* … 증빙'
    blocks: list[Block] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def grid_cols(n: int) -> int:
    if n <= 1:
        return 1
    if n in (2, 4):
        return 2
    return 3


def _sorted(items: list[Evidence]) -> list[Evidence]:
    return sorted(items, key=lambda e: (e.day or date.max, e.path.name))


def stay_pages(trip: Trip) -> list[Page]:
    items = _sorted(trip.stay)
    if not items:
        return []
    if trip.days <= ONE_PAGE_STAY_DAYS:
        days = [e.day for e in items if e.day]
        right = ""
        if days:
            first, last = days[0], days[-1]
            right = korean_date(first) if first == last else f"{korean_date(first)} ~ {last.month}월 {last.day}일"
        captions = [korean_date(e.day) if e.day else e.path.stem for e in items]
        return [Page(["* 체류 증빙", right], [Block([e.path for e in items], captions, cols=grid_cols(len(items)), fill=True)])]
    pages = []
    for day, group in _group(items, lambda e: e.day):
        pages.append(Page(["* 체류 증빙", korean_date(day) if day else "일자 없음"],
                          [Block([e.path for e in group], cols=grid_cols(len(group)), fill=True)]))
    return pages


def _group(items, key):
    groups: list[tuple] = []
    for item in items:
        k = key(item)
        if groups and groups[-1][0] == k:
            groups[-1][1].append(item)
        else:
            groups.append((k, [item]))
    return groups


def public_pages(trip: Trip) -> list[Page]:
    pages = []
    # 같은 날은 넣은 차례(이동한 차례)대로 — 이동편 이름 차례로 섞지 않는다
    items = sorted(trip.public, key=lambda e: e.day or date.max)
    groups: dict = {}
    for e in items:
        groups.setdefault((e.day, e.mode.strip()), []).append(e)
    for (day, mode), group in groups.items():
        total = sum(e.amount or 0 for e in group)
        label = "* 교통비 증빙" + (f" ({mode})" if mode else " (대중교통)")
        pages.append(Page([label, korean_date(day) if day else "일자 없음", won(total)],
                          [Block([e.path for e in group], cols=grid_cols(len(group)), fill=True)]))
    return pages


def car_pages(trip: Trip) -> list[Page]:
    tolls = _sorted(trip.tolls)
    route = trip.route_map is not None or trip.km_go is not None or trip.km_back is not None
    if not tolls and not route:
        return []
    total = sum(e.amount or 0 for e in tolls)
    blocks = []
    for day, group in _group(tolls, lambda e: e.day):
        subtotal = sum(e.amount or 0 for e in group)
        blocks.append(Block([e.path for e in group], title=[korean_date(day) if day else "일자 없음", f"하이패스 {won(subtotal)}"],
                            cols=3))
    if route:
        go, back = trip.km_go, trip.km_back if trip.km_back is not None else trip.km_go
        both = (go or 0) + (back or 0) if go is not None or back is not None else None
        title = ["* 이동경로", f"출발지→도착지 {km(go)}", f"도착지→출발지 {km(back)}", f"총 이동경로 {km(both)}"]
        blocks.append(Block([trip.route_map] if trip.route_map else [], title=title, cols=1, fill=True))
    head = ["* 교통비 증빙 (자차)", won(total)] if tolls else ["* 교통비 증빙 (자차)"]
    return [Page(head, blocks)]


def lodging_pages(trip: Trip) -> list[Page]:
    pages = []
    cap = trip.cap()
    for ev in _sorted(trip.lodging):
        support, limit = lodging_support(ev, cap, trip.people)
        notes = []
        if ev.amount is not None and ev.amount > limit:
            people = f" × {trip.people}명" if trip.people > 1 else ""
            notes.append(f"결제 {won(ev.amount)} — 공무원 여비 기준 숙박비 상한({trip.cap_region()} 1박 {won(cap)} × {ev.nights}박{people}"
                         f" = {won(limit)})을 넘어 상한금액으로 지원")
        pages.append(Page(["* 숙박비 증빙", f"숙박기간 {stay_period(ev)}", f"지원금액 {won(support)}"],
                          [Block([ev.path], cols=1, fill=True)], notes))
    return pages


def pages(trip: Trip) -> list[Page]:
    """체류 → 교통비(대중교통 · 자차) → 숙박."""
    return stay_pages(trip) + public_pages(trip) + car_pages(trip) + lodging_pages(trip)


def problems(trip: Trip) -> list[str]:
    """만들기 전에 알릴 것 — 막는 것은 이름 · 증빙 없음뿐이고 나머지는 알림."""
    out = []
    if not trip.name.strip():
        out.append("출장자 이름을 넣어 주세요.")
    if not (trip.stay or trip.public or trip.tolls or trip.lodging or trip.route_map):
        out.append("증빙 파일이 하나도 없습니다.")
    for kind, items in ((STAY, trip.stay), (PUBLIC, trip.public), (TOLL, trip.tolls), (LODGING, trip.lodging)):
        for e in items:
            if not e.day:
                out.append(f"{KIND_NAMES[kind]} · {e.path.name}: 일자가 없습니다.")
            if kind != STAY and e.amount is None:
                out.append(f"{KIND_NAMES[kind]} · {e.path.name}: 금액이 없습니다.")
            if kind == PUBLIC and not e.mode.strip():
                out.append(f"대중교통 · {e.path.name}: 이동편(열차 · 고속버스 …)이 없습니다.")
    if trip.tolls and trip.route_map is None and trip.km_go is None:
        out.append("자차 하이패스가 있는데 이동경로(지도 · km)가 없습니다.")
    return out


def blocking(trip: Trip) -> list[str]:
    return [p for p in problems(trip) if p.startswith(("출장자 이름", "증빙 파일이 하나도"))]


def output_path(folder: Path, name: str) -> Path:
    """'<이름> 출장증빙.pdf' — 같은 이름이 있으면 덮어쓰지 않고 _2, _3."""
    safe = re.sub(r'[\\/:*?"<>|]', " ", name.strip()) or "출장자"
    path = folder / f"{safe} 출장증빙.pdf"
    n = 2
    while path.exists():
        path = folder / f"{safe} 출장증빙_{n}.pdf"
        n += 1
    return path


def rows_for(n: int, cols: int) -> int:
    return max(1, math.ceil(n / max(1, cols)))


# ── 폴더에서 항목별로 나누기 ──────────────────────────────────────────────
# 출장 폴더 아래 하위 폴더(또는 파일) 이름의 낱말로 지원 항목을 정한다 — 담당자 "지원항목별로 증빙 자료를 넣고".
# 이름으로 못 정한 파일은 넣지 않고 알린다(신청서 · 공문 · 만든 출장증빙이 섞이지 않게).
KIND_WORDS = (
    (TOLL, ("하이패스", "자차", "통행료", "톨게이트", "유류")),
    (LODGING, ("숙박", "호텔", "모텔", "리조트")),
    (PUBLIC, ("대중교통", "열차", "기차", "ktx", "srt", "itx", "버스", "택시", "지하철", "승차권", "교통")),
    (STAY, ("체류",)),
)
MAP_WORDS = ("지도", "경로", "길찾기", "map")
MODES = (("열차", ("열차", "기차", "ktx", "srt", "itx", "무궁화", "새마을")), ("고속버스", ("고속버스",)),
         ("시외버스", ("시외버스",)), ("시내버스", ("시내버스",)), ("택시", ("택시",)), ("지하철", ("지하철",)), ("항공", ("항공", "비행기")))
SKIP_WORDS = ("출장증빙", "신청서", "명령", "공문", "참가확인")


def kind_of(name: str) -> str:
    low = name.lower()
    for kind, words in KIND_WORDS:
        if any(w in low for w in words):
            return kind
    return ""


def mode_of(name: str) -> str:
    low = name.lower()
    for mode, words in MODES:
        if any(w in low for w in words):
            return mode
    return ""


@dataclass
class Scan:
    files: dict[str, list[Path]] = field(default_factory=dict)
    route_map: Path | None = None
    unsorted: list[Path] = field(default_factory=list)


def scan_folder(folder: Path) -> Scan:
    """출장 폴더를 훑어 항목별 파일을 고른다. 파일 이름이 먼저, 없으면 위 폴더 이름(출장 폴더 아래 몇 단계든)."""
    out = Scan(files={k: [] for k in (STAY, PUBLIC, TOLL, LODGING)})
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in FILE_SUFFIXES:
            continue
        rel = path.relative_to(folder)
        if any(w in path.stem for w in SKIP_WORDS):
            continue
        if out.route_map is None and path.suffix.lower() in IMAGE_SUFFIXES and any(w in path.stem.lower() for w in MAP_WORDS):
            out.route_map = path
            continue
        kind = kind_of(path.stem)
        if not kind:
            for part in reversed(rel.parts[:-1]):
                kind = kind_of(part)
                if kind:
                    break
        if kind:
            out.files[kind].append(path)
        else:
            out.unsorted.append(path)
    return out
