"""네이버 지도 최단거리 — 하이패스가 있으면 자차라 출장증빙의 자차 쪽에 네이버 지도 최단거리(거리우선) 그림과 km 를 적는다(담당자 2026-11-10).

담당자: "자차이용의 경우 네이버지도에서 검색한 최단거리 사진과 KM를 알아야 함" · "가는거 오는거 총합 KM" · "네이버지도 최단거리 사진은 이렇게 보이면 됨"
(그림: 왼쪽 길찾기 칸에 경로 목록 — 추천 · 큰길우선 · 무료우선 · 거리우선 '1시간 10분 76km' — 과 오른쪽 지도) ·
"네이버지도 경로검색은 백그라운드에서 자동으로 돌아가기" · "목적지가 불분명해서 검색이 되지 않을경우 … 해당 출장자의 출장목적지를 입력해달라고 입력하는 박스".

그래서 앱 브라우저의 네이버 지도 탭(session._map_page — 처음엔 보이지 않는 브라우저였으나 네이버가 보안문자를 요구해 바꿈)에서 한다: ① 사람이 하듯
출발지 · 목적지마다 네이버 지도 검색(늘 같은 출발지는 장소 번호로 장소 화면)을 한 번 열고 그 화면이 보여 주는 결과(프레임의 Apollo 상태 · 검색 답)에서
이름이 같거나 가장 비슷한 곳, 없으면 맨 위 결과를 고른다 — 좌표를 못 읽으면 장소 화면의 [출발] · [도착] 을 눌러 네이버가 여는 길찾기 주소에서 읽는다(look_up)
② 자동차 길찾기 주소로 열고 '거리우선' 을 골라 둔 채 사람이 판단하게 기다린다(confirm) ③ [이 경로로 찍기] 가 화면을 찍고 거리우선 km 를 읽는다(capture · model.route_km).
한 번 찾은 곳 · 사람이 띄운 길찾기 주소의 곳은 기억한다(settings.travel_places — 늘 같은 출발지는 다시 찾지 않는다). 못 찾으면 그 화면의 프레임 · 답 모양을 기록에.

**네이버 지도 화면은 실측 전이다**(이 클라우드 환경은 네이버에 닿지 않는다 — CLAUDE.md 28절). 어느 단계든 안 되면 그 까닭을 돌려주고(지어내지 않는다),
사람이 그 창에서 고친 뒤 [이 경로로 찍기] 를 누른다. 누르는 것은 '거리우선' 과 장소 화면의 '출발' · '도착'(글자가 정확히 같은 것이 하나일 때)뿐이고
값을 넣지 않는다(주소로 연다). 네이버 지도는 로그인이 없다. 보안문자는 풀거나 피하지 않는다 — 사람이 그 창에서 푼다.
"""
from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import math
import os
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
# 찍을 때의 화면 — 앱 브라우저 창 크기와 상관없이 가로로 긴 16:9(담당자 2026-11-11 "지도 경로가 잘렸습니다 … 이게 보통 가로로 긴 이미지인데" —
# 창이 좁으면 지도도 좁아 경로가 오른쪽에서 잘렸다). 창은 그대로 두고 찍는 동안만 화면 크기를 흉내 낸다(CDP Emulation — 끝나면 되돌림)
CAPTURE_SIZE = (1600, 900)
MAP_DIR = "출장지도"                              # 찍은 지도 그림은 앱 사용자 폴더(~/.claim-downloader/출장지도)에 — 출장 폴더에는 남기지 않는다

