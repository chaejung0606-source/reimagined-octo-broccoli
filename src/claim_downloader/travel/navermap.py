"""네이버 지도 최단거리 — 하이패스가 있으면 자차라 출장증빙의 자차 쪽에 네이버 지도 최단거리(거리우선) 그림과 km 를 적는다(담당자 2026-11-10).

담당자: "자차이용의 경우 네이버지도에서 검색한 최단거리 사진과 KM를 알아야 함" · "가는거 오는거 총합 KM" · "네이버지도 최단거리 사진은 이렇게 보이면 됨"
(그림: 왼쪽 길찾기 칸에 경로 목록 — 추천 · 큰길우선 · 무료우선 · 거리우선 '1시간 10분 76km' — 과 오른쪽 지도) ·
"네이버지도 경로검색은 백그라운드에서 자동으로 돌아가기" · "목적지가 불분명해서 검색이 되지 않을경우 … 해당 출장자의 출장목적지를 입력해달라고 입력하는 박스".

그래서 앱 브라우저의 네이버 지도 탭(session._map_page — 처음엔 보이지 않는 브라우저였으나 네이버가 보안문자를 요구해 바꿈)에서 한다: ① 출발지 · 목적지를 네이버 지도 검색(지도 화면이 쓰는 검색 주소를 그 화면 안에서 부름)으로 찾아
② 자동차 길찾기 주소로 열고 ③ '거리우선' 이 하나 보이면 그것을 눌러 ④ 화면을 찍고 ⑤ 화면 글자에서 거리우선 km 를 읽는다(model.route_km).
목적지가 검색되지 않으면 need_place 로 돌려 화면이 그 출장자의 출장목적지를 묻는다.

**네이버 지도 화면은 실측 전이다**(이 클라우드 환경은 네이버에 닿지 않는다 — CLAUDE.md 28절). 검색 주소 · 길찾기 주소 꼴 · 화면 글자는 공개된 웹 화면의
일반적인 모양으로 짐작했다. 어느 단계든 안 되면 그 까닭을 돌려주고(지어내지 않는다), 화면은 [브라우저에서 직접](보이는 브라우저) · [지도 찍기] 로 사람이 한다.
2026-11-10 담당자 PC: 검색 주소(allSearch)의 답에서 '강원대학교 춘천캠퍼스' 도 곳이 안 나왔다(사람은 네이버 지도에서 둘 다 찾음) — 그래서 답의 꼴을 짐작하지 않고
JSON 어디서든 '이름 + 경도 · 위도' 를 읽고(places_in), 그래도 없으면 지도 검색 화면을 열어 그 화면이 스스로 받는 답에서 읽는다(search_on_page).
한 번 찾은 곳 · 사람이 띄운 길찾기 주소의 곳은 기억한다(settings.travel_places — 늘 같은 출발지는 다시 찾지 않는다). 못 찾으면 답의 모양(열쇠 이름)을 기록에.
누르는 것은 '거리우선'(글자가 정확히 같은 것이 하나일 때) 하나뿐이고 값을 넣지 않는다(주소로 연다). 네이버 지도는 로그인이 없다.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

from .model import route_km

BASE = "https://map.naver.com"
DIRECTIONS_URL = BASE + "/p/directions"
SHORTEST = "거리우선"
VIEWPORT = {"width": 1400, "height": 900}        # 담당자 그림처럼 왼쪽 경로 목록과 지도가 한 화면에
SEARCH_NEAR = "127.7300;37.8700"                   # 강원대학교 춘천캠퍼스 둘레부터 — 같은 이름이 여럿이면 가까운 곳이 먼저

# 지도 화면 안에서 부르는 장소 검색 — 같은 출처라 쿠키 · 머리글이 화면과 같다. 답의 모양을 짐작하지 않고 글 그대로 돌려 파이썬이 읽는다(places_in).
# 2026-11-10 담당자 PC 에서 이 검색이 '강원대학교 춘천캠퍼스' 까지 빈 결과였다 — 그래서 이것은 첫 시도일 뿐이고, 안 되면 지도 화면의 검색(search_on_page)으로.
SEARCH_JS = """async ([q, near]) => {
  try {
    const url = '/p/api/search/allSearch?query=' + encodeURIComponent(q) + '&type=all&searchCoord=' + encodeURIComponent(near) + '&boundary=';
    const r = await fetch(url, {credentials: 'include', headers: {'Accept': 'application/json'}});
    const text = await r.text();
    return {ok: r.ok, status: r.status, text: text.slice(0, 400000)};
  } catch (e) { return {ok: false, status: 0, text: '', why: String(e).slice(0, 120)}; }
}"""
SEARCH_POLLS = 24                                  # 지도 화면 검색 — 0.5초씩, 결과가 오면 바로 멈춘다
CAPTCHA_POLLS = 240                                # 네이버가 보안문자를 물으면 사람이 풀 때까지(2분) 기다린다
CAPTCHA_NOTE = "네이버가 보안문자(자동 입력 방지)를 물었습니다"
_API_BLOCKED = False                               # 검색 주소가 보안문자를 물으면 앱을 다시 켤 때까지 지도 검색 화면으로만
# 늘 쓰는 곳 — 검색하지 않고 네이버 장소 번호로 장소 화면을 열어 좌표를 읽는다(담당자 2026-11-10 "출발지는 항상 강원대학교 춘천캠퍼스인데
# 이건 고정이잖아요"). 장소 번호는 담당자가 보낸 네이버 지도 화면(map.naver.com/p/entry/place/11591476 · 강원 춘천시 강원대학길 1)에서.
# 좌표는 적어 두지 않는다 — 네이버가 그 장소에 매긴 좌표를 읽어 기억한다(짐작한 좌표로 길을 찾으면 km 가 달라질 수 있다).
FIXED_PLACES = {"강원대학교춘천캠퍼스": ("강원대학교 춘천캠퍼스", "11591476")}
JSON_LIMIT = 3_000_000

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
    label: str = ""                 # 기록에 남는 이름표 — '출장자 N 가는 길' · '출장자 N 구간 N'(출장자 이름은 넣지 않는다, 28절)
    km: float | None = None
    image: str = ""                 # 찍은 그림 파일
    ok: bool = False
    need_place: str = ""            # 검색되지 않은 곳 — 화면이 그 출장자의 출장목적지를 다시 묻는다
    note: str = ""
    steps: list[str] = field(default_factory=list)
    places: list = field(default_factory=list)     # 배운 곳(사람이 띄운 길찾기 주소에서) — session 이 settings.travel_places 에 더한다
    pending: bool = False           # 네이버 지도 창에 길찾기를 띄워 두고 사람의 확인을 기다림 — [이 경로로 찍기] 로 찍는다
    deferred: bool = False          # 앞 구간을 확인 · 찍은 뒤에 띄운다(창이 하나라 한 구간씩)

    def lines(self) -> list[str]:
        if self.pending:
            head = f"… 네이버 지도 최단거리 {self.label}: {self.origin} → {self.goal} — {self.note}"
        elif self.deferred:
            return [f"… 네이버 지도 최단거리 {self.label}: 앞 구간을 찍은 뒤에 띄웁니다"]
        elif self.ok and self.km is not None:
            head = f"✓ 네이버 지도 최단거리 {self.label}: {self.origin} → {self.goal} {self.km:g}km"
        else:
            head = f"⚠ 네이버 지도 최단거리 {self.label}: {self.origin} → {self.goal} — {self.note or '찾지 못함'}"
        return [head] + ["  " + s for s in self.steps]


def mercator(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 → 웹 메르카토르(m) — 네이버 지도 길찾기 주소의 좌표 꼴."""
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0) * 20037508.34 / 180.0
    return x, y


