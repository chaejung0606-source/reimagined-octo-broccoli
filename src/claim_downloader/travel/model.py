"""출장증빙 — 지원 항목별 증빙과 출장 정보에서 쪽 짜임 · 숙박 지원금액을 정한다. Qt 없음.

담당자가 손으로 만들던 '<이름> 출장증빙.pdf' 의 모양(2026-10-27 그림 · 설명, CLAUDE.md 28절)을 그대로 옮긴다:
- 쪽 차례는 **체류 → 교통비 → 숙박**(담당자 지정).
- 체류: 출장이 7일 이하면 **한 쪽을 칸으로 나눠** 모든 날을 담고, 8일 이상이면 일자마다 한 쪽. 머리 줄 오른쪽 칸은 비우고(금액 · 일자 없음),
  그 아래 출장지 줄('삼척 출장 증빙'). 출장지가 여러 곳이면 출장지마다 그 줄 + 그곳의 날들(담당자 2026-10-27).
- 대중교통: (일자, 이동편)마다 한 쪽 — 같은 날이라도 열차 → 고속버스처럼 이동편이 바뀌면 나눈다. 머리 줄에 일자와 금액.
- 자차: 한 쪽에 하이패스 영수증을 **이용일자별로** 묶어 그날 금액을 적고(담당자 "이용일자별로 나눠서 금액을 작성"), 아래에 이동경로(구간마다 km · 총)와 지도.
  출장지가 여러 곳이면 출발지 → 출장지들 → 출발지 구간마다.
- 숙박: 영수증마다 숙박기간과 지원금액. 결제액이 공무원 여비 기준 상한을 넘으면 지원금액은 상한금액.

출장자가 여럿이면(출장신청서 — travel/application.py) 증빙마다 출장자를 정하고(파일 이름 '<이름>_체류증빙' 꼴, 담당자 2026-11-10)
출장자마다 따로 확인하고 따로 만든다(`for_traveler` · `review`). 하이패스가 있으면 자차 — 네이버 지도 최단거리(거리우선) 그림과 가는 길 · 오는 길 · 총 km 를
자차 쪽에 적는다(담당자 2026-11-10).
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
# 출장비 증빙 넷 밖의 파일 중 이름이 앞에 붙은 것(참가확인서 등) — 출장증빙 끝에 붙인다(담당자 2026-11-10 "출장비증빙 서류파일외 파일명 앞에
# 이름이 붙어있는 파일은 기타증빙으로 넣기")
OTHER = "other"
KINDS = (STAY, PUBLIC, TOLL, LODGING, OTHER)
KIND_NAMES = {STAY: "체류", PUBLIC: "대중교통", TOLL: "자차(하이패스)", LODGING: "숙박", OTHER: "기타"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
FILE_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}

# 체류를 한 묶음(한 쪽부터)으로 담는 출장 일수(이하) — 담당자 "출장일이 7일 이하일 경우 칸을 나눠서 한페이지에".
# 한 쪽에 다 넣으면 증빙 글자가 작아질 때는 그리기(render.py)가 다음 쪽으로 넘긴다(담당자 2026-11-10 "최대한 증빙이 잘보이는 방향으로")
ONE_PAGE_STAY_DAYS = 7


@dataclass
class Evidence:
    path: Path
    day: date | None = None
    amount: int | None = None
    mode: str = ""          # 대중교통 이동편(열차 · 고속버스 …)
    nights: int = 1         # 숙박 영수증 하나가 덮는 박 수
    place: str = ""         # 출장지가 여러 곳일 때 어느 곳의 체류 · 숙박인지
    part: int | None = None # 영수증 여러 장이 든 PDF(하이패스 '총 N 건') 중 몇 번째 상자인지 — 없으면 파일 전체
    person: str = ""        # 출장자가 여럿일 때 누구 증빙인지 — SHARED('공통')면 모두의 출장증빙에 넣는다
    origin: str = ""        # 대중교통 증빙(승차권 하나)의 출발지 — 담당자 2026-11-10 "증빙별로 출발지와 목적지 및 금액 작성"
    goal: str = ""          # 대중교통 증빙의 목적지
    ref: tuple = ()         # 화면 표의 어느 줄인지((항목, 줄)) — 미리 보기에서 고친 값을 그 줄에 적는다
    label: str = ""         # 기타 증빙의 내용(파일 이름에서 이름을 뗀 것 — '참가확인서')
    shop_region: str = ""   # 체류 영수증 가맹점 주소의 시 · 군 — 출장지와 같아야 한다(담당자 2026-11-10, stay_regions)


@dataclass
class Trip:
    name: str = ""
    start: date | None = None
    end: date | None = None
    origin: str = ""
    destination: str = ""   # 여러 곳이면 쉼표(·, →)로 — 다니는 차례대로
    region: str = ""        # 숙박 상한 지역 구분 — 비우면 출장지로 정한다
    lodging_cap: int | None = None   # 1박 상한을 손으로 정했으면
    people: int = 1         # 공동숙박 인원
    stay: list[Evidence] = field(default_factory=list)
    public: list[Evidence] = field(default_factory=list)
    tolls: list[Evidence] = field(default_factory=list)
    lodging: list[Evidence] = field(default_factory=list)
    other: list[Evidence] = field(default_factory=list)    # 기타 증빙(이름이 붙은 그 밖의 파일)
    route_map: Path | None = None
    legs: list = field(default_factory=list)   # 구간 km — 출발지→출장지1 → … → 마지막 출장지→출발지. 출장지가 하나면 [가는 길, 오는 길(비면 가는 길)]
    route_maps: list = field(default_factory=list)   # 구간마다 네이버 지도 최단거리 그림(legs 와 같은 차례) — 있으면 route_map 대신 이것들
    route_stops: list = field(default_factory=list)  # 자차 경유지 + 목적지(차례대로) — 경유지가 있을 때만(담당자 2026-11-10). 비면 출장지로
    fuel: str = ""          # 자차 연료 종류(휘발유 · 경유 · LPG …) — 자차 쪽 머리 줄에 적는다(담당자 2026-11-10)
    place_regions: dict = field(default_factory=dict)   # 출장지 글 → 시 · 군(출장지 글에 시 · 군이 없을 때 네이버에서 찾은 그곳 주소로 — 화면이 채움)

    @property
    def days(self) -> int:
        if self.start and self.end:
            return (self.end - self.start).days + 1
        dates = sorted(e.day for e in self.stay if e.day)
        return (dates[-1] - dates[0]).days + 1 if dates else len(self.stay)

    @property
    def places(self) -> list[str]:
        return split_places(self.destination)

    def place_of(self, ev: Evidence) -> str:
        """그 증빙의 출장지 — 출장지가 하나면 그곳, 여럿이면 증빙에 적은 곳(목록에 있는 것)만."""
        places = self.places
        if len(places) == 1:
            return places[0]
        return match_place(ev.place, places)

    def cap_region(self, ev: Evidence | None = None) -> str:
        if self.region:
            return self.region
        place = self.place_of(ev) if ev is not None else ""
        return lodging_region(place or (self.places[0] if self.places else ""))

    def cap(self, ev: Evidence | None = None) -> int:
        return self.lodging_cap if self.lodging_cap else LODGING_CAPS[self.cap_region(ev)]

    def route_legs(self) -> list[tuple[str, float | None]]:
        """이동경로 구간(이름, km). 출장지가 하나면 담당자 양식 그대로 '출발지→도착지' · '도착지→출발지'."""
        legs = list(self.legs)
        places = list(self.route_stops) if len(self.route_stops) > 1 else self.places
        if len(places) <= 1:
            go = legs[0] if legs else None
            back = legs[1] if len(legs) > 1 and legs[1] else go
            return [("출발지→도착지", go), ("도착지→출발지", back)]
        stops = ["출발지", *places, "출발지"]
        return [(f"{a}→{b}", legs[i] if i < len(legs) else None) for i, (a, b) in enumerate(zip(stops, stops[1:]))]

    def has_route(self) -> bool:
        return self.route_map is not None or any(self.route_maps) or any(v for v in self.legs)

    def maps(self) -> list[tuple[str, Path]]:
        """이동경로 그림(설명, 파일) — 구간마다 찍은 것이 있으면 그것들(구간 이름 · km), 없으면 하나뿐인 지도."""
        legs = self.route_legs()
        shots = [(f"{legs[i][0] if i < len(legs) else ''} {km(legs[i][1]) if i < len(legs) else ''}".strip(), Path(p))
                 for i, p in enumerate(self.route_maps) if p]
        if shots:
            return shots
        return [("", self.route_map)] if self.route_map else []


# ── 글자 ────────────────────────────────────────────────────────────────
def korean_date(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일"


def won(n: int | None) -> str:
    return f"{n:,}원" if n is not None else "금액 없음"


def km(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:g}km" if value != int(value) else f"{int(value)}km"


_PLACE_SPLIT = re.compile(r"\s*(?:[,，、·/→>]|->)\s*")
_PLACE_TAIL = re.compile(r"(특별자치시|특별자치도|특별시|광역시|시|군|구|도|읍|면)$")


def split_places(text: str) -> list[str]:
    """'삼척, 강릉' · '삼척 → 강릉' → ['삼척', '강릉'] — 다니는 차례대로, 같은 곳은 한 번."""
    out: list[str] = []
    for part in _PLACE_SPLIT.split(text or ""):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def place_keys(place: str) -> set[str]:
    """파일 이름에서 찾을 낱말 — '강원 삼척시' → {'강원', '삼척시', '삼척'}. 두 글자 이상만."""
    keys = set()
    for word in place.split():
        keys.add(word)
        keys.add(_PLACE_TAIL.sub("", word))
    return {k.lower() for k in keys if len(k) >= 2}


def match_place(text: str, places: list[str]) -> str:
    """글(증빙에 적은 출장지 · 파일 경로)이 가리키는 출장지 하나 — 정확히 같거나, 낱말이 한 곳에만 맞을 때만."""
    plain = re.sub(r"\s", "", text or "").lower()
    if not plain:
        return ""
    for place in places:
        if re.sub(r"\s", "", place).lower() == plain:
            return place
    # 여러 곳에 다 든 낱말('강원 삼척시' · '강원 강릉시' 의 '강원')로는 가리지 않는다
    counts: dict[str, int] = {}
    for place in places:
        for key in place_keys(place):
            counts[key] = counts.get(key, 0) + 1
    hits = [p for p in places if any(counts[k] == 1 and k in plain for k in place_keys(p))]
    return hits[0] if len(hits) == 1 else ""


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
# 숫자만 붙여 쓴 날짜 '20261020'(담당자 2026-11-10 "일자 20261020 이렇게 입력해도 2026-10-20으로") — 달 · 일이 맞는 것만
_COMPACT_DATE = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
_SHORT_DATE = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)|(?<!\d)(\d{1,2})[.\-](\d{1,2})(?!\d)|(?<![\d.])(\d{2})(\d{2})(?![\d,])")
_AMOUNT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{3,7})\s*원")


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def guess_day(text: str, year: int) -> date | None:
    """글에서 일자 — '2026-10-20' · '2026. 10. 20' · '2026년 10월 20일' → '20261020' → '261020' · '10.20' · '1020'(year 의 해) 차례."""
    for pattern in (_FULL_DATE, _COMPACT_DATE):
        for match in pattern.finditer(text):
            found = _make(*(int(g) for g in match.groups()))
            if found:
                return found
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


_CALC_OPS = {"+", "-", "*", "/"}


def calc(text: str) -> float | None:
    """금액 칸의 셈 — 엑셀처럼 더하기 · 빼기 · 곱하기 · 나누기 · 괄호(담당자 2026-11-10 "하이패스 같이 금액을 사용자가 확인해서 넣어야 할 때
    엑셀처럼 더하기 빼기 나누기 정도는 금액 칸에서"). '4100+4100' · '=8,200/2' · '4,100×2' · '(4100+4100)÷2원'. 셈이 아니면(글자가 섞임) None.
    eval 을 쓰지 않는다 — 숫자 · 연산자 · 괄호만 직접 읽는다."""
    expr = (text or "").strip().lstrip("=")
    for a, b in (("×", "*"), ("x", "*"), ("X", "*"), ("÷", "/"), ("－", "-"), ("＋", "+"), ("원", ""), (",", ""), (" ", "")):
        expr = expr.replace(a, b)
    if not expr or not re.fullmatch(r"[\d.+\-*/()]+", expr):
        return None
    tokens = re.findall(r"\d+(?:\.\d+)?|[+\-*/()]", expr)
    if "".join(tokens) != expr:
        return None
    pos = 0

    def peek() -> str:
        return tokens[pos] if pos < len(tokens) else ""

    def take() -> str:
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def number() -> float:
        token = take() if pos < len(tokens) else ""
        if token == "-":
            return -number()
        if token == "+":
            return number()
        if token == "(":
            value = total()
            if take() != ")":
                raise ValueError
            return value
        return float(token)

    def term() -> float:
        value = number()
        while peek() in ("*", "/"):
            if take() == "*":
                value *= number()
            else:
                value /= number()
        return value

    def total() -> float:
        value = term()
        while peek() in ("+", "-"):
            value = value + term() if take() == "+" else value - term()
        return value

    try:
        value = total()
    except (ValueError, ZeroDivisionError, IndexError):
        return None
    return value if pos == len(tokens) else None


def amount_of(text: str) -> int | None:
    """금액 칸의 값 — 셈이면 그 결과(원 단위로 반올림), 아니면 글자 속 숫자('4,100원(카드)' → 4100)."""
    value = calc(text)
    if value is not None:
        return int(round(value))
    if re.fullmatch(r"=?[\d,.\s+\-*/()×xX÷원]*[+\-*/×xX÷][\d,.\s+\-*/()×xX÷원]*", (text or "").strip()):
        return None              # 셈인데 틀렸다('7/0' · '4100*') — 숫자만 이어 붙여 엉뚱한 금액을 만들지 않는다
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    return int(digits) if digits else None


def guess_amount(text: str) -> int | None:
    values = [int(v.replace(",", "")) for v in _AMOUNT.findall(text)]
    return max(values) if values else None


def pdf_text(path: Path, pages: int = 2) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:pages])
    except Exception:
        return ""


def guess(path: Path, year: int, route: bool = False, stay: bool = False) -> Evidence:
    """파일 이름 → (PDF 면) 글자 차례로 일자 · 금액을 짐작한다. 그림 영수증은 이름에 적힌 것만 — 화면에서 고친다.
    route 면(대중교통) 출발지 · 목적지도 — 파일 이름 '…_춘천-서울_…' · '춘천→서울', 승차권 글자의 '출발 … 도착 …'.
    stay 면(체류) 가맹점 주소의 시 · 군도 — 파일 이름에 적힌 시 · 군, 영수증 글자의 주소 줄(그림 영수증은 앱이 못 읽는다)."""
    stem = path.stem
    day, amount = guess_day(stem, year), guess_amount(stem)
    origin, goal = guess_route(stem) if route else ("", "")
    shop = region_of(stem) if stay else ""
    if (day is None or amount is None or (route and not (origin and goal)) or (stay and not shop)) and path.suffix.lower() == ".pdf":
        text = pdf_text(path)
        day = day or guess_day(text, year)
        amount = amount or guess_amount(text)
        if route and not (origin and goal):
            origin, goal = guess_route(text)
        if stay and not shop:
            shop = shop_region_of(text)
    return Evidence(path=path, day=day, amount=amount, origin=origin, goal=goal, shop_region=shop)


# ── 체류 영수증의 가맹점 지역 — 출장지와 같은 시 · 군이어야 한다 ───────────────────
# 담당자 2026-11-10 "체류증빙은 영수증 가맹점의 주소지와 출장 목적지가 같아야" · "강원도 춘천시가 출장지면 강원도 춘천시까지만 동일하면" ·
# "강원도 원주시 인터불고호텔이 출장지이면 체류증빙은 강원도 원주시 내 영수증이면 됩니다". 시 · 군 이름표는 카드 회의비의 지역 규칙(claims/card.py)과 같은 것.
def region_of(text: str) -> str:
    """글에 나온 첫 시 · 군('강원도 원주시 인터불고호텔' → 원주, '강원가명정보활용지원센터 (원주)' → 원주). 모르면 ''."""
    from ..claims.card import regions_in
    found = regions_in(text or "")
    return found[0] if found else ""


def shop_region_of(text: str) -> str:
    """영수증 글자 → 가맹점 주소의 시 · 군. 주소 줄이 있으면 그것, 없으면 글에 시 · 군이 하나만 나올 때."""
    from ..claims.card import address_region, read_receipt, regions_in
    receipt = read_receipt(text or "")
    found = address_region(receipt.address) if receipt.address else ""
    if found:
        return found
    regions = regions_in(text or "")
    return regions[0] if len(regions) == 1 else ""


def stay_regions(trip: Trip, ev: Evidence) -> list[str]:
    """그 체류 영수증이 있어야 할 시 · 군들 — 증빙에 출장지를 적었으면(출장지가 여럿일 때) 그곳, 아니면 출장지 모두.
    출장지 글에 시 · 군이 없으면 네이버에서 찾은 그곳 주소의 시 · 군(trip.place_regions)."""
    own = trip.place_of(ev) if len(trip.places) > 1 else ""
    out: list[str] = []
    for place in [own] if own else trip.places:
        region = region_of(place) or trip.place_regions.get(place, "")
        if region and region not in out:
            out.append(region)
    return out


# 대중교통 출발지 · 목적지 — '춘천→서울' · '춘천-서울' · '춘천~서울', 또는 '출발(역 · 지) 춘천 … 도착(역 · 지) 서울'
_STOP = r"[가-힣A-Za-z][가-힣A-Za-z0-9()]{1,14}"
_ROUTE_ARROW = re.compile(rf"({_STOP})\s*(?:→|->|➝|➔|⇒|▶|~|-)\s*({_STOP})")
_ROUTE_FROM = re.compile(r"(?:출발역|출발지|승차역|출발|승차)\s*[:：]?\s*([가-힣A-Za-z]{2,14})")
_ROUTE_TO = re.compile(r"(?:도착역|도착지|하차역|도착|하차)\s*[:：]?\s*([가-힣A-Za-z]{2,14})")
_NOT_STOP = ("증빙", "영수증", "대중교통", "교통", "승차권", "출장", "체류", "하이패스", "숙박", "금액", "합계", "일자", "출발", "도착",
             "승차", "하차", "ktx", "srt", "itx", "열차", "기차", "버스", "택시", "지하철", "항공", "카드", "결제")


def _stop_ok(word: str) -> bool:
    low = word.lower()
    return not any(w in low for w in _NOT_STOP) and not low.isdigit()


def guess_route(text: str) -> tuple[str, str]:
    """글자에서 (출발지, 목적지) — 둘 다 찾았을 때만, 아니면 ('', '')."""
    for m in _ROUTE_ARROW.finditer(text or ""):
        a, b = m.group(1), m.group(2)
        if _stop_ok(a) and _stop_ok(b) and a != b:
            return a, b
    a = next((m.group(1) for m in _ROUTE_FROM.finditer(text or "") if _stop_ok(m.group(1))), "")
    b = next((m.group(1) for m in _ROUTE_TO.finditer(text or "") if _stop_ok(m.group(1))), "")
    return (a, b) if a and b and a != b else ("", "")


# 하이패스 홈페이지 영수증 인쇄(담당자 2026-10-27 견본): 상자마다 '2026년10월23일 13시02분' · '9,600 원(카드)'
_HIPASS_DAY = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*\d{1,2}\s*시")
_HIPASS_AMOUNT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원\s*\((?:카드|현금|선불|후불)[^)]*\)")


def hipass_receipts(text: str) -> list[tuple[date | None, int]]:
    """하이패스 영수증 인쇄 글에서 영수증마다 (이용일자, 금액) — 일자 · 금액 수가 같을 때만(아니면 빈 목록)."""
    days = [_make(*(int(g) for g in m.groups())) for m in _HIPASS_DAY.finditer(text)]
    amounts = [int(m.group(1).replace(",", "")) for m in _HIPASS_AMOUNT.finditer(text)]
    return list(zip(days, amounts)) if days and len(days) == len(amounts) else []


# ── 쪽 짜임 ─────────────────────────────────────────────────────────────
@dataclass
class Block:
    images: list[Path]
    captions: list[str] = field(default_factory=list)   # 그림마다 위에 적는 글(체류 칸의 일자)
    title: list[str] = field(default_factory=list)      # 그림 묶음 위의 줄(자차의 일자 · 금액, 이동경로)
    cols: int = 3
    fill: bool = False      # 남은 높이를 다 쓴다(체류 한 쪽 · 지도)
    parts: list = field(default_factory=list)            # 그림마다 PDF 의 몇 번째 영수증 상자인지(Evidence.part) — 없으면 파일 전체
    refs: list = field(default_factory=list)             # 그림마다 어느 증빙인지(Evidence.ref) — 앱 미리 보기에서 눌러 고친다
    title_ref: tuple = ()                                # 묶음 줄을 누르면 고칠 것(이동경로 km · 연료)


@dataclass
class Page:
    head: list[str]         # 머리 줄 칸 — 첫 칸은 왼쪽 '* … 증빙'
    blocks: list[Block] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    head_ref: tuple = ()    # 머리 줄을 누르면 고칠 것(숙박 영수증 · 자차 연료)


def grid_cols(n: int) -> int:
    if n <= 1:
        return 1
    if n in (2, 4):
        return 2
    return 3


def _sorted(items: list[Evidence]) -> list[Evidence]:
    return sorted(items, key=lambda e: (e.day or date.max, e.path.name))


def _place_title(place: str) -> list[str]:
    return [f"{place} 출장 증빙"] if place else []


def stay_pages(trip: Trip) -> list[Page]:
    """머리 줄 오른쪽 칸은 비운다 — 체류 증빙에는 금액을 적지 않는다(담당자 2026-10-27 그림). 그 아래 출장지 줄('삼척 출장 증빙') 맨 오른쪽에 일자 칩
    (담당자 2026-11-10 "체류증빙 일자는 장소와 같은 행 맨 오른쪽에 · 색상은 다른 증빙서식과 동일하게" — 하이패스의 '하이패스 8,200원' 같은 칩).
    그 출장지의 날이 여럿이면 칩은 기간이고 칸마다 그날 일자 이름표(같은 칩 색) — 영수증을 나란히 놓아야 7일도 몇 쪽에 들어간다.
    출장지가 여러 곳이면 출장지마다 줄 하나와 그곳의 날들 — 7일 이하면 한 쪽에 차례로, 8일 이상이면 일자마다 한 쪽."""
    items = _sorted(trip.stay)
    if not items:
        return []
    head = ["* 체류 증빙", ""]
    places = trip.places

    def block(place: str, group: list[Evidence]) -> Block:
        days = sorted({e.day for e in group if e.day})
        one_day = len({e.day for e in group}) == 1
        if one_day:
            when = korean_date(days[0]) if days else "일자 없음"
            title = [*_place_title(place), when] if place else [when]
            captions: list[str] = []
        else:
            when = days_period(days)
            title = [*_place_title(place), when] if place and when else _place_title(place)
            captions = [korean_date(e.day) if e.day else e.path.stem for e in group]
        return Block([e.path for e in group], captions, title=title, cols=grid_cols(len(group)), fill=True,
                     refs=[e.ref for e in group], title_ref=group[0].ref if one_day else ())

    if trip.days <= ONE_PAGE_STAY_DAYS:
        groups: dict[str, list[Evidence]] = {}
        for e in items:
            groups.setdefault(trip.place_of(e), []).append(e)
        order = [p for p in places if p in groups] + [p for p in groups if p not in places]
        return [Page(head, [block(place, groups[place]) for place in order])]
    return [Page(head, [block(place, group)]) for (_day, place), group in _group(items, lambda e: (e.day, trip.place_of(e)))]


def days_period(days: list) -> str:
    """체류 날들의 기간 — '2026년 5월 28일 ~ 5월 30일'(해가 다르면 해까지). 날을 모르면 ''."""
    if not days:
        return ""
    first, last = days[0], days[-1]
    if first == last:
        return korean_date(first)
    tail = f"{last.month}월 {last.day}일" if last.year == first.year else f"{last.year}년 {last.month}월 {last.day}일"
    return f"{first.year}년 {first.month}월 {first.day}일 ~ {tail}"


def _group(items, key):
    groups: list[tuple] = []
    for item in items:
        k = key(item)
        if groups and groups[-1][0] == k:
            groups[-1][1].append(item)
        else:
            groups.append((k, [item]))
    return groups


def public_caption(e: Evidence) -> str:
    """증빙(승차권) 하나 위에 적는 글 — '열차 · 춘천 → 서울 · 8,000원'. 모르는 것은 '?'(담당자 2026-11-10 "불분명한 경우 확인요청")."""
    return f"{e.mode.strip() or '이동편 ?'} · {e.origin.strip() or '?'} → {e.goal.strip() or '?'} · {won(e.amount)}"


def public_pages(trip: Trip) -> list[Page]:
    """대중교통 — 체류처럼 일자별로 나누고(일자 줄에 그날 합계), 일자 안에서는 증빙(승차권 · 영수증 파일) 하나하나가 따로 칸이다:
    이동편이 바뀌어도 · 같은 이동편이라도 표를 나눠 끊었으면 다른 증빙(담당자 2026-11-10). 칸마다 이동편 · 출발지 → 목적지 · 금액,
    머리 줄에 실비 합계. 날이 여럿이면 끝에 실비 합계 줄을 한 번 더."""
    # 같은 날은 넣은 차례(이동한 차례)대로 — 이동편 이름 차례로 섞지 않는다
    items = sorted(trip.public, key=lambda e: e.day or date.max)
    if not items:
        return []
    total = _sum_text(items)
    blocks = []
    for day, group in _group(items, lambda e: e.day):
        blocks.append(Block([e.path for e in group], [public_caption(e) for e in group],
                            title=[korean_date(day) if day else "일자 없음", f"증빙 {len(group)}건", f"일자 합계 {_sum_text(group)}"],
                            cols=grid_cols(len(group)), fill=True, refs=[e.ref for e in group]))
    if len(blocks) > 1:
        blocks.append(Block([], title=["* 실비 합계", f"{len(blocks)}일 · 증빙 {len(items)}건", total]))
    return [Page(["* 교통비 증빙 (대중교통)", f"실비 합계 {total}"], blocks)]


def _sum_text(items: list[Evidence]) -> str:
    """합계 글 — 금액을 모르는 증빙이 있으면 그 수를 함께(0원으로 보이지 않게)."""
    missing = sum(1 for e in items if e.amount is None)
    return won(sum(e.amount or 0 for e in items)) + (f" (금액 없음 {missing}건)" if missing else "")


def car_pages(trip: Trip) -> list[Page]:
    """자차 — 하이패스 쪽과 이동경로 쪽을 나눈다(담당자 2026-11-10 "교통비 증빙 (자차-하이패스)" · "교통비 증빙 (자차-이동경로)" ·
    "하이패스 증빙에서는 연료 표시 필요없습니다. 또 이동경로 증빙페이지에서는 금액이 필요없습니다" · "이동경로에도 이동일자를" ·
    "이동일자는 자차의 경우 하이패스 이용내역과 동일하게"). 하이패스 쪽 머리 줄은 금액만, 이동경로 쪽은 연료만,
    이동경로 줄 왼쪽은 하이패스 이용일자."""
    tolls = _sorted(trip.tolls)
    route = trip.has_route()
    pages = []
    if tolls:
        blocks = []
        for day, group in _group(tolls, lambda e: e.day):
            subtotal = sum(e.amount or 0 for e in group)
            blocks.append(Block([e.path for e in group], parts=[e.part for e in group], refs=[e.ref for e in group],
                                title=[korean_date(day) if day else "일자 없음", f"하이패스 {won(subtotal)}"],
                                cols=grid_cols(len(group))))
        # 이동경로가 아직 없으면(지도 · km 전) 이 머리 줄을 눌러 km · 연료를 고친다 — 미리 보기에서 갈 곳이 있게
        pages.append(Page(["* 교통비 증빙 (자차-하이패스)", won(sum(e.amount or 0 for e in tolls))], blocks,
                          head_ref=() if route else route_key(trip)))
    if route:
        legs = trip.route_legs()
        known = [v for _, v in legs if v]
        total = sum(known) if known else None
        title = [route_days(trip) or "이동경로", *(f"{name} {km(v)}" for name, v in legs), f"총 이동경로 {km(total)}"]
        maps = trip.maps()
        # 네이버 지도 최단거리 그림 — 구간마다 찍었으면 칸마다 그 구간 이름 · km(담당자 2026-11-10 "가는거 오는거 총합 KM")
        route_ref = route_key(trip)
        block = Block([p for _, p in maps], [c for c, _ in maps] if len(maps) > 1 else [], title=title, cols=1, fill=True,
                      refs=[route_ref] * len(maps), title_ref=route_ref)
        head = ["* 교통비 증빙 (자차-이동경로)"] + ([f"연료 {trip.fuel}"] if trip.fuel else [])
        pages.append(Page(head, [block], head_ref=route_ref))
    return pages


def route_days(trip: Trip) -> str:
    """이동경로의 이동일자 — 하이패스 이용일자와 같게(담당자 2026-11-10 "이동일자는 자차의 경우 하이패스 이용내역과 동일하게" ·
    "자차는 무조건 하이패스 이용내역이 있어야 합니다"). 하이패스 일자를 아직 모르면 ''(그 영수증의 일자를 채우면 같이 나온다)."""
    days = sorted({e.day for e in trip.tolls if e.day})
    if not days:
        return ""
    first = days[0]
    rest = [f"{d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일" if d.year == first.year else korean_date(d) for d in days[1:]]
    return ", ".join([korean_date(first), *rest])


def route_key(trip: Trip) -> tuple:
    """자차 이동경로 · 연료를 가리키는 표시 — 미리 보기에서 이동경로 줄 · 지도 · 머리 줄을 누르면 km · 연료를 고친다."""
    return ("route", trip.name or "출장자")


def lodging_pages(trip: Trip) -> list[Page]:
    pages = []
    for ev in _sorted(trip.lodging):
        cap = trip.cap(ev)
        support, limit = lodging_support(ev, cap, trip.people)
        notes = []
        if ev.amount is not None and ev.amount > limit:
            people = f" × {trip.people}명" if trip.people > 1 else ""
            notes.append(f"결제 {won(ev.amount)} — 공무원 여비 기준 숙박비 상한({trip.cap_region(ev)} 1박 {won(cap)} × {ev.nights}박{people}"
                         f" = {won(limit)})을 넘어 상한금액으로 지원")
        pages.append(Page(["* 숙박비 증빙", f"숙박기간 {stay_period(ev)}", f"지원금액 {won(support)}"],
                          [Block([ev.path], cols=1, fill=True, refs=[ev.ref])], notes, head_ref=ev.ref))
    return pages


def other_caption(e: Evidence) -> str:
    return (e.label.strip() or e.path.stem) + (f" · {short_date(e.day)}" if e.day else "")


def other_pages(trip: Trip) -> list[Page]:
    """기타 증빙 — 파일마다 칸(위에 내용), 넣은 차례대로. 확인할 칸은 없다(일자 · 금액을 따지지 않는다)."""
    items = list(trip.other)
    if not items:
        return []
    return [Page(["* 기타 증빙", f"{len(items)}건"],
                 [Block([e.path for e in items], [other_caption(e) for e in items], cols=grid_cols(len(items)), fill=True,
                        refs=[e.ref for e in items])])]


def pages(trip: Trip) -> list[Page]:
    """체류 → 교통비(대중교통 · 자차) → 숙박 → 기타."""
    return stay_pages(trip) + public_pages(trip) + car_pages(trip) + lodging_pages(trip) + other_pages(trip)


def unclear(trip: Trip, kind: str, e: Evidence) -> list[str]:
    """증빙 하나에서 확인이 필요한 칸 — 앱 미리 보기가 그 칸을 칠하고 고치게 한다(담당자 2026-11-10 "확인이 필요한 부분을 직접 편집")."""
    if kind == OTHER:
        return []
    out = []
    if not e.day:
        out.append("일자")
    elif trip.start and trip.end:
        last = trip.end - timedelta(days=1) if kind == LODGING and trip.end > trip.start else trip.end
        if not (trip.start <= e.day <= last):
            out.append("일자(출장기간 밖)")
    if kind != STAY and e.amount is None:
        out.append("금액")
    if kind == PUBLIC:
        out += [label for label, value in (("이동편", e.mode), ("출발지", e.origin), ("목적지", e.goal)) if not value.strip()]
    if kind in (STAY, LODGING) and len(trip.places) > 1 and not trip.place_of(e):
        out.append("출장지")
    if kind == STAY:
        want = stay_regions(trip, e)
        if want and not e.shop_region.strip():
            out.append("가맹점 지역")
        elif want and region_of(e.shop_region) not in want:
            out.append("가맹점 지역(다름)")
    return out


def route_unclear(trip: Trip) -> list[str]:
    """자차 이동경로에서 확인이 필요한 것 — km · 지도 · 연료."""
    if not trip.tolls:
        return []
    out = []
    if any(v is None for _, v in trip.route_legs()) or not any(v for v in trip.legs):
        out.append("km")
    if not trip.maps():
        out.append("지도 그림")
    if not trip.fuel:
        out.append("연료")
    return out


def evidence_of(trip: Trip) -> list[tuple[str, Evidence]]:
    """출장의 증빙 모두 — (항목, 증빙), 쪽 차례(체류 → 대중교통 → 자차 → 숙박)."""
    return ([(STAY, e) for e in trip.stay] + [(PUBLIC, e) for e in trip.public] + [(TOLL, e) for e in trip.tolls]
            + [(LODGING, e) for e in trip.lodging] + [(OTHER, e) for e in trip.other])


def problems(trip: Trip) -> list[str]:
    """만들기 전에 알릴 것 — 막는 것은 이름 · 증빙 없음뿐이고 나머지는 알림."""
    out = []
    if not trip.name.strip():
        out.append("출장자 이름을 넣어 주세요.")
    if not (trip.stay or trip.public or trip.tolls or trip.lodging or trip.other or trip.route_map):
        out.append("증빙 파일이 하나도 없습니다.")
    for kind, items in ((STAY, trip.stay), (PUBLIC, trip.public), (TOLL, trip.tolls), (LODGING, trip.lodging)):
        for e in items:
            if not e.day:
                out.append(f"{KIND_NAMES[kind]} · {e.path.name}: 일자가 없습니다.")
            if kind != STAY and e.amount is None:
                out.append(f"{KIND_NAMES[kind]} · {e.path.name}: 금액이 없습니다.")
            if kind == STAY and e.shop_region.strip():
                want = stay_regions(trip, e)
                if want and region_of(e.shop_region) not in want:
                    out.append(f"체류 · {e.path.name}: 영수증 가맹점({e.shop_region.strip()})이 출장지({', '.join(want)})와 다른 시 · 군입니다 — "
                               "출장지 시 · 군 안의 영수증이어야 합니다.")
            if kind == PUBLIC and not e.mode.strip():
                out.append(f"대중교통 · {e.path.name}: 이동편(열차 · 고속버스 …)이 없습니다.")
            if kind == PUBLIC and not (e.origin.strip() and e.goal.strip()):
                out.append(f"대중교통 · {e.path.name}: 출발지 · 목적지를 확인해 주세요.")
            if kind in (STAY, LODGING) and len(trip.places) > 1 and not trip.place_of(e):
                out.append(f"{KIND_NAMES[kind]} · {e.path.name}: 어느 출장지인지 고르세요({' · '.join(trip.places)}).")
    if trip.tolls and not trip.has_route():
        out.append("자차 하이패스가 있는데 이동경로(지도 · km)가 없습니다.")
    return out


# ── 출장자 ──────────────────────────────────────────────────────────────
SHARED = "공통"      # 증빙 표의 출장자 칸에 이렇게 적으면 모든 출장자의 출장증빙에 들어간다
_NAME = re.compile(r"[가-힣]{2,4}")
_NOT_PERSON = ("체류", "증빙", "숙박", "교통", "하이패스", "자차", "영수증", "지도", "경로", "출장", "공통", "기타", "호텔", "열차", "버스", "택시")


def split_names(text: str) -> list[str]:
    """출장자 칸 → 이름 목록. 쉼표 · 가운뎃점 · 빗금 · 띄어쓰기로 나눈다(이름에는 띄어쓰기가 없다)."""
    out = []
    for name in re.split(r"[\s,，、·/]+", text or ""):
        name = name.strip()
        if name and name not in out:
            out.append(name)
    return out


def person_hint(path: Path) -> str:
    """파일 이름 '<이름>_체류증빙' 의 앞 이름(담당자 2026-11-10 — 파일명은 이름_체류증빙 · 이름_하이패스 증빙 · 이름_숙박비 증빙 · 이름_대중교통 증빙),
    없으면 위 폴더 이름이 이름 꼴인 것. 이름 꼴(한글 2~4자)이 아니거나 항목 낱말이면 ''."""
    head = path.stem.split("_", 1)[0].strip() if "_" in path.stem else ""
    for candidate in [head, *reversed([p for p in path.parts[:-1]])]:
        candidate = candidate.strip()
        if _NAME.fullmatch(candidate) and not any(w in candidate for w in _NOT_PERSON) and not kind_of(candidate):
            return candidate
    return ""


def person_of(path: Path, names: list[str]) -> str:
    """그 파일이 누구 증빙인지 — 출장자가 한 명이면 그 사람, 여럿이면 파일 이름 앞 이름 → 경로에 이름이 하나만 든 것. 못 정하면 ''."""
    if len(names) == 1:
        return names[0]
    hint = person_hint(path)
    if hint and (hint in names or not names):
        return hint
    hits = [n for n in names if n and n in str(path)]
    if len(hits) == 1:
        return hits[0]
    return hint if hint and not names else ""


def names_in_files(paths) -> list[str]:
    """증빙 파일 이름에서 읽은 출장자 — 신청서가 없을 때 출장자 칸을 채운다."""
    out = []
    for path in paths:
        hint = person_hint(Path(path))
        if hint and hint not in out:
            out.append(hint)
    return out


def _all_evidence(trip: Trip) -> list[tuple[str, Evidence]]:
    return [(kind, e) for kind, items in ((STAY, trip.stay), (PUBLIC, trip.public), (TOLL, trip.tolls), (LODGING, trip.lodging))
            for e in items]


def traveler_problems(trip: Trip, names: list[str]) -> list[str]:
    """출장자가 여럿일 때 — 누구 것인지 모르는 증빙 · 출장자 목록에 없는 사람의 증빙."""
    if len(names) <= 1:
        return []
    out = []
    for kind, e in _all_evidence(trip):
        who = e.person.strip()
        if not who:
            out.append(f"{KIND_NAMES[kind]} · {e.path.name}: 어느 출장자 것인지 고르세요({' · '.join(names)} 또는 {SHARED}).")
        elif who != SHARED and who not in names:
            out.append(f"{KIND_NAMES[kind]} · {e.path.name}: '{who}' 는 출장자 목록에 없습니다({' · '.join(names)}).")
    return out


def for_traveler(trip: Trip, name: str, names: list[str]) -> Trip:
    """출장자 한 명의 출장증빙 — 그 사람 증빙과 '공통' 증빙만. 이동경로(자차)는 하이패스가 있는 사람 것에만 붙는다(하이패스가 있으면 자차)."""
    single = len(names) <= 1

    def mine(items: list[Evidence]) -> list[Evidence]:
        return [e for e in items if single or e.person.strip() in (name, SHARED)]

    out = Trip(**{**trip.__dict__})
    out.name = name
    out.stay, out.public, out.tolls, out.lodging = mine(trip.stay), mine(trip.public), mine(trip.tolls), mine(trip.lodging)
    out.other = mine(trip.other)
    if not single and not out.tolls:
        out.route_map, out.route_maps, out.legs, out.route_stops, out.fuel = None, [], [], [], ""
    return out


FUELS = ("휘발유", "경유", "LPG", "전기", "하이브리드", "수소")


def parse_fuels(text: str) -> dict[str, str]:
    """설정 travel_fuels('이름=연료' 줄들) → {이름: 연료}. 연료 이름이 표에 없어도 적힌 대로 둔다."""
    out = {}
    for line in (text or "").splitlines():
        name, _, fuel = line.partition("=")
        if name.strip() and fuel.strip():
            out[name.strip()] = fuel.strip()
    return out


def format_fuels(fuels: dict[str, str]) -> str:
    return "\n".join(f"{name}={fuel}" for name, fuel in fuels.items() if name.strip() and fuel.strip())


def short_date(d: date) -> str:
    return f"{d.month}월 {d.day}일({WEEKDAYS[d.weekday()]})"


def review(trip: Trip) -> list[str]:
    """출장자별 증빙 확인(담당자 2026-11-10 "출장자별로 증빙 확인") — 막지 않는 알림. 체류 빠진 날 · 기간 밖 날짜 · 교통비 · 자차 이동경로 · 숙박 박 수."""
    out = []
    if not trip.stay:
        out.append("체류 증빙이 없습니다")
    if trip.start and trip.end:
        have = {e.day for e in trip.stay if e.day}
        if trip.stay and have:
            missing = [trip.start + timedelta(days=i) for i in range((trip.end - trip.start).days + 1)
                       if trip.start + timedelta(days=i) not in have]
            if missing:
                out.append("체류 증빙이 없는 날: " + ", ".join(short_date(d) for d in missing[:7]) + (" …" if len(missing) > 7 else ""))
        for kind, e in _all_evidence(trip):
            last = trip.end - timedelta(days=1) if kind == LODGING and trip.end > trip.start else trip.end
            if e.day and not (trip.start <= e.day <= last):
                out.append(f"{KIND_NAMES[kind]} · {e.path.name}: 출장기간 밖의 날짜({short_date(e.day)})")
        nights = sum(e.nights for e in trip.lodging)
        if trip.lodging and nights > max(0, trip.days - 1):
            out.append(f"숙박 {nights}박 — 출장 {trip.days}일(최대 {max(0, trip.days - 1)}박)보다 많습니다")
    if not trip.public and not trip.tolls:
        out.append("교통비 증빙(대중교통 · 하이패스)이 없습니다")
    if trip.stay:
        wants = {r for e in trip.stay for r in stay_regions(trip, e)}
        other = [e for e in trip.stay if e.shop_region.strip() and stay_regions(trip, e)
                 and region_of(e.shop_region) not in stay_regions(trip, e)]
        unknown = [e for e in trip.stay if not e.shop_region.strip()]
        if other:
            out.append(f"체류 증빙 {len(other)}건 — 영수증 가맹점이 출장지와 다른 시 · 군입니다")
        if unknown and wants:
            out.append(f"체류 증빙 {len(unknown)}건 — 영수증 가맹점이 {', '.join(sorted(wants))} 안인지 확인해 주세요(그림 영수증은 앱이 주소를 못 읽습니다)")
        elif not wants:
            out.append("출장지의 시 · 군을 몰라 체류 영수증의 가맹점 지역을 견주지 못했습니다 — 출장지에 '원주시' 처럼 시 · 군을 넣어 주세요")
    unclear = [e for e in trip.public if not (e.origin.strip() and e.goal.strip()) or e.amount is None]
    if unclear:
        out.append(f"대중교통 증빙 {len(unclear)}건 — 출발지 · 목적지 · 금액을 확인해 주세요")
    if trip.tolls:
        if not trip.maps():
            out.append("하이패스가 있어 자차입니다 — 네이버 지도 최단거리 그림이 없습니다")
        if not any(v for v in trip.legs):
            out.append("하이패스가 있어 자차입니다 — 이동 거리(km)가 없습니다")
        if not trip.fuel:
            out.append("하이패스가 있어 자차입니다 — 연료 종류가 없습니다")
    return out


# ── 네이버 지도 길찾기 글자에서 km ───────────────────────────────────────
# '1시간 10분 76km' · '2분 | 540m'(2026-11-10 담당자 그림 — 시간과 거리 사이에 칸막이, 가까우면 m)
_ROUTE = re.compile(r"(?:(\d+)\s*시간\s*)?(\d+)\s*분\s*[|ㆍ·/]?\s*([\d,]+(?:\.\d+)?)\s*(km|m)(?![a-z])", re.I)


def route_km(text: str) -> float | None:
    """길찾기 결과 글자 → 가장 짧은 거리(km). '거리우선' 경로가 보이면 그 km, 아니면 경로 목록 중 가장 짧은 km.
    경로 요약은 '1시간 10분 76km' 꼴(담당자 그림 2026-11-10) — 구간 안내('중앙고속도로 52km')는 '분' 이 앞에 없어 세지 않는다."""
    flat = re.sub(r"\s+", " ", text or "")
    values = []
    for m in _ROUTE.finditer(flat):
        try:
            value = float(m.group(3).replace(",", ""))
            values.append((m.start(), value / 1000 if m.group(4).lower() == "m" else value))
        except ValueError:
            continue
    if not values:
        return None
    at = flat.find("거리우선")
    if at >= 0:
        after = [(pos, v) for pos, v in values if 0 <= pos - at <= 160]
        if after:
            return after[0][1]
    return min(v for _, v in values)


def blocking(trip: Trip) -> list[str]:
    return [p for p in problems(trip) if p.startswith(("출장자 이름", "증빙 파일이 하나도"))]


def output_path(folder: Path, name: str, day: date | None = None) -> Path:
    """'<이름> 출장증빙_yy.mm.dd.pdf'(출장 시작일, 담당자 2026-10-27) — 같은 이름이 있으면 덮어쓰지 않고 _2, _3."""
    safe = re.sub(r'[\\/:*?"<>|]', " ", name.strip()) or "출장자"
    stem = f"{safe} 출장증빙" + (f"_{day:%y.%m.%d}" if day else "")
    path = folder / f"{stem}.pdf"
    n = 2
    while path.exists():
        path = folder / f"{stem}_{n}.pdf"
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
MAP_WORDS = ("지도", "경로", "길찾기", "최단거리", "map")
GO_WORDS = ("가는", "출발", "갈때", "갈 때")
BACK_WORDS = ("오는", "돌아", "귀가", "복귀", "올때", "올 때")
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
    route_maps: list = field(default_factory=list)      # [가는 길, 오는 길] — 이름에 '가는' · '오는' 이 든 지도 그림
    unsorted: list[Path] = field(default_factory=list)


APPLICATION_WORDS = ("출장신청", "출장명령", "출장계획", "출장품의", "출장신고")   # 출장신청서(travel/application.py 가 읽는다)


def name_prefix(path: Path, names: list[str] | None = None) -> str:
    """파일 이름 앞에 붙은 사람 이름 — '홍길동_참가확인서' · (출장자를 알면) '홍길동 참가확인서'. 없으면 ''."""
    stem = path.stem.strip()
    for name in names or []:
        if name and re.match(rf"{re.escape(name)}(?:[\s_\-]|$)", stem):
            return name
    head = stem.split("_", 1)[0].strip() if "_" in stem else ""
    if _NAME.fullmatch(head) and not any(w in head for w in _NOT_PERSON) and not kind_of(head):
        return head
    return ""


def other_label(path: Path, names: list[str] | None = None) -> str:
    """기타 증빙의 내용 — 파일 이름에서 앞 이름을 떼고 밑줄은 띄어쓰기로('홍길동_참가확인서' → '참가확인서')."""
    stem = path.stem.strip()
    name = name_prefix(path, names)
    if name:
        stem = stem[len(name):]
    return re.sub(r"[\s_]+", " ", stem).strip(" -") or path.stem


def trip_root(saved: str, desktops) -> str:
    """[폴더 추가] · [상위 폴더에서 여러 개] 가 처음 여는 곳 — 담당자 2026-11-10 "C:\\Users\\…\\Desktop\\★★지출진행\\3. 출장비 및 프로그램참여지원비 ·
    출장비 폴더추가할 때는 바로 이폴더가 뜨도록". 설정 travel_root 가 있으면 그것, 없으면 바탕화면의 이름에 '지출진행' 이 든 폴더 안에서 이름에
    '출장비' 가 든 폴더(개인 경로를 코드에 적지 않는다 — 9절). 못 찾으면 ''(운영체제가 고른 곳)."""
    if saved and Path(saved).is_dir():
        return saved
    for desk in desktops:
        try:
            works = sorted(d for d in Path(desk).iterdir() if d.is_dir() and "지출진행" in d.name)
        except OSError:
            continue
        for work in works:
            try:
                hits = sorted(d for d in work.iterdir() if d.is_dir() and "출장비" in d.name)
            except OSError:
                continue
            if hits:
                return str(hits[0])
    return ""


def looks_like_trip(folder: Path, depth: int = 3) -> bool:
    """출장 폴더처럼 보이는지 — 아래(depth 단계까지)에 출장신청서나 증빙 파일(항목 낱말 · 이름_ 이 붙은 파일)이 있으면."""
    try:
        for path in folder.rglob("*"):
            if len(path.relative_to(folder).parts) > depth or not path.is_file():
                continue
            squashed = re.sub(r"\s+", "", path.stem)
            if any(w in squashed for w in APPLICATION_WORDS):
                return True
            if path.suffix.lower() in FILE_SUFFIXES and (kind_of(path.stem) or name_prefix(path)) and "출장증빙" not in squashed:
                return True
    except OSError:
        return False
    return False


def scan_folder(folder: Path, names: list[str] | None = None) -> Scan:
    """출장 폴더를 훑어 항목별 파일을 고른다. 파일 이름이 먼저, 없으면 위 폴더 이름(출장 폴더 아래 몇 단계든).
    출장비 증빙 넷이 아닌데 이름이 앞에 붙은 파일(참가확인서 · 공문 등)은 기타 증빙 — 출장신청서 · 만든 출장증빙은 빼고(담당자 2026-11-10)."""
    out = Scan(files={k: [] for k in KINDS})
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in FILE_SUFFIXES:
            continue
        rel = path.relative_to(folder)
        squashed = re.sub(r"\s+", "", path.stem)
        if "출장증빙" in squashed or any(w in squashed for w in APPLICATION_WORDS):
            continue
        named = name_prefix(path, names)
        if any(w in path.stem for w in SKIP_WORDS) and not named:
            continue
        if path.suffix.lower() in IMAGE_SUFFIXES and any(w in path.stem.lower() for w in MAP_WORDS):
            back = any(w in path.stem for w in BACK_WORDS)
            go = any(w in path.stem for w in GO_WORDS)
            if go or back:
                while len(out.route_maps) < 2:
                    out.route_maps.append(None)
                if out.route_maps[1 if back else 0] is None:
                    out.route_maps[1 if back else 0] = path
            if out.route_map is None and not back:
                out.route_map = path
            continue
        kind = kind_of(path.stem)
        if not kind:
            for part in reversed(rel.parts[:-1]):
                kind = kind_of(part)
                if kind:
                    break
        if not kind and named:
            kind = OTHER
        if kind:
            out.files[kind].append(path)
        else:
            out.unsorted.append(path)
    return out