# 곳 찾기 — 사람이 하듯 네이버 지도에서 한 번 검색하고(또는 장소 번호로 장소 화면을 열고), 그 화면이 보여 주는 결과를 읽는다(담당자 2026-11-10
# "똑같은 목적지를 계속 검색해봤자 똑같은 결과만 나옵니다 · 처음 검색했을 때 가장 유사한 … 맨 처음에 뜬 장소를 선택해서 자동차 경로탐색 · 사용자가 판단하게 ·
# 지금은 너무 느립니다" · "강원대학교 춘천캠퍼스 검색하면 바로 뜨고 출발을 누르면 경로 탐색이 됩니다" · "가장 효율적인 방법과 루트").
# 19:34 담당자 PC: 화면에는 결과가 바로 떴는데 앱은 화면이 받는 JSON 만 보아 곳을 못 읽고, 검색어를 바꿔 네 번(한 번에 12초) 다시 찾았다 —
# 결과 목록 · 장소 화면은 pcmap.place.naver.com 프레임이고 그 내용은 프레임의 Apollo 상태(window.__APOLLO_STATE__)에 이미 들어 있다(HTML 로 와서 JSON 답이 아니다).
POLL = 0.3                                         # 0.3초마다 본다 — 고를 수 있게 되면 바로 멈춘다
LOOK_POLLS = 25                                    # 한 번 찾는 데 ≈7.5초까지
CLICK_AFTER = 8                                    # ≈2.4초가 지나도 장소 화면에서 좌표를 못 읽으면 그 화면의 [출발] · [도착] 을 눌러 네이버가 여는 길찾기 주소에서 읽는다
ROUTE_POLLS = 34                                   # 길찾기 결과(경로 km)를 ≈10초까지 기다린다
CAPTCHA_POLLS = 400                                # 네이버가 보안문자를 물으면 사람이 풀 때까지(2분) 기다린다
CAPTCHA_NOTE = "네이버가 보안문자(자동 입력 방지)를 물었습니다"
# 늘 쓰는 곳 — 검색하지 않고 네이버 장소 번호로 장소 화면을 열어 좌표를 읽는다(담당자 2026-11-10 "출발지는 항상 강원대학교 춘천캠퍼스인데
# 이건 고정이잖아요"). 장소 번호는 담당자가 보낸 네이버 지도 화면(map.naver.com/p/entry/place/11591476 · 강원 춘천시 강원대학길 1)에서.
# 좌표는 적어 두지 않는다 — 네이버가 그 장소에 매긴 좌표를 읽어 기억한다(짐작한 좌표로 길을 찾으면 km 가 달라질 수 있다). 한 번 읽으면 다시 열지 않는다.
FIXED_PLACES = {"강원대학교춘천캠퍼스": ("강원대학교 춘천캠퍼스", "11591476")}
JSON_LIMIT = 3_000_000

TEXT_JS = "() => (document.body && document.body.innerText) || ''"

# 프레임의 Apollo 상태(네이버 장소 화면 · 검색 목록이 그린 내용) — 읽기만 한다
STATE_JS = """() => {
  try { const s = window.__APOLLO_STATE__; return s ? JSON.stringify(s) : ''; } catch (e) { return ''; }
}"""
STATE_LIMIT = 8_000_000

# 글자가 정확히 word('거리우선' · 장소 화면의 '출발' · '도착') 인 보이는 요소가 하나면 그 항목을 누른다 — 여럿이거나 없으면 누르지 않고 수만 돌려준다
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