def directions_url(start: Place | None, goal: Place | None) -> str:
    """자동차 길찾기 주소 — /p/directions/<출발>/<도착>/-/car. 곳마다 'x,y,이름,id,PLACE_POI'(x · y 는 웹 메르카토르), 모르는 곳은 '-'
    (사람이 그 창에서 넣는다)."""
    def part(p: Place | None) -> str:
        if p is None:
            return "-"
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


# ── 찾기 — 네이버 답의 모양에 기대지 않는다 ────────────────────────────────
_X_KEYS = ("x", "lng", "lon", "longitude", "mapx")
_Y_KEYS = ("y", "lat", "latitude", "mapy")
_NAME_KEYS = ("name", "title", "placeName", "businessName", "display", "fullAddress", "roadAddress")
_ADDRESS_KEYS = ("roadAddress", "address", "fullAddress", "commonAddress")
_TAG = re.compile(r"<[^>]+>")


def norm(text: str) -> str:
    """견줄 이름 — 띄어쓰기 · 문장부호를 빼고 소문자('강원 가명정보 활용지원센터' = '강원가명정보활용지원센터')."""
    return re.sub(r"[\W_]+", "", text or "").lower()


def _coord(value) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number > 1_000_000:          # 지역 검색의 mapx · mapy 꼴(경도 × 10^7)
        number /= 10_000_000
    return number


