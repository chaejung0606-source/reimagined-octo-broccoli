"""정규화 함수 — docs/03-field-dictionary.md §1 의 예시를 그대로 검증한다."""
from datetime import date, datetime

import pytest

from app import normalize as nz


@pytest.mark.parametrize("raw, expected", [
    ("592201-01-565992", "59220101565992"),
    ("110-493-878372", "110493878372"),
    ("", None),
    (None, None),
])
def test_digits_only(raw, expected):
    assert nz.digits_only(raw) == expected


def test_strip_spaces_handles_full_width():
    assert nz.strip_spaces("권 석 재") == "권석재"
    assert nz.strip_spaces("권　석 재") == "권석재"


@pytest.mark.parametrize("raw, expected", [
    ("국민", "국민은행"),
    ("카카오", "카카오뱅크"),
    ("토스", "토스뱅크"),
    ("신한은행", "신한은행"),
    ("(주)카카오뱅크", "카카오뱅크"),
])
def test_bank_alias(raw, expected):
    assert nz.bank_alias(raw) == expected


def test_money():
    assert nz.money("1,200원") == 1200
    assert nz.money("300,000") == 300000
    assert nz.money(None) is None


@pytest.mark.parametrize("raw, expected", [
    ("2026.06.29.", date(2026, 6, 29)),
    ("2026-06-29", date(2026, 6, 29)),
    ("2026년 6월 29일", date(2026, 6, 29)),
    ("2026. 03. 31.", date(2026, 3, 31)),
    ("26/03/9", date(2026, 3, 9)),          # 연 2자리 + 월일 비제로패딩
])
def test_parse_date(raw, expected):
    assert nz.parse_date(raw) == expected


def test_parse_date_needs_year_context():
    assert nz.parse_date("7/3") is None
    assert nz.parse_date("7/3", default_year=2026) == date(2026, 7, 3)


def test_parse_datetime():
    assert nz.parse_datetime("2026년07월03일 13시20분") == datetime(2026, 7, 3, 13, 20)
    assert nz.parse_datetime("2026.07.03 13:20") == datetime(2026, 7, 3, 13, 20)


@pytest.mark.parametrize("raw, expected", [("5", 5.0), ("5시간", 5.0), ("5.0", 5.0),
                                           ("4시간 30분", 4.5)])
def test_parse_hours(raw, expected):
    assert nz.parse_hours(raw) == expected


def test_hangul_amount_round_trip():
    assert nz.hangul_amount(240000) == "금이십사만원정"
    assert nz.parse_hangul_amount("금이십사만원정") == 240000
    for amount in (12000, 300000, 1015000, 240000):
        assert nz.parse_hangul_amount(nz.hangul_amount(amount)) == amount


def test_region_of():
    assert nz.region_of("강원평창군대관령면대관령로100") == "강원 평창군"
    assert nz.region_of("강원특별자치도 강릉시 경강로 2024") == "강원 강릉시"


def test_regions_of_matches_without_suffix():
    """출장지는 `강원 평창, 강릉` 처럼 시/군 접미사 없이 적힌다.

    영수증 주소(`강원 평창군 …`)와 맞추려면 접미사를 떼고 비교해야 한다.
    R-TRV-013 이 여기서 오탐을 내면 안 된다.
    """
    destination = nz.regions_of("강원 평창, 강릉")
    assert nz.region_of("강원평창군대관령면대관령로100") in destination
    assert nz.region_of("강원특별자치도 강릉시 경강로 2024") in destination
    assert nz.region_of("강원특별자치도 춘천시 중앙로 1") not in destination


def test_similarity():
    assert nz.similarity("AI 융합 학과", "AI융합학과") == 1.0
    assert nz.similarity("클라우드", "블록체인") < 0.5