# 찍을 때 지도를 가리는 '거리우선' 세부 경로 창을 잠깐 숨긴다(담당자 2026-11-10 "이경로로찍기 클릭하면 쓸데없이 세부경로가 자꾸 지도를 가리는데
# 지도 가리지 않게 해서 캡쳐할 수 있도록" — 그림: 왼쪽 경로 목록의 '거리우선' 을 고르면 지도 위에 같은 '거리우선' 머리의 세부 경로 창이 뜬다).
# 창의 [X] 를 누르면 고른 경로가 풀릴 수 있어 누르지 않고, 찍는 동안만 보이지 않게 했다가 되돌린다(HIDE_DETAIL_JS · SHOW_DETAIL_JS).
# 고르는 법: 보이는 '거리우선' 글자 둘 중 오른쪽(지도 위) 것에서 위로 올라가되, 왼쪽 목록의 것을 품거나 · 지도 그림(canvas)을 품거나 ·
# 창 폭의 60% 를 넘는 조상 앞에서 멈춘다 — 세부 창은 통째로, 지도는 숨기지 않게.
HIDE_DETAIL_JS = """(word) => {
  const named = el => { const t = (el.textContent || '').replace(/\\s+/g, ''); return t === word || (t.length <= word.length + 3 && t.endsWith(word)); };
  const hits = [...document.querySelectorAll('body *')].filter(el => {
    if (!named(el)) return false;
    if ([...el.children].some(named)) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }).map(el => [el, el.getBoundingClientRect()]).sort((a, b) => a[1].left - b[1].left);
  if (hits.length < 2) return 0;
  const list = hits[0], detail = hits[hits.length - 1];
  if (detail[1].left < list[1].right + 20) return 0;
  let panel = detail[0];
  while (panel.parentElement && panel.parentElement !== document.body) {
    const up = panel.parentElement;
    if (up.contains(list[0]) || up.querySelector('canvas')) break;
    if (up.getBoundingClientRect().width > window.innerWidth * 0.6) break;
    panel = up;
  }
  if (panel.querySelector('canvas') || panel.contains(list[0])) return 0;
  panel.setAttribute('data-coss-hidden', panel.style.visibility || '-');
  panel.style.visibility = 'hidden';
  return 1;
}"""
SHOW_DETAIL_JS = """() => {
  let n = 0;
  for (const el of document.querySelectorAll('[data-coss-hidden]')) {
    const was = el.getAttribute('data-coss-hidden');
    el.style.visibility = was === '-' ? '' : was;
    el.removeAttribute('data-coss-hidden');
    n++;
  }
  return n;
}"""


# 넓힌 화면에서 경로 전체가 보이게 — 지도 오른쪽 아래의 '전체'(경로 전체 보기, 담당자 그림 2026-11-11) 단추가 하나 보이면 누른다.
# 지도 보기만 바뀐다(값 · 경로는 그대로). 지도 쪽(창의 오른쪽 · 아래)에 있는 것만 — 목록의 '전체' 같은 거르기 글은 아니다
FIT_ROUTE_JS = """() => {
  const plain = el => (el.textContent || '').replace(/\\s+/g, '');
  const hits = [...document.querySelectorAll('body *')].filter(el => {
    if (plain(el) !== '전체') return false;
    if ([...el.children].some(c => plain(c) === '전체')) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.left > innerWidth * 0.55 && r.top > innerHeight * 0.4;
  });
  if (hits.length !== 1) return hits.length;
  (hits[0].closest('a, button, [role=button]') || hits[0]).click();
  return 1;
}"""


def _wide_view(page) -> Callable[[], None] | None:
    """찍는 동안 화면을 CAPTURE_SIZE 로 — 되돌리는 함수(못 하면 None — 창 그대로 찍는다). 앱 브라우저(창 크기를 따르는 화면, no_viewport)는
    창은 그대로 두고 CDP 로 화면 크기만 흉내 냈다가 지우고, 화면 크기를 정해 둔 페이지(시험 · 옛 보이지 않는 브라우저)는 크기를 바꿨다가 되돌린다."""
    width, height = CAPTURE_SIZE
    try:
        before = page.viewport_size
    except Exception:  # noqa: BLE001
        before = None
    if before:
        try:
            page.set_viewport_size({"width": width, "height": height})
        except Exception:  # noqa: BLE001
            return None

        def back() -> None:
            try:
                page.set_viewport_size(before)
            except Exception:  # noqa: BLE001
                pass
        return back
    try:
        session = page.context.new_cdp_session(page)
        session.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 0, "mobile": False})
    except Exception:  # noqa: BLE001 — Chromium 이 아니거나 창이 닫히는 중
        return None

    def clear() -> None:
        try:
            session.send("Emulation.clearDeviceMetricsOverride")
            session.detach()
        except Exception:  # noqa: BLE001
            pass
    return clear


