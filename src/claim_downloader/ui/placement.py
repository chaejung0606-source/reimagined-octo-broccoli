"""창을 화면(작업 표시줄을 뺀 작업 영역) 안에 놓는 셈 — Qt 없이 돈다(테스트가 PySide6 없이 본다).

담당자 2026-10-21: 앱을 새로 열면 창이 데스크톱 밖으로 삐져나가 옮기기 어렵다. 창은 늘 1320×860 으로 열렸고 자리는 윈도우가 정했다 —
1366×768 노트북이나 1920×1080 150% 배율(논리 1280×720)에서는 그 크기가 작업 영역보다 커서 아래(때로는 제목 줄까지)가 화면 밖으로 나갔다.
이제 창을 연 화면의 작업 영역에 맞춰 줄이고 가운데에 둔다. 최소 크기(1024×640)도 들어가지 않는 화면이면 최소 크기를 낮추고 최대화한다.
"""
from __future__ import annotations

from dataclasses import dataclass

# 창을 보이기 전에는 창틀(제목 줄 · 테두리) 두께를 모른다 — 윈도우 100% 배율 값으로 짐작하고, 보인 뒤 실제 값으로 다시 맞춘다
GUESS_FRAME = (1, 31, 1, 1)
MARGIN = 24          # 작업 영역 가장자리와 띄울 틈 — 자리가 모자라면 줄인다


@dataclass(frozen=True)
class Placement:
    x: int               # 창틀 바깥 왼쪽 위 (QWidget.move 좌표)
    y: int
    width: int           # 창 안쪽 크기 (QWidget.resize)
    height: int
    min_width: int       # 이 화면에 들어가는 최소 크기
    min_height: int
    maximize: bool       # 최소 크기도 들어가지 않으면 최대화


def place(area: tuple[int, int, int, int], want: tuple[int, int], minimum: tuple[int, int],
          frame: tuple[int, int, int, int] = GUESS_FRAME, margin: int = MARGIN) -> Placement:
    """area = 작업 영역 (x, y, 너비, 높이), want = 바라는 안쪽 크기, minimum = 최소 안쪽 크기, frame = 창틀 (왼, 위, 오른, 아래)."""
    ax, ay, aw, ah = area
    left, top, right, bottom = frame
    room_w = max(1, aw - left - right)      # 창틀 안쪽에 쓸 수 있는 가장 큰 크기
    room_h = max(1, ah - top - bottom)
    min_w, min_h = min(minimum[0], room_w), min(minimum[1], room_h)
    width = _fit(want[0], min_w, room_w, margin)
    height = _fit(want[1], min_h, room_h, margin)
    x = ax + max(0, (aw - (width + left + right)) // 2)
    y = ay + max(0, (ah - (height + top + bottom)) // 2)
    return Placement(x, y, width, height, min_w, min_h, maximize=(min_w, min_h) != tuple(minimum))


def _fit(want: int, least: int, room: int, margin: int) -> int:
    """바라는 크기를 자리에 맞춘다 — 둘레에 틈을 두되, 틈 때문에 최소보다 작아지면 틈을 줄인다."""
    return max(least, min(want, room - 2 * margin, room))


def inside(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    """inner (x, y, 너비, 높이) 가 outer 안에 다 들어가는지."""
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh
