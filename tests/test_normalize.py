"""정규화 함수 테스트. 여기가 틀리면 교차 대사가 통째로 오탐이 된다."""
import datetime as dt

import pytest

from expense_review import normalize as nz


@pytest.mark.parametrize("raw, expected", [
    ("592201-01-565992", "59220101565992"),
    ("59220101565992", "59220101565992"),
    ("110-493-878372", "110493878372"),
])
def test_account_normalization_makes_notations_equal(raw, expected):
    assert nz.digits_only(raw) == expected


def test_bank_aliases_collapse():
    assert nz.bank_alias("국민") == nz.bank_alias("국민은행")
    assert nz.bank_alias("카카오") == "카카오뱅크"
    assert nz.bank_alias("토스뱅크") == "토스뱅크"


@pytest.mark.parametrize("raw, expected", [
    ("2026.06.29.", dt.date(2026, 6, 29)),
    ("26/03/9", dt.date(2026, 3, 9)),          # 근무상황부 손글씨 표기
    ("2026년 6월 29일", dt.date(2026, 6, 29)),
    ("2026.  03.   31.", dt.date(2026, 3, 31)),
])
def test_date_parsing_covers_form_notations(raw, expected):
    assert nz.parse_date(raw) == expected


def test_datetime_parsing_for_tollgate_receipt():
    assert nz.parse_datetime("2026년07월03일 13시20분") == dt.datetime(2026, 7, 3, 13, 20)


@pytest.mark.parametrize("start, end, expected", [
    ("09:00", "14:00", 5.0),
    ("13:00", "18:00", 5.0),
    ("09:00", "12:00", 3.0),
])
def test_hours_between(start, end, expected):
    assert nz.hours_between(start, end) == expected


@pytest.mark.parametrize("amount, expected", [
    (240000, "금이십사만원정"),
    (300000, "금삼십만원정"),
    (8500, "금팔천오백원정"),
    (10000, "금일만원정"),
])
def test_hangul_amount(amount, expected):
    assert nz.hangul_amount(amount) == expected


def test_money_strips_units_and_separators():
    assert nz.money("1,200원") == 1200
    assert nz.money("240,000원 (금이십사만원정)") == 240000
    assert nz.money("없음") is None


def test_region_of_drops_province_and_suffix():
    assert nz.region_of("강원평창군대관령면대관령로100,1층") == "평창"
    assert nz.region_of("강원특별자치도 춘천시 효자동") == "춘천"


def test_regions_of_handles_suffixless_destinations():
    # 출장지는 '강원 평창, 강릉' 처럼 시/군 접미사 없이 적힌다.
    assert {"평창", "강릉"} <= nz.regions_of("강원 평창, 강릉")
    assert nz.region_of("강원평창군대관령면") in nz.regions_of("강원 평창, 강릉")