def screenshot_clear(page, out: Path, wait: Callable[[float], None] | None = None) -> int:
    """넓은 화면(CAPTURE_SIZE)에서 경로 전체를 보이게 하고 지도를 가리는 세부 경로 창을 잠깐 숨기고 찍은 뒤 되돌린다 — 숨긴 창 수(없으면 0)."""
    restore = _wide_view(page)
    if restore is not None and wait is not None:
        wait(0.8)                       # 지도가 넓어진 화면에 맞춰 다시 그려질 때까지
        try:
            fitted = page.evaluate(FIT_ROUTE_JS)
        except Exception:  # noqa: BLE001
            fitted = 0
        if fitted == 1:
            wait(1.2)
    hidden = 0
    for frame in list(page.frames):
        try:
            hidden += int(frame.evaluate(HIDE_DETAIL_JS, SHORTEST) or 0)
        except Exception:  # noqa: BLE001 — 닫히는 프레임
            continue
    if hidden and wait is not None:
        wait(0.3)                       # 다시 그려질 때까지
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(out))
    finally:
        if hidden:
            for frame in list(page.frames):
                try:
                    frame.evaluate(SHOW_DETAIL_JS)
                except Exception:  # noqa: BLE001
                    continue
        if restore is not None:
            restore()
    return hidden


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
    """JSON 어디에 있든 '이름 + 경도 · 위도(우리나라)' 가 함께 든 것(이름 곁의 좌표 묶음도) — 나온 차례대로. 답의 꼴이 바뀌어도 읽힌다."""
    out: list[Place] = []
    seen: set = set()

    def walk(node, depth: int) -> None:
        if len(out) >= limit or depth > 14:
            return
        if isinstance(node, dict):
            x, y = _coord(_first(node, _X_KEYS)), _coord(_first(node, _Y_KEYS))
            name = _first(node, _NAME_KEYS)
            kind = str(node.get("__typename") or "")
            if kind.startswith("Ad") or "Advert" in kind or node.get("isAd") is True or node.get("isAdPlace") is True:
                name = None              # 검색 목록 맨 위의 광고 — 맨 위 결과로 고르지 않는다
            if (x is None or y is None) and isinstance(name, str):
                # 장소 화면의 꼴 — 이름 곁에 좌표 묶음(coordinate: {x, y})
                for value in node.values():
                    if isinstance(value, dict) and len(value) <= 8:
                        cx, cy = _coord(_first(value, _X_KEYS)), _coord(_first(value, _Y_KEYS))
                        if cx is not None and cy is not None:
                            x, y = cx, cy
                            break
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
                return place, "네이버가 연 곳"
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
    best = max(places, key=lambda p: similarity(bare or whole, norm(p.name)))
    if similarity(bare or whole, norm(best.name)) >= 0.5:
        return best, "이름이 가장 비슷한 곳"
    region = norm(" ".join(re.findall(r"\(([^)]*)\)", query or "")))
    if region:
        for place in places:
            if region in norm(place.address):
                return place, f"주소에 '{region}' 이 든 첫 결과"
    return places[0], "첫 결과(이름이 같은 곳 없음)"


def similarity(a: str, b: str) -> float:
    """두 이름이 얼마나 비슷한지(0~1) — 두 글자 묶음이 겹치는 정도('인터불고호텔원주' ↔ '호텔인터불고원주')."""
    def pairs(text: str) -> list[str]:
        return [text[i:i + 2] for i in range(len(text) - 1)]
    left, right = pairs(a), pairs(b)
    if not left or not right:
        return 1.0 if a and a == b else 0.0
    rest = list(right)
    common = 0
    for pair in left:
        if pair in rest:
            rest.remove(pair)
            common += 1
    return 2 * common / (len(left) + len(right))


def _search_answer(url: str) -> bool:
    """그 검색어의 검색 답인지 — 장소 검색(allSearch · instant-search)과 장소 화면의 GraphQL. 주변 가게 · 광고 · 지하철 노선 같은 답은 아니다."""
    low = url.split("?")[0].lower()
    return any(w in low for w in ("allsearch", "instant-search", "graphql")) and not any(w in low for w in ("ads", "bubble", "brand"))


