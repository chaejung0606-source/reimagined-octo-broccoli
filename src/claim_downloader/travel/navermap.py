"""네이버 지도 최단거리 — 하이패스가 있으면 자차라 출장증빙의 자차 쪽에 네이버 지도 최단거리(거리우선) 그림과 km 를 적는다(담당자 2026-11-10).

담당자: "자차이용의 경우 네이버지도에서 검색한 최단거리 사진과 KM를 알아야 함" · "가는거 오는거 총합 KM" · "네이버지도 최단거리 사진은 이렇게 보이면 됨"
(그림: 왼쪽 길찾기 칸에 경로 목록 — 추천 · 큰길우선 · 무료우선 · 거리우선 '1시간 10분 76km' — 과 오른쪽 지도) ·
"네이버지도 경로검색은 백그라운드에서 자동으로 돌아가기" · "목적지가 불분명해서 검색이 되지 않을경우 … 해당 출장자의 출장목적지를 입력해달라고 입력하는 박스".

그래서 보이지 않는 브라우저(session._map_page)에서 한다: ① 출발지 · 목적지를 네이버 지도 검색(지도 화면이 쓰는 검색 주소를 그 화면 안에서 부름)으로 찾아
② 자동차 길찾기 주소로 열고 ③ '거리우선' 이 하나 보이면 그것을 눌러 ④ 화면을 찍고 ⑤ 화면 글자에서 거리우선 km 를 읽는다(model.route_km).
목적지가 검색되지 않으면 need_place 로 돌려 화면이 그 출장자의 출장목적지를 묻는다.

**네이버 지도 화면은 실측 전이다**(이 클라우드 환경은 네이버에 닿지 않는다 — CLAUDE.md 28절). 검색 주소 · 길찾기 주소 꼴 · 화면 글자는 공개된 웹 화면의
일반적인 모양으로 짐작했다. 어느 단계든 안 되면 그 까닭을 돌려주고(지어내지 않는다), 화면은 [브라우저에서 직접](보이는 브라우저) · [지도 찍기] 로 사람이 한다.
누르는 것은 '거리우선'(글자가 정확히 같은 것이 하나일 때) 하나뿐이고 값을 넣지 않는다(주소로 연다). 네이버 지도는 로그인이 없다.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from .model import route_km

BASE = "https://map.naver.com"
DIRECTIONS_URL = BASE + "/p/directions"
SHORTEST = "거리우선"
VIEWPORT = {"width": 1400, "height": 900}        # 담당자 그림처럼 왼쪽 경로 목록과 지도가 한 화면에
SEARCH_NEAR = "127.7300;37.8700"                   # 강원대학교 춘천캠퍼스 둘레부터 — 같은 이름이 여럿이면 가까운 곳이 먼저

# 지도 화면 안에서 부르는 장소 검색 — 같은 출처라 쿠키 · 머리글이 화면과 같다. 결과 꼴이 다르면 ok=false 로 까닭만.
SEARCH_JS = """async ([q, near]) => {
  try {
    const url = '/p/api/search/allSearch?query=' + encodeURIComponent(q) + '&type=all&searchCoord=' + encodeURIComponent(near) + '&boundary=';
    const r = await fetch(url, {credentials: 'include', headers: {'Accept': 'application/json'}});
    if (!r.ok) return {ok: false, why: 'HTTP ' + r.status};
    const j = await r.json();
    const res = (j && j.result) || {};
    const list = ((res.place || {}).list || []).concat(((res.address || {}).jibunsAddress || {}).list || []);
    return {ok: true, list: list.slice(0, 5).map(p => ({
      id: String(p.id || p.sid || ''), name: String(p.name || p.title || p.fullAddress || q),
      x: Number(p.x), y: Number(p.y), address: String(p.roadAddress || p.address || p.fullAddress || '')}))
      .filter(p => isFinite(p.x) && isFinite(p.y) && p.x && p.y)};
  } catch (e) { return {ok: false, why: String(e).slice(0, 120)}; }
}"""

TEXT_JS = "() => (document.body && document.body.innerText) || ''"

# 글자가 정확히 '거리우선' 인 보이는 요소가 하나면 그 항목을 누른다 — 여럿이거나 없으면 누르지 않고 수만 돌려준다
CLICK_SHORTEST_JS = """(word) => {
  const hits = [...document.querySelectorAll('body *')].filter(el => {
    if ((el.textContent || '').trim() !== word) return false;
    if ([...el.children].some(c => (c.textContent || '').trim() === word)) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  if (hits.length !== 1) return hits.length;
  const target = hits[0].closest('a, button, li, [role=button], [role=tab], [role=option]') || hits[0];
  target.click();
  return 1;
}"""


@dataclass
class Place:
    name: str
    x: float          # 경도(WGS84)
    y: float          # 위도
    id: str = ""
    address: str = ""


@dataclass
class RouteResult:
    origin: str = ""
    goal: str = ""
    label: str = ""                 # 가는 길 · 오는 길 · 구간 N
    km: float | None = None
    image: str = ""                 # 찍은 그림 파일
    ok: bool = False
    need_place: str = ""            # 검색되지 않은 곳 — 화면이 그 출장자의 출장목적지를 다시 묻는다
    note: str = ""
    steps: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        head = (f"✓ 네이버 지도 최단거리 {self.label}: {self.origin} → {self.goal} {self.km:g}km" if self.ok and self.km is not None
                else f"⚠ 네이버 지도 최단거리 {self.label}: {self.origin} → {self.goal} — {self.note or '찾지 못함'}")
        return [head] + ["  " + s for s in self.steps]


def mercator(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 → 웹 메르카토르(m) — 네이버 지도 길찾기 주소의 좌표 꼴."""
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0) * 20037508.34 / 180.0
    return x, y


def directions_url(start: Place, goal: Place) -> str:
    """자동차 길찾기 주소 — /p/directions/<출발>/<도착>/-/car. 곳마다 'x,y,이름,id,PLACE_POI'(x · y 는 웹 메르카토르)."""
    def part(p: Place) -> str:
        x, y = mercator(p.x, p.y)
        kind = "PLACE_POI" if p.id else "ADDRESS_POI"
        return f"{x:.7f},{y:.7f},{quote(p.name, safe='')},{p.id},{kind}"
    return f"{DIRECTIONS_URL}/{part(start)}/{part(goal)}/-/car"


def page_text(page) -> str:
    """창과 그 안 프레임의 글자 — 길찾기 칸이 프레임 안에 있을 수도 있다."""
    out = []
    for frame in page.frames:
        try:
            out.append(frame.evaluate(TEXT_JS) or "")
        except Exception:  # noqa: BLE001 — 닫히는 프레임
            continue
    return "\n".join(out)


def search_queries(text: str) -> list[str]:
    """검색어 차례 — 그대로 → 괄호를 뺀 것 → 괄호 속(지역)을 앞에 둔 것. 출장신청서의 출장지가 '강원가명정보활용지원센터 (원주)' 꼴이다(2026-11-10)."""
    text = (text or "").strip()
    out = [text]
    inside = re.findall(r"\(([^)]*)\)", text)
    bare = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()
    if bare and bare != text:
        out.append(bare)
        if inside and inside[0].strip():
            out.append(f"{inside[0].strip()} {bare}")
    return list(dict.fromkeys(q for q in out if q))


def search_place(page, query: str) -> tuple[Place | None, str]:
    """네이버 지도 검색으로 곳 하나 — (곳, 까닭). 결과가 없으면 (None, '검색 결과 없음')."""
    try:
        got = page.evaluate(SEARCH_JS, [query, SEARCH_NEAR])
    except Exception as error:  # noqa: BLE001
        return None, "검색을 부르지 못함: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__)
    if not isinstance(got, dict) or not got.get("ok"):
        return None, "검색을 부르지 못함: " + str((got or {}).get("why", "모양이 다름"))
    found = got.get("list") or []
    if not found:
        return None, "검색 결과 없음"
    p = found[0]
    return Place(name=p.get("name") or query, x=float(p["x"]), y=float(p["y"]), id=p.get("id", ""), address=p.get("address", "")), ""


def find_route(page, origin: str, goal: str, out: Path, log: Callable[[str], None],
               wait: Callable[[float], None], label: str = "") -> RouteResult:
    """origin → goal 의 자동차 거리우선 경로를 찾아 out 에 화면을 찍는다. page 는 네이버 지도가 열린 (보이지 않는) 창."""
    result = RouteResult(origin=origin, goal=goal, label=label)
    if not origin.strip() or not goal.strip():
        result.need_place = goal if not goal.strip() else origin
        result.note = "출발지 · 목적지가 비어 있습니다"
        return result
    if not page.url.startswith(BASE):
        page.goto(DIRECTIONS_URL, wait_until="domcontentloaded")
        wait(1.5)
    places = []
    for query in (origin, goal):
        place, why = None, ""
        for attempt in search_queries(query):          # 괄호 든 곳('…센터 (원주)')은 괄호를 빼고 · 괄호 속 지역을 앞에 두고 한 번 더
            place, why = search_place(page, attempt)
            result.steps.append(f"검색 '{attempt}' → {place.name if place else why}")
            if place is not None or why != "검색 결과 없음":
                break
        if place is None:
            result.note = f"'{query}' 를 네이버 지도에서 찾지 못했습니다 ({why})"
            if why == "검색 결과 없음":
                result.need_place = query
            return result
        places.append(place)
    url = directions_url(*places)
    page.goto(url, wait_until="domcontentloaded")
    km = None
    for _ in range(30):                 # 경로 목록이 뜰 때까지(최대 15초)
        wait(0.5)
        km = route_km(page_text(page))
        if km is not None:
            break
    if km is None:
        result.note = "길찾기 결과(경로 km)가 화면에 나오지 않았습니다"
        result.steps.append("길찾기 주소: " + url.split("/-/")[0][:80] + "…")
        return result
    try:
        clicked = page.evaluate(CLICK_SHORTEST_JS, SHORTEST)
    except Exception:  # noqa: BLE001
        clicked = 0
    result.steps.append(f"'{SHORTEST}' " + ("누름" if clicked == 1 else f"보이는 것 {clicked}개 — 누르지 않음"))
    if clicked == 1:
        wait(2.0)                       # 지도에 그 경로가 그려질 때까지
        km = route_km(page_text(page)) or km
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out))
    result.km, result.image, result.ok = km, str(out), True
    log(f"네이버 지도 최단거리 {label}: {km:g}km — {out.name}")
    return result


def capture(page, out: Path, label: str = "") -> RouteResult:
    """사람이 (보이는 브라우저에서) 띄운 길찾기 화면을 그대로 찍고 km 를 읽는다 — 자동 찾기가 안 될 때의 길."""
    result = RouteResult(label=label)
    result.km = route_km(page_text(page))
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out))
    result.image, result.ok = str(out), True
    if result.km is None:
        result.note = "화면에서 경로 km 를 읽지 못했습니다 — km 를 직접 적으세요"
    return result


def shot_path(folder: Path, label: str) -> Path:
    """찍은 지도 그림 이름 — '네이버지도 최단거리_가는 길.png'. 같은 이름이 있으면 덮어쓰지 않고 _2."""
    stem = f"네이버지도 최단거리_{label}".strip("_ ")
    path = folder / f"{stem}.png"
    n = 2
    while path.exists():
        path = folder / f"{stem}_{n}.png"
        n += 1
    return path