def _first(d: dict, keys) -> object:
    for key in keys:
        value = d.get(key)
        if value not in (None, ""):
            return value
    return None


def places_in(data, limit: int = 60) -> list[Place]:
    """JSON 어디에 있든 '이름 + 경도 · 위도(우리나라)' 가 함께 든 것 — 나온 차례대로. 검색 답의 꼴(result.place.list · GraphQL …)이 바뀌어도 읽힌다."""
    out: list[Place] = []
    seen: set = set()

    def walk(node, depth: int) -> None:
        if len(out) >= limit or depth > 14:
            return
        if isinstance(node, dict):
            x, y = _coord(_first(node, _X_KEYS)), _coord(_first(node, _Y_KEYS))
            name = _first(node, _NAME_KEYS)
            if x is not None and y is not None and 124 <= x <= 132 and 33 <= y <= 39.5 and isinstance(name, str):
                name = _TAG.sub("", name).strip()
                key = (norm(name), round(x, 5), round(y, 5))
                if name and key not in seen:
                    seen.add(key)
                    address = _first(node, _ADDRESS_KEYS)
                    out.append(Place(name=name, x=x, y=y, id=str(_first(node, ("id", "sid", "placeId", "businessId")) or ""),
                                     address=str(address) if isinstance(address, str) else ""))
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                walk(value, depth + 1)

    walk(data, 0)
    return out


def has_captcha(data, depth: int = 0) -> bool:
    """네이버 답에 보안문자 요구(ncaptcha)가 들었는지 — 2026-11-10 담당자 PC: 보이지 않는 브라우저의 검색에 result.ncaptcha 가 오고 곳은 비었다.
    앱은 보안문자를 풀거나 피하지 않는다 — 사람이 앱 브라우저 창에서 풀게 기다린다."""
    if depth > 3:
        return False
    if isinstance(data, dict):
        for key, value in data.items():
            if "captcha" in str(key).lower() and value:
                return True
            if isinstance(value, (dict, list)) and has_captcha(value, depth + 1):
                return True
    elif isinstance(data, list):
        return any(has_captcha(v, depth + 1) for v in data[:5])
    return False


def shape(data, depth: int = 0) -> str:
    """답의 모양(열쇠 이름만) — 못 찾았을 때 기록에 남겨 다음에 고친다. 값은 적지 않는다."""
    if depth > 2:
        return "…"
    if isinstance(data, dict):
        if not data:
            return "{}"
        parts = [f"{k}:{shape(v, depth + 1)}" if isinstance(v, (dict, list)) else (f"{k}=null" if v is None else str(k))
                 for k, v in list(data.items())[:10]]
        return "{" + ",".join(parts) + ("…" if len(data) > 10 else "") + "}"
    if isinstance(data, list):
        return f"[{len(data)}" + (" " + shape(data[0], depth + 1) if data else "") + "]"
    return type(data).__name__


def rank(query: str, places: list[Place], prefer_id: str = "", allow_first: bool = True) -> tuple[Place | None, str]:
    """찾은 곳 중 하나 — 화면이 고른 곳(id) → 이름이 검색어와 같은 곳 → 이름이 검색어를 담은(또는 그 반대) 곳 → (allow_first 면) 첫 결과.
    목적지는 신청서에 적힌 이름과 네이버 이름이 같은 일이 거의 없다 — 비슷한 곳, 없으면 맨 위 결과(담당자 2026-11-10).
    allow_first 는 그 검색어의 검색 답일 때만 — 지도 화면이 함께 받는 주변 가게 · 광고 표시에서 첫 것을 고르면 엉뚱한 곳이 된다
    (2026-11-10 담당자 PC: '강원대학교 춘천캠퍼스' 대신 '포랑 춘천점', 목적지 대신 '호담'). (곳, 고른 까닭)."""
    if not places:
        return None, ""
    if prefer_id:
        for place in places:
            if place.id == prefer_id:
                return place, "지도 화면이 고른 곳"
    whole = norm(query)
    bare = norm(re.sub(r"\([^)]*\)", " ", query or ""))
    for place in places:
        if norm(place.name) in (whole, bare):
            return place, "이름이 같은 곳"
    for place in places:
        name = norm(place.name)
        if len(name) >= 2 and bare and (bare in name or name in bare):
            return place, "이름이 비슷한 곳"
    if not allow_first:
        return None, ""
    return places[0], "첫 결과(이름이 같은 곳 없음)"