_ENTRY = re.compile(r"place\.naver\.com/(?:[a-z]+/)?(\d{4,})(?:[/?#]|$)")
_CHOSEN = re.compile(r"/place/(\d{4,})")


def apollo_tree(state: dict):
    """Apollo 상태(정규화된 캐시) — ROOT_QUERY 부터 '__ref' 를 풀어 화면에 보이는 차례(검색 목록의 첫 결과가 먼저)로, 그다음 나머지 그대로."""
    budget = [200_000]

    def resolve(node, depth: int, path: frozenset):
        budget[0] -= 1
        if depth > 12 or budget[0] < 0:
            return None
        if isinstance(node, dict):
            ref = node.get("__ref")
            if isinstance(ref, str):
                target = state.get(ref)
                return resolve(target, depth + 1, path | {ref}) if isinstance(target, dict) and ref not in path else None
            return {k: resolve(v, depth + 1, path) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v, depth + 1, path) for v in node]
        return node

    root = state.get("ROOT_QUERY")
    return [resolve(root, 0, frozenset()), state] if isinstance(root, dict) else state


def _short(url: str) -> str:
    return (url or "").split("?")[0].split("://", 1)[-1][:60]


def read_frames(page, states: dict) -> None:
    """프레임마다 Apollo 상태의 곳들 → states[프레임 주소] = (곳들, 기록용 한 줄). 곳을 이미 읽은 프레임은 다시 읽지 않는다."""
    for frame in list(page.frames):
        url = frame.url or ""
        if not url.startswith("http") or states.get(url, ([], ""))[0]:
            continue
        try:
            text = frame.evaluate(STATE_JS) or ""
        except Exception:  # noqa: BLE001 — 닫히는 · 다시 그리는 프레임
            continue
        if not text:
            states[url] = ([], "상태 없음")
            continue
        if len(text) > STATE_LIMIT:
            states[url] = ([], f"상태가 너무 큼({len(text)}자)")
            continue
        try:
            data = json.loads(text)
        except ValueError:
            states[url] = ([], "상태를 읽지 못함")
            continue
        found = places_in(apollo_tree(data) if isinstance(data, dict) else data, limit=200)
        kinds = sorted({str(k).split(":")[0] for k in data} if isinstance(data, dict) else set())[:8]
        states[url] = (found, f"상태 {len(data)}개({', '.join(kinds)}) · 곳 {len(found)}")


def press_in_place_screen(page, word: str) -> int:
    """네이버 장소 화면(pcmap.place.naver.com 프레임)의 '출발' · '도착' — 글자가 정확히 같은 보이는 것이 하나일 때만 누른다(사람이 하는 길,
    담당자 2026-11-10 "검색하면 바로 뜨고 출발을 누르면 경로 탐색이 됩니다"). 누르면 네이버가 그 곳을 넣은 길찾기 주소로 바꾼다. 누른 수."""
    for frame in list(page.frames):
        if not _ENTRY.search(frame.url or ""):
            continue
        try:
            if frame.evaluate(CLICK_SHORTEST_JS, word) == 1:
                return 1
        except Exception:  # noqa: BLE001
            continue
    return 0


