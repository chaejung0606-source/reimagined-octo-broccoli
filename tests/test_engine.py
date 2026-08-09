"""규칙 엔진 회귀 테스트.

docs/01-sample-analysis.md 에 기록된 실제 사례를 그대로 재현한다. 두 방향을 모두 본다.

- **잡아야 할 것을 잡는가** — 총 이동경로 공란, 기간 이탈 영수증, 블록 누락 …
- **정상 건에서 조용한가** — 권석재·강옥일은 세 서류가 일치한다. 여기서 🔴 가 뜨면
  오탐이고, 오탐이 나면 담당자가 앱을 못 쓴다.
"""
from app.engine import review_case
from app.models import Status

from . import fixtures as fx


def statuses(result):
    """규칙 ID → 판정 목록."""
    out = {}
    for finding in result.findings:
        out.setdefault(finding.rule_id, []).append(finding.status)
    return out


def worst(result, rule_id):
    found = statuses(result).get(rule_id, [])
    for status in (Status.ERROR, Status.WARN, Status.REVIEW,
                   Status.UNSUPPORTED, Status.SKIPPED, Status.PASS):
        if status in found:
            return status
    return None


# ======================================================= 정상 건 — 무오탐 검증

def test_ta_case_is_clean():
    """권석재: 15h × 20,000 = 300,000 이 세 서류에서 일치한다.

    docs/02 §3-2 가 회귀 테스트 케이스로 지목한 건이다. 🔴/🟡/🔵 가 하나도 없어야 한다.
    """
    result = review_case(fx.ta_case())
    assert result.count(Status.ERROR) == 0
    assert result.count(Status.WARN) == 0
    assert result.count(Status.REVIEW) == 0
    for rule_id in ("R-SCH-001", "R-SCH-002", "R-SCH-003",
                    "R-SCH-008", "R-SCH-009", "R-SCH-013"):
        assert worst(result, rule_id) is Status.PASS, rule_id


def test_supporters_case_has_no_errors():
    """강옥일: 25h / 300,000원 — 청구서·보고서·근무일지·지급내역이 모두 맞는다."""
    result = review_case(fx.supporters_case())
    assert result.count(Status.ERROR) == 0
    for rule_id in ("R-SCH-002", "R-SCH-008", "R-SCH-009", "R-SCH-010",
                    "R-SCH-011", "R-SCH-012"):
        assert worst(result, rule_id) is Status.PASS, rule_id


def test_account_number_formatting_is_not_an_error():
    """신청서 `59220101565992` vs 지급내역 `592201-01-565992`.

    표기만 다르고 같은 계좌다. R-CMN-005 가 여기서 울리면 오탐이다.
    """
    result = review_case(fx.innovation_case())
    assert worst(result, "R-CMN-005") is Status.PASS


# ================================================== 혁신인재 — 잡아야 할 것들

def test_innovation_activity_dates_mismatch():
    """보고서 대표성과 5/4·5/18 vs 근무상황부 5/6·5/13·5/20 (R-INN-012)."""
    result = review_case(fx.innovation_case())
    assert worst(result, "R-INN-012") is Status.WARN
    message = next(f.message for f in result.findings if f.rule_id == "R-INN-012")
    assert "2026-05-04" in message and "2026-05-18" in message


def test_innovation_student_id_length():
    """팀원 최용빈 학번 8자리 (R-INN-014)."""
    result = review_case(fx.innovation_case())
    assert worst(result, "R-INN-014") is Status.WARN
    assert any("최용빈" in f.message for f in result.findings if f.rule_id == "R-INN-014")


def test_innovation_typo_detection():
    """본문 오탈자 `5원 4일` (R-INN-020)."""
    result = review_case(fx.innovation_case())
    assert worst(result, "R-INN-020") is Status.WARN
    assert any("5원 4일" in f.message for f in result.findings if f.rule_id == "R-INN-020")


def test_innovation_hangul_amount_matches():
    """240,000원 ↔ 금이십사만원정 (R-INN-002)."""
    result = review_case(fx.innovation_case())
    assert worst(result, "R-INN-002") is Status.PASS


# ==================================================== 출장비 — 잡아야 할 것들

def test_missing_route_total_is_an_error_with_the_answer():
    """이성재: 206/206 인데 총 이동경로 칸이 공란 (R-TRV-006).

    '공란' 은 '못 읽음' 과 다르다. 칸을 찾았고 비어 있으므로 🔴 여야 하고,
    조치 문구에는 계산된 정답(412km)이 들어 있어야 한다.
    """
    result = review_case(fx.travel_lee_sj_case())
    assert worst(result, "R-TRV-006") is Status.ERROR
    finding = next(f for f in result.findings if f.rule_id == "R-TRV-006")
    assert "412" in finding.fix


