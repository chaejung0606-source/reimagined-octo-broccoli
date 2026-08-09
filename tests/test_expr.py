"""규칙 표현식 평가기 — 샌드박스 경계와 `computed` 자동 산출."""
from datetime import date, datetime

import pytest

from app import expr
from app.models import MISSING, Namespace, Period, build_namespace


def scope(**values):
    return build_namespace(values).as_dict()


# ------------------------------------------------------------------ 샌드박스

@pytest.mark.parametrize("source", [
    '__import__("os").system("echo pwned")',
    "open('/etc/passwd').read()",
    "a.__class__.__mro__",
    "(lambda: 1)()",
    "[].__class__",
])
def test_sandbox_rejects_dangerous_expressions(source):
    with pytest.raises(expr.ExprError):
        expr.evaluate(source, {"a": Namespace({})})


def test_unknown_function_is_rejected():
    with pytest.raises(expr.ExprError):
        expr.evaluate("eval('1')", {})


# ------------------------------------------------------------------ 전처리

def test_pluck_syntax():
    assert expr.preprocess("sum(worklog.rows[].hours)") == 'sum(pluck(worklog.rows, "hours"))'


def test_infix_helpers():
    assert expr.evaluate("normalize(a) contains normalize(b)",
                         {"a": "데이터보안활용융합진로설계 /TA", "b": "데이터보안활용융합진로설계"})
    inner = Period(date(2026, 3, 3), date(2026, 3, 31))
    outer = Period(date(2026, 3, 2), date(2026, 6, 19))
    assert expr.evaluate("a within b", {"a": inner, "b": outer})
    assert not expr.evaluate("b within a", {"a": inner, "b": outer})


def test_lowercase_literals():
    assert expr.evaluate("x == true", {"x": True})
    assert expr.evaluate("x != null", {"x": 1})


# -------------------------------------------------------------- 값 비교 규칙

def test_blank_never_passes_a_comparison():
    """공란(None)은 '값이 다르다' 로 판정되어야 한다 — 총 이동경로 공란이 그 경우다."""
    values = scope(**{"trip_evidence.dist_total": None,
                      "trip_evidence.dist_out": 206.0,
                      "trip_evidence.dist_back": 206.0})
    source = "trip_evidence.dist_total == trip_evidence.dist_out + trip_evidence.dist_back"
    assert expr.evaluate(source, values) is False
    assert expr.compute(source, values) == 412.0


def test_missing_value_raises_so_engine_can_downgrade():
    with pytest.raises(expr.MissingValueError):
        expr.evaluate("a.b == 1", {"a": Namespace({})})


def test_numbers_and_spacing_are_compared_leniently():
    """표 추출은 `15` 를 `15.0` 으로, `권석재` 를 `권 석 재` 로 뱉는다."""
    assert expr.evaluate("a == b", {"a": 15, "b": 15.0})
    assert expr.evaluate("a == b", {"a": "권 석 재", "b": "권석재"})


def test_date_and_datetime_compare_by_date():
    """근로기간이 날짜, 근로일자도 날짜 — 한쪽만 00:00 이 붙어 종료일이 밀리면 안 된다."""
    values = {"start": datetime(2026, 3, 3, 0, 0), "end": datetime(2026, 3, 31, 0, 0),
              "day": date(2026, 3, 31)}
    assert expr.evaluate("start <= day <= end", values)


def test_period_contains_datetime():
    period = Period(datetime(2026, 7, 2, 18, 0), datetime(2026, 7, 3, 12, 0))
    assert expr.evaluate("t in p", {"t": datetime(2026, 7, 2, 19, 0), "p": period})
    assert not expr.evaluate("t in p", {"t": datetime(2026, 7, 3, 13, 20), "p": period})


# ------------------------------------------------------------ computed 선택

@pytest.mark.parametrize("source, expected", [
    # 계산된 쪽이 오른쪽
    ("a == b + c", "b + c"),
    # 계산된 쪽이 왼쪽
    ("sum(pluck(rows, 'hours')) == total", "sum(pluck(rows, 'hours'))"),
    ("unit * hours == amount", "unit * hours"),
    ("len(trips) == 1", "len(trips)"),
])
def test_computed_picks_the_derived_side(source, expected):
    assert expr.computed_source(source) == expected


def test_computed_is_none_when_both_sides_are_plain_fields():
    assert expr.computed_source("claim_form.amount == roster.amount") is None


def test_period_filter_before_summing():
    """R-TRV-009 의 핵심 — 기간 필터 없이 합산하면 오탐이 난다."""
    period = Period(datetime(2026, 6, 29, 8, 0), datetime(2026, 7, 1, 18, 0))
    receipts = [
        Namespace({"amount": 2500, "datetime": datetime(2026, 6, 29, 8, 12)}),
        Namespace({"amount": 3400, "datetime": datetime(2026, 6, 29, 9, 40)}),
        Namespace({"amount": 2600, "datetime": datetime(2026, 7, 1, 17, 5)}),
        Namespace({"amount": 25400, "datetime": datetime(2026, 6, 20, 8, 0)}),
    ]
    values = {"trip_request": Namespace({"period": period}),
              "transport_receipts": receipts,
              "trip_evidence": Namespace({"transport_amount": 8500})}
    source = ("trip_evidence.transport_amount == "
              "sum(r.amount for r in transport_receipts if r.datetime in trip_request.period)")
    assert expr.evaluate(source, values) is True
    assert expr.compute(source, values) == 8500


def test_namespace_data_wins_over_methods():
    """`receipt.items` 는 데이터여야 한다. Namespace.items 메서드가 이기면 규칙이 깨진다."""
    receipt = Namespace({"items": [Namespace({"amount": 100})], "keys": "값", "get": 1})
    assert expr.evaluate("len(receipt.items) == 1", {"receipt": receipt})
    assert receipt.keys == "값"
    assert receipt.get == 1
    assert receipt.없는키 is MISSING