def search_api(page, query: str) -> tuple[list[Place], str]:
    """지도 화면 안에서 검색 주소를 불러 — (찾은 곳들, 못 찾았으면 까닭과 답의 모양)."""
    try:
        got = page.evaluate(SEARCH_JS, [query, SEARCH_NEAR])
    except Exception as error:  # noqa: BLE001
        return [], "검색을 부르지 못함: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__)
    if not isinstance(got, dict):
        return [], "검색 답의 모양이 다름"
    if got.get("why"):
        return [], "검색을 부르지 못함: " + str(got["why"])
    text = got.get("text") or ""
    try:
        data = json.loads(text)
    except ValueError:
        head = re.sub(r"\s+", " ", text[:80])
        return [], f"HTTP {got.get('status')} · JSON 아님({head!r})"
    found = places_in(data)
    if not found and has_captcha(data):
        return [], CAPTCHA_NOTE
    return found, "" if found else f"HTTP {got.get('status')} · 곳 없음 · 답 {shape(data)[:240]}"


def _search_answer(url: str) -> bool:
    """그 검색어의 검색 답인지 — 장소 검색(allSearch · instant-search)과 장소 화면의 GraphQL. 주변 가게 · 광고 · 지하철 노선 같은 답은 아니다."""
    low = url.split("?")[0].lower()
    return any(w in low for w in ("allsearch", "instant-search", "graphql")) and not any(w in low for w in ("ads", "bubble", "brand"))


def search_on_page(page, query: str, wait: Callable[[float], None],
                   log: Callable[[str], None] | None = None) -> tuple[list[Place], str, str]:
    """네이버 지도 검색 화면(/p/search/검색어)을 열고, 그 화면이 스스로 받는 답(JSON)에서 곳을 읽는다 — 화면에 결과가 보이면 좌표도 그 답에 있다.
    네이버가 보안문자를 물으면 사람이 그 창에서 풀 때까지(CAPTCHA_POLLS) 기다린다 — 풀면 화면이 다시 검색하고 그 답에서 읽는다.
    (찾은 곳들, 화면이 하나를 골랐으면 그 id, 못 찾았으면 까닭)."""
    seen: list = []

    def keep(response) -> None:          # 알림 자리에서는 담아만 둔다 — 여기서 Playwright 를 부르지 않는다(21절)
        seen.append(response)

    page.on("response", keep)
    read = 0
    found: list[Place] = []          # 그 검색어의 검색 답(allSearch · GraphQL …)에서 읽은 곳
    nearby: list[Place] = []         # 지도 화면이 함께 받은 다른 답(주변 가게 · 광고 표시 …) — 이름이 맞을 때만 쓴다
    paths: list[str] = []
    captcha = False
    try:
        page.goto(f"{BASE}/p/search/{quote(query, safe='')}", wait_until="domcontentloaded")
        polls = 0
        while polls < (CAPTCHA_POLLS if captcha else SEARCH_POLLS):
            polls += 1
            wait(0.5)
            while read < len(seen):
                response = seen[read]
                read += 1
                try:
                    if response.request.resource_type not in ("xhr", "fetch") or "naver" not in response.url:
                        continue
                    body = response.body()
                    if len(body) > JSON_LIMIT:
                        continue
                    data = json.loads(body.decode("utf-8", "replace"))
                except Exception:  # noqa: BLE001 — JSON 이 아닌 답 · 이미 사라진 답
                    continue
                paths.append(response.url.split("?")[0].split("naver.com", 1)[-1][:60])
                bucket = found if _search_answer(response.url) else nearby
                bucket += [p for p in places_in(data) if all((p.name, p.x, p.y) != (q.name, q.x, q.y) for q in bucket)]
                if not captcha and has_captcha(data):
                    captcha = True
                    try:
                        page.bring_to_front()
                    except Exception:  # noqa: BLE001
                        pass
                    if log is not None:
                        log(f"{CAPTCHA_NOTE} — 앱 브라우저의 네이버 지도 창에서 입력해 주세요(2분 기다립니다)")
            if found or rank(query, nearby, allow_first=False)[0] is not None:
                break
    finally:
        page.remove_listener("response", keep)
    chosen = re.search(r"/place/(\d+)", page.url or "")
    named = rank(query, nearby, chosen.group(1) if chosen else "", allow_first=False)[0]
    if not found and named is not None:
        found = [named]
    if not found and captcha:
        return [], "", CAPTCHA_NOTE + " — 2분 안에 풀지 않아 그만두었습니다"
    why = "" if found else (f"검색 화면이 받은 답 {len(paths)}개에 곳 없음" + (f" ({', '.join(dict.fromkeys(paths))[:200]})" if paths else ""))
    return found, chosen.group(1) if chosen else "", why