def look_up(page, url: str, query: str, role: str, wait: Callable[[float], None], log: Callable[[str], None] | None = None,
            prefer_id: str = "", strict: bool = False) -> tuple[Place | None, str, str]:
    """네이버 지도 화면 하나(검색 화면 · 장소 화면)를 열고 그 화면이 보여 주는 곳을 고른다 — (곳, 고른 까닭, 못 찾았으면 까닭).
    고르는 차례: 그 화면의 결과(검색 목록 · 장소 화면의 Apollo 상태, 검색 답) 중 네이버가 연 곳(주소의 /place/번호) · 이름이 같은 곳 · 비슷한 곳 ·
    주소가 맞는 곳 · 맨 위 결과(strict 면 이름이 맞을 때만). 주변 가게 · 광고 표시 같은 다른 답의 곳은 이름이 맞을 때만.
    장소 화면인데 좌표를 못 읽으면 그 화면의 [출발](출발지) · [도착](목적지)을 눌러 네이버가 여는 길찾기 주소에서 읽는다.
    네이버가 보안문자를 물으면 사람이 그 창에서 풀 때까지(CAPTCHA_POLLS) 기다린다 — 앱은 풀거나 피하지 않는다."""
    seen: list = []

    def keep(response) -> None:          # 알림 자리에서는 담아만 둔다 — 여기서 Playwright 를 부르지 않는다(21절)
        seen.append(response)

    page.on("response", keep)
    read = 0
    answers: list[Place] = []        # 그 검색어의 검색 답(allSearch · GraphQL …)
    nearby: list[Place] = []         # 지도 화면이 함께 받은 다른 답(주변 가게 · 광고 표시 …) — 이름이 맞을 때만 쓴다
    states: dict = {}
    paths: list[str] = []
    captcha = pressed = False
    word = "출발" if role == "출발지" else "도착"
    try:
        page.goto(url, wait_until="domcontentloaded")
        polls = 0
        while polls < (CAPTCHA_POLLS if captcha else LOOK_POLLS):
            polls += 1
            wait(POLL)
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
                paths.append(_short(response.url))
                bucket = answers if _search_answer(response.url) else nearby
                bucket += [p for p in places_in(data) if all((p.name, p.x, p.y) != (q.name, q.x, q.y) for q in bucket)]
                if not captcha and has_captcha(data):
                    captcha = True
                    try:
                        page.bring_to_front()
                    except Exception:  # noqa: BLE001
                        pass
                    if log is not None:
                        log(f"{CAPTCHA_NOTE} — 앱 브라우저의 네이버 지도 창에서 입력해 주세요(2분 기다립니다)")
            read_frames(page, states)
            chosen = _CHOSEN.search(page.url or "")
            entry = next((m.group(1) for m in (_ENTRY.search(u) for u in states) if m), "")
            want = prefer_id or (chosen.group(1) if chosen else "") or entry
            shown = [p for u, (found, _) in states.items() if "place.naver.com" in u for p in found] + answers
            others = nearby + [p for u, (found, _) in states.items() if "place.naver.com" not in u for p in found]
            if want and polls < CLICK_AFTER and not any(p.id == want for p in shown):
                continue                 # 네이버가 곳 하나를 열었다 — 그 곳의 좌표가 올 때까지 조금 더
            place, how = rank(query, shown, want, allow_first=not strict)
            if place is None:
                place, how = rank(query, others, want, allow_first=False)
            if place is not None:
                return place, how, ""
            if pressed:
                got = places_from_url(page.url)
                if got:
                    place = got[0] if role == "출발지" else got[-1]
                    place.id = place.id or want
                    return place, f"장소 화면의 [{word}] 로 연 길찾기", ""
            elif polls >= CLICK_AFTER and press_in_place_screen(page, word):
                pressed = True
    finally:
        page.remove_listener("response", keep)
    if captcha:
        return None, "", CAPTCHA_NOTE + " — 2분 안에 풀지 않아 그만두었습니다"
    frames = "; ".join(f"{_short(u)} {note}" for u, (_, note) in states.items()) or "프레임 없음"
    answered = f"받은 답 {len(paths)}개" + (f"({', '.join(dict.fromkeys(paths))[:160]})" if paths else "")
    return None, "", f"화면에서 곳을 읽지 못했습니다 — {frames[:400]} · {answered}" + (f" · [{word}] 누름" if pressed else "")


