"""창 자리(ui/placement.py) — 담당자 2026-10-21: 새로 연 창이 데스크톱 밖으로 삐져나가 옮기기 어려웠다. 작업 영역(작업 표시줄 뺀 곳) 안에
창틀까지 다 들어가는지 흔한 화면들로 본다."""
from __future__ import annotations

import pytest

from claim_downloader.ui import placement

WANT, MIN = (1320, 860), (1024, 640)
FRAME = placement.GUESS_FRAME


def outer(spot, frame=FRAME):
    left, top, right, bottom = frame
    return spot.x, spot.y, spot.width + left + right, spot.height + top + bottom


@pytest.mark.parametrize("area", [
    (0, 0, 1920, 1032),          # 1920×1080 100% · 작업 표시줄 48
    (0, 0, 1536, 816),           # 1920×1080 125%
    (0, 0, 1280, 672),           # 1920×1080 150% (논리 1280×720)
    (0, 0, 1366, 728),           # 1366×768 노트북
    (0, 0, 1440, 852),           # 맥북 크기
    (1920, -200, 1080, 1872),    # 오른쪽에 세운 둘째 화면(좌표가 음수)
    (-1280, 0, 1280, 984),       # 왼쪽 둘째 화면
    (0, 40, 1920, 1040),         # 작업 표시줄이 위에
])
def test_window_fits_inside_the_work_area(area):
    spot = placement.place(area, WANT, MIN)
    assert placement.inside(area, outer(spot)), (area, spot)
    assert not spot.maximize and (spot.min_width, spot.min_height) == MIN
    assert spot.width >= MIN[0] and spot.height >= MIN[1]


def test_big_screen_keeps_the_usual_size_centered():
    spot = placement.place((0, 0, 1920, 1032), WANT, MIN)
    assert (spot.width, spot.height) == WANT
    assert spot.x == (1920 - 1322) // 2 and spot.y == (1032 - 892) // 2


def test_small_screen_shrinks_to_fit_with_a_margin_when_possible():
    spot = placement.place((0, 0, 1366, 728), WANT, MIN)
    assert spot.width == 1366 - 2 - 2 * placement.MARGIN and spot.height == 728 - 32 - 2 * placement.MARGIN
    spot = placement.place((0, 0, 1280, 672), WANT, MIN)       # 틈을 두면 최소보다 작아진다 — 틈을 줄여 최소 크기로
    assert spot.height == 640 and spot.y == 0 and placement.inside((0, 0, 1280, 672), outer(spot))


def test_screen_smaller_than_the_minimum_lowers_it_and_maximizes():
    area = (0, 0, 1093, 574)                                   # 1366×768 125% — 최소 높이 640 이 안 들어간다
    spot = placement.place(area, WANT, MIN)
    assert spot.maximize and spot.min_height == 574 - 32 and spot.min_width == 1024
    assert placement.inside(area, outer(spot))


def test_real_frame_after_show_is_used():
    frame = (8, 45, 8, 8)                                      # 150% 배율의 두꺼운 제목 줄
    area = (0, 0, 1280, 672)
    spot = placement.place(area, (1320, 860), MIN, frame)
    assert placement.inside(area, outer(spot, frame))
    assert placement.inside((0, 0, 10, 10), (0, 0, 10, 10)) and not placement.inside((0, 0, 10, 10), (0, -1, 10, 10))