def place_by_id(page, place_id: str, name: str, wait: Callable[[float], None],
                log: Callable[[str], None] | None = None) -> tuple[Place | None, str]:
    """네이버 장소 화면(/p/entry/place/번호)을 열어 그 장소의 좌표를 읽는다 — 검색을 거치지 않는다. (곳, 못 읽었으면 까닭)."""
    seen: list = []

    def keep(response) -> None:          # 알림 자리에서는 담아만 둔다
        seen.append(response)

    page.on("response", keep)
    read, found, captcha = 0, [], False
    try:
        page.goto(f"{BASE}/p/entry/place/{place_id}", wait_until="domcontentloaded")
        polls = 0
        while polls < (CAPTCHA_POLLS if captcha else SEARCH_POLLS):
            polls += 1
            wait(0.5)
            while read < len(seen):
                response = seen[read]
                read += 1
                try:
                    if response.request.resource_type not in ("xhr", "fetch") or "naver" not in response.url:
                        continue
                    body = response.body()
                    if len(body) > JSON_LIMIT:
                        continue
                    data = json.loads(body.decode("utf-8", "replace"))
                except Exception:  # noqa: BLE001
                    continue
                found += places_in(data)
                if not captcha and has_captcha(data):
                    captcha = True
                    if log is not None:
                        log(f"{CAPTCHA_NOTE} — 앱 브라우저의 네이버 지도 창에서 입력해 주세요(2분 기다립니다)")
            hit = next((p for p in found if p.id == place_id), None) or rank(name, found, allow_first=False)[0]
            if hit is not None:
                hit.id = hit.id or place_id
                return hit, ""
    finally:
        page.remove_listener("response", keep)
    return None, (CAPTCHA_NOTE if captcha else f"장소 화면(번호 {place_id})에서 좌표를 읽지 못했습니다")


def search_place(page, query: str, wait: Callable[[float], None] | None = None,
                 known: dict | None = None, log: Callable[[str], None] | None = None) -> tuple[Place | None, str, list[str]]:
    """네이버 지도에서 곳 하나 — (곳, 못 찾았으면 '검색 결과 없음' 등, 한 일). known 은 전에 찾은 곳(settings.travel_places)."""
    steps: list[str] = []
    for attempt in search_queries(query):
        hit = (known or {}).get(norm(attempt)) or (known or {}).get(norm(re.sub(r"\([^)]*\)", " ", attempt)))
        if hit and not hit.get("found") and not same_place(attempt, hit.get("name", "")):
            # 이름이 다른 기억은 쓰지 않는다 — 앞 판이 주변 가게를 잘못 집어 기억했을 수 있다(2026-11-10 '포랑 춘천점' · '호담')
            steps.append(f"'{attempt}' → 전에 기억한 '{hit.get('name', '')}' 은 이름이 달라 쓰지 않습니다")
            hit = None
        if hit:
            steps.append(f"'{attempt}' → 전에 찾은 곳 '{hit['name']}'")
            return Place(**{k: hit[k] for k in ("name", "x", "y", "id", "address") if k in hit}), "", steps
    fixed = FIXED_PLACES.get(norm(query))
    if fixed and wait is not None:
        place, why = place_by_id(page, fixed[1], fixed[0], wait, log)
        if place is not None:
            steps.append(f"'{query}' → 네이버 장소 {fixed[1]} 의 좌표 ({place.name})")
            return place, "", steps
        steps.append(f"'{query}' → 네이버 장소 {fixed[1]}: {why} — 검색으로 찾아 봅니다")
    global _API_BLOCKED
    why = ""
    for attempt in search_queries(query):          # 괄호 든 곳('…센터 (원주)')은 괄호를 빼고 · 괄호 속 지역을 앞에 두고 한 번 더
        if not _API_BLOCKED:
            found, why = search_api(page, attempt)
            place, how = rank(attempt, found)
            if place is not None:
                steps.append(f"검색 '{attempt}' → {place.name} ({how})")
                return place, "", steps
            steps.append(f"검색 '{attempt}' → {why}")
            if why == CAPTCHA_NOTE:
                _API_BLOCKED = True          # 이번 실행에서는 검색 주소를 더 부르지 않는다 — 부를수록 보안문자를 더 묻는다
        if wait is None:
            continue
        found, chosen, why = search_on_page(page, attempt, wait, log)
        place, how = rank(attempt, found, chosen)
        if place is not None:
            steps.append(f"지도 화면 검색 '{attempt}' → {place.name} ({how})")
            return place, "", steps
        steps.append(f"지도 화면 검색 '{attempt}' → {why}")
        if why.startswith(CAPTCHA_NOTE):
            return None, why, steps          # 사람이 보안문자를 풀지 않았으면 다른 검색어로 되풀이하지 않는다
    return None, "검색 결과 없음", steps