def test_transport_amount_matches_after_period_filter():
    """이성재: 하이패스 8건 33,900원 중 출장기간 내 3건 8,500원 = 기재액.

    기간 필터를 빼고 단순 합산하면 여기서 오탐이 난다 (docs/02 §5-2).
    """
    result = review_case(fx.travel_lee_sj_case())
    assert worst(result, "R-TRV-009") is Status.PASS


def test_receipts_far_outside_the_period_are_only_a_warning():
    """이성재의 6/20·6/24·7/5 영수증은 다른 건의 것이다 → 🟡 (반려 사유가 아니다)."""
    result = review_case(fx.travel_lee_sj_case())
    assert worst(result, "R-TRV-011") is Status.WARN


def test_receipt_just_past_the_period_end_is_an_error():
    """이동재: 출장 종료 7/3 12:00, 귀로 통행료 7/3 13:20 → 기간 기재가 틀린 것 (R-TRV-011)."""
    result = review_case(fx.travel_lee_dj_case())
    assert worst(result, "R-TRV-011") is Status.ERROR
    finding = next(f for f in result.findings
                   if f.rule_id == "R-TRV-011" and f.status is Status.ERROR)
    assert "13:20" in finding.message


def test_missing_stay_evidence_day():
    """이동재: 출장 7/2~7/3 인데 체류 증빙은 7/2 만 (R-TRV-004)."""
    result = review_case(fx.travel_lee_dj_case())
    assert worst(result, "R-TRV-004") is Status.ERROR
    finding = next(f for f in result.findings if f.rule_id == "R-TRV-004")
    assert "2026-07-03" in finding.message


def test_missing_evidence_blocks():
    """황승재: 교통비·이동경로 블록이 서식에 아예 없다 (R-TRV-002/003)."""
    result = review_case(fx.travel_hwang_case())
    assert worst(result, "R-TRV-002") is Status.ERROR
    assert worst(result, "R-TRV-003") is Status.ERROR
    assert worst(result, "R-CMN-001") is Status.ERROR


def test_multiple_trips_in_one_request():
    """김동현: 신청서 한 장에 출장 2건 (R-TRV-017)."""
    result = review_case(fx.travel_kim_dh_case())
    assert worst(result, "R-TRV-017") is Status.WARN


def test_normal_travel_case_has_no_errors():
    """김동현의 이동경로는 211/154/365 로 맞는다 — 🔴 가 없어야 한다."""
    result = review_case(fx.travel_kim_dh_case())
    assert result.count(Status.ERROR) == 0
    assert worst(result, "R-TRV-006") is Status.PASS


# ============================================ 판정 보류(🔵)와 미검사(⚪) 처리

def test_ocr_dependent_checks_are_reported_not_silently_passed():
    """서명·신분증 판독은 4단계 몫이다. 조용히 통과시키지 않고 ⚪ 로 남겨야 한다."""
    result = review_case(fx.ta_case())
    assert worst(result, "R-CMN-010") is Status.UNSUPPORTED
    assert worst(result, "R-CMN-014") is Status.UNSUPPORTED


def test_l3_rules_without_settings_are_skipped_with_a_reason():
    result = review_case(fx.ta_case())
    finding = next(f for f in result.findings if f.rule_id == "R-SCH-019")
    assert finding.status is Status.SKIPPED
    assert "규정값" in finding.reason


def test_l3_rules_activate_once_settings_are_supplied():
    result = review_case(fx.ta_case(), overrides={"max_hours_per_month": 60})
    assert worst(result, "R-SCH-019") is Status.PASS

    tight = review_case(fx.ta_case(), overrides={"max_hours_per_month": 10})
    assert worst(tight, "R-SCH-019") is Status.WARN


def test_rules_scoped_to_the_other_subtype_are_not_evaluated():
    """TA 에는 근무일지·청구서가 없다. 없는 서류를 찾아 🔵 를 쌓으면 안 된다."""
    result = review_case(fx.ta_case())
    assert "R-SCH-006" not in statuses(result)
    assert "R-SCH-010" not in statuses(result)


def test_travel_case_skips_document_rules_that_do_not_apply():
    """출장비 서류에는 통장 사본·재학증명서가 없다."""
    result = review_case(fx.travel_kim_dh_case())
    for rule_id in ("R-CMN-013", "R-CMN-015", "R-CMN-016", "R-CMN-019"):
        assert rule_id not in statuses(result), rule_id


# ================================================================ 개인정보

def test_rrn_is_masked_in_output():
    """docs/04 §6 — 결과 리포트에 주민등록번호를 그대로 싣지 않는다."""
    result = review_case(fx.ta_case(), mask_level="basic")
    blob = " ".join(f.message + f.fix + " ".join(f.evidence) for f in result.findings)
    assert "010203-3456789" not in blob
    assert "0102033456789" not in blob


def test_account_number_is_not_mistaken_for_an_rrn():
    """14자리 계좌 `59220101565992` 에서 13자리를 떼어 주민번호로 읽으면 안 된다."""
    result = review_case(fx.innovation_case())
    assert worst(result, "R-CMN-008") is not Status.ERROR