def search_place(page, query: str, wait: Callable[[float], None] | None = None,
                 known: dict | None = None, log: Callable[[str], None] | None = None,
                 role: str = "목적지") -> tuple[Place | None, str, list[str]]:
    """네이버 지도에서 곳 하나 — (곳, 못 찾았으면 까닭, 한 일). known 은 전에 찾은 곳(settings.travel_places).
    한 곳에 검색은 한 번 — 같은 곳을 검색어만 바꿔 다시 찾아도 같은 결과다(담당자 2026-11-10). 늘 쓰는 곳(FIXED_PLACES)은 장소 번호로 장소 화면을 연다."""
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
    if wait is None:
        return None, "검색 결과 없음", steps
    fixed = FIXED_PLACES.get(norm(query))
    if fixed:
        place, how, why = look_up(page, f"{BASE}/p/entry/place/{fixed[1]}", fixed[0], role, wait, log, prefer_id=fixed[1], strict=True)
        if place is not None:
            steps.append(f"'{query}' → 네이버 장소 {fixed[1]} ({place.name} · {how})")
            return place, "", steps
        steps.append(f"'{query}' → 네이버 장소 {fixed[1]}: {why}")
        if why.startswith(CAPTCHA_NOTE):
            return None, why, steps
    words = search_queries(query)[-1]          # 괄호 속 지역은 앞에('강원가명정보활용지원센터 (원주)' → '원주 강원가명정보활용지원센터')
    place, how, why = look_up(page, f"{BASE}/p/search/{quote(words, safe='')}", query, role, wait, log,
                              prefer_id=fixed[1] if fixed else "", strict=bool(fixed))
    if place is not None:
        steps.append(f"검색 '{words}' → {place.name} ({how})")
        return place, "", steps
    steps.append(f"검색 '{words}' → {why}")
    return None, why if why.startswith(CAPTCHA_NOTE) else "검색 결과 없음", steps


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
    places = []
    for role, query in (("출발지", origin), ("목적지", goal)):
        place, why, steps = search_place(page, query, wait, known, log, role)
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
    for _ in range(ROUTE_POLLS):        # 경로 목록이 뜰 때까지
        wait(POLL)
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
    screenshot_clear(page, out, wait)
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
            place, why, steps = search_place(page, query, wait, known, log, role)
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
        for _ in range(ROUTE_POLLS):    # 경로 목록이 뜰 때까지 — 뜨면 '거리우선' 을 골라 둔다
            wait(POLL)
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
    if screenshot_clear(page, out, wait):
        result.steps.append("지도를 가리는 세부 경로 창을 숨기고 찍음")
    result.image, result.ok = str(out), True
    if result.km is None:
        result.note = "화면에서 경로 km 를 읽지 못했습니다 — km 를 직접 적으세요"
    return result


KEEP_SHOTS = 2      # 같은 구간의 지도 그림은 최근 둘만(새로 찍으면 그 전 것 하나는 남겨 둔다 — 찍다 실패해도 앞 그림이 남게)


def shot_path(folder: Path, label: str, now: dt.datetime | None = None) -> Path:
    """찍을 지도 그림 — 출장 폴더가 아니라 앱 사용자 폴더(~/.claim-downloader/출장지도/<출장 폴더마다>/)에.
    담당자 2026-11-11 "네이버지도 최단거리 이미지가 생성되는데 왜이러나요? 이건 필요없습니다" — 출장증빙 PDF 에 넣을 그림일 뿐인데 출장 폴더에
    '네이버지도 최단거리_… _7.png' 처럼 찍을 때마다 쌓였다. 이름에 찍은 때를 붙여(미리 보기가 옛 그림을 다시 쓰지 않게) 같은 구간의 오래된 것은 지운다
    (앱이 자기 폴더에 만든 것만)."""
    from .. import settings
    key = hashlib.sha1(os.path.normcase(os.path.abspath(str(folder))).encode("utf-8")).hexdigest()[:12]
    base = settings.data_dir() / MAP_DIR / key
    stem = re.sub(r'[\\/:*?"<>|]+', " ", f"최단거리_{label}").strip("_ ")
    olds = sorted(glob.glob(os.path.join(glob.escape(str(base)), glob.escape(stem) + "_" + "[0-9]" * 8 + "-" + "[0-9]" * 6 + "*.png")))
    for old in olds[:max(0, len(olds) - (KEEP_SHOTS - 1))]:
        try:
            os.remove(old)
        except OSError:
            pass
    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    path = base / f"{stem}_{stamp}.png"
    n = 2
    while path.exists():
        path = base / f"{stem}_{stamp}_{n}.png"
        n += 1
    return path