def same_place(query: str, name: str) -> bool:
    """검색어와 곳 이름이 같은 곳을 가리키는지 — 띄어쓰기 · 문장부호 · 괄호 속 지역을 빼고 같거나 한쪽이 다른 쪽을 담으면."""
    return rank(query, [Place(name=name, x=0.0, y=0.0)], allow_first=False)[0] is not None


def remember(known: dict | None, query: str, place: Place) -> None:
    """찾은 곳을 known 에 — 검색어 이름과 네이버 이름 둘로. 'found' 는 이 앱 판이 그 검색어로 찾은 곳이라는 표시 —
    목적지는 신청서의 이름과 네이버 이름이 거의 다르므로(담당자 2026-11-10) 이름이 달라도 이 표시가 있으면 쓴다."""
    if known is None:
        return
    value = {"name": place.name, "x": place.x, "y": place.y, "id": place.id, "address": place.address, "found": True}
    for key in {norm(query), norm(re.sub(r"\([^)]*\)", " ", query)), norm(place.name)} - {""}:
        known[key] = value


def mercator_back(x: float, y: float) -> tuple[float, float]:
    """웹 메르카토르(m) → WGS84(경도, 위도)."""
    lon = x / 20037508.34 * 180.0
    lat = math.atan(math.exp(y / 20037508.34 * math.pi)) * 360.0 / math.pi - 90.0
    return lon, lat


def places_from_url(url: str) -> list[Place]:
    """길찾기 주소(/p/directions/x,y,이름,id,종류/…)의 곳들 — 사람이 브라우저에서 띄운 길찾기에서 출발지 · 목적지를 배운다."""
    if "/directions/" not in (url or ""):
        return []
    out = []
    for part in url.split("?")[0].split("/directions/", 1)[1].split("/"):
        bits = unquote(part).split(",")          # 쉼표가 %2C 로 적힌 주소도
        if len(bits) < 3:
            continue
        try:
            x, y = float(bits[0]), float(bits[1])
        except ValueError:
            continue
        lon, lat = mercator_back(x, y) if abs(x) > 1000 else (x, y)
        name = bits[2].strip()
        if name and 124 <= lon <= 132 and 33 <= lat <= 39.5:
            out.append(Place(name=name, x=lon, y=lat, id=bits[3] if len(bits) > 3 else ""))
    return out


CONFIRM_NOTE = "네이버 지도 창에서 출발지 · 목적지를 확인하고 [이 경로로 찍기] 를 누르세요(틀리면 그 창에서 목적지를 다시 고르고 길찾기)"


def find_route(page, origin: str, goal: str, out: Path, log: Callable[[str], None],
               wait: Callable[[float], None], label: str = "", known: dict | None = None, confirm: bool = False) -> RouteResult:
    """origin → goal 의 자동차 거리우선 경로를 찾아 out 에 화면을 찍는다. page 는 네이버 지도 창.
    known 은 전에 찾은 곳(이름 → 곳) — 새로 찾은 곳을 더한다.
    confirm 이면 찍지 않고 길찾기를 띄워 둔 채 사람의 확인을 기다린다(pending — 담당자 2026-11-10 "네이버 브라우저 열어서 경로 검색하고
    사용자가 목적지를 확인하거나 틀리면 재설정해가지고 그 상태를 어플에서 캡쳐하고 이동거리를 자동입력"). 곳을 못 찾았으면 아는 곳만 넣어 띄운다."""
    if confirm:
        return _open_for_confirm(page, origin, goal, log, wait, label, known)
    result = RouteResult(origin=origin, goal=goal, label=label)
    if not origin.strip() or not goal.strip():
        result.need_place = goal if not goal.strip() else ""
        result.note = "출발지 · 목적지가 비어 있습니다"
        return result
    if not page.url.startswith(BASE):
        page.goto(DIRECTIONS_URL, wait_until="domcontentloaded")
        wait(1.5)
    places = []
    for role, query in (("출발지", origin), ("목적지", goal)):
        place, why, steps = search_place(page, query, wait, known, log)
        result.steps += steps
        if place is None:
            result.note = f"{role} '{query}' 를 네이버 지도에서 찾지 못했습니다 ({why})"
            # 목적지만 다시 묻는다 — 출발지(늘 같은 곳)부터 안 되면 곳 이름이 아니라 앱의 검색이 안 된 것이다(2026-11-10 담당자 PC)
            if role == "목적지" and why == "검색 결과 없음":
                result.need_place = query
            return result
        remember(known, query, place)
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
    # 그림 이름(out.name)에는 출장자 이름이 든다 — 기록에는 남기지 않는다(28절, 그림 경로는 화면 · result.image 에)
    log(f"네이버 지도 최단거리 {label}: {km:g}km — 지도 그림 저장")
    return result


def _open_for_confirm(page, origin: str, goal: str, log: Callable[[str], None], wait: Callable[[float], None],
                      label: str, known: dict | None) -> RouteResult:
    """길찾기를 네이버 지도 창에 띄워 두고 사람의 확인을 기다린다 — 찍기 · km 는 [이 경로로 찍기](capture)."""
    result = RouteResult(origin=origin, goal=goal, label=label, pending=True)
    places: list[Place | None] = []
    missing = []
    for role, query in (("출발지", origin), ("목적지", goal)):
        place = None
        if query.strip():
            place, why, steps = search_place(page, query, wait, known, log)
            result.steps += steps
            if place is not None:
                remember(known, query, place)
            elif why.startswith(CAPTCHA_NOTE):
                result.steps.append(why)
        if place is None:
            missing.append(role)
        places.append(place)
    url = directions_url(*places)
    page.goto(url, wait_until="domcontentloaded")
    if not missing:
        for _ in range(30):             # 경로 목록이 뜰 때까지(최대 15초) — 뜨면 '거리우선' 을 골라 둔다
            wait(0.5)
            if route_km(page_text(page)) is not None:
                break
        try:
            clicked = page.evaluate(CLICK_SHORTEST_JS, SHORTEST)
        except Exception:  # noqa: BLE001
            clicked = 0
        result.steps.append(f"'{SHORTEST}' " + ("골라 둠" if clicked == 1 else f"보이는 것 {clicked}개 — 고르지 않음"))
        result.km = route_km(page_text(page))
        result.note = CONFIRM_NOTE
    else:
        result.note = (f"{' · '.join(missing)}를 찾지 못했습니다 — 네이버 지도 창에서 {' · '.join(missing)}를 넣고 길찾기를 누른 뒤 "
                       "[이 경로로 찍기] 를 누르세요")
    try:
        page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass
    log(f"네이버 지도 창에 길찾기를 띄웠습니다({label}) — 확인 기다림")
    return result


def capture(page, out: Path, label: str = "", wait: Callable[[float], None] | None = None) -> RouteResult:
    """사람이 확인한 (보이는 브라우저의) 길찾기 화면을 찍고 km 를 읽는다. '거리우선' 이 하나 보이면 그것을 골라 찍는다(최단거리 —
    담당자 2026-11-10 "네이버지도에서 검색한 최단거리"). 주소의 출발지 · 목적지는 places 로 돌려준다(앱이 기억)."""
    result = RouteResult(label=label)
    if wait is not None:
        try:
            clicked = page.evaluate(CLICK_SHORTEST_JS, SHORTEST)
        except Exception:  # noqa: BLE001
            clicked = 0
        if clicked == 1:
            wait(2.0)                   # 지도에 그 경로가 그려질 때까지
            result.steps.append(f"'{SHORTEST}' 골라 찍음")
    result.km = route_km(page_text(page))
    result.places = places_from_url(page.url)
    if result.places:
        result.origin, result.goal = result.places[0].name, result.places[-1].name
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
