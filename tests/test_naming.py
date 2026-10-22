"""파일 이름 짓기와 저장 위치.

파일명은 기존 보관본과 같은 형식이어야 한다. 형식이 달라지면 담당자가 폴더에서
같은 건을 두 번 받은 것처럼 보거나, 플랫폼 업로드 때 이름을 다시 고쳐야 한다.
"""
from __future__ import annotations

import pytest

from claim_downloader import naming
from conftest import make_row


def test_readme_example():
    """기본은 비목 번호로 시작한다 (담당자 요청)."""
    code, name = naming.build_name(make_row(), {"owners": ["코웨이(주)"]})
    assert code == "09"
    assert name == "09_(261008) 2026년 사업단 정수기 임차료(9월)_코웨이(주)_(51,900).pdf"


def test_date_first_format():
    _, name = naming.build_name(make_row(), {"owners": ["코웨이(주)"]}, name_date_first=True)
    assert name == "(261008) 2026년 사업단 정수기 임차료(9월)_코웨이(주)_(51,900).pdf"


def test_unsorted_gets_00():
    _, name = naming.build_name(make_row(cont="특강 강사료"), {})
    assert name.startswith("00_(261008) ")


def test_two_or_more_owners():
    _, name = naming.build_name(make_row(), {"owners": ["홍길동", "김철수", "이영희"]})
    assert "_홍길동 등 3명_" in name


def test_forbidden_characters_become_spaces():
    _, name = naming.build_name(make_row(cont="03_회의비 (9/11) 지급"), {})
    assert "(9 11)" in name
    assert "/" not in name


def test_negative_amount_written_without_sign():
    _, name = naming.build_name(make_row(amt="-120000"), {})
    assert name.endswith("_(120,000).pdf")


def test_missing_date_keeps_placeholder():
    _, name = naming.build_name(make_row(expDt=""), {})
    assert name.startswith("09_(------) ")


def test_name_is_capped():
    _, name = naming.build_name(make_row(cont="09_" + "가" * 400), {})
    assert len(name) == naming.MAX_NAME + len(".pdf")


@pytest.mark.parametrize("cont, info, expected", [
    ("09_정수기", {}, "09"),                                         # ① 선행 0N_
    ("[교육·연구프로그램 개발·운영비] 특강 강사료", {}, "03"),          # ② […] 비목명
    ("특강 강사료", {"bimok": "실험실습장비및기자재구입운영비"}, "05"),   # ③ 상세 표 '비목' 열
    ("특강 강사료", {"full": "비목 금액\n성과 활용·확산 지원비 51,900\n합계"}, "08"),  # ④ 금액 줄
    ("특강 강사료", {}, "00"),                                       # 못 정함 → 미분류
])
def test_bimok_order(cont, info, expected):
    code, _ = naming.build_name(make_row(cont=cont), info)
    assert code == expected


def test_doctext_with_two_bimok_names_is_not_guessed():
    """금액 줄이 없고 비목명이 둘 이상이면 추측하지 않는다."""
    full = "인건비 안내\n장학금 안내"
    assert naming.code_from_doctext(full, "999") == ""


def test_alt_names():
    assert naming.code_of("지자체연계협업비용") == "06"
    assert naming.code_of("기타운영경비") == "09"


def test_destination_never_overwrites(tmp_path):
    folder = tmp_path / "09. 그 밖의사업운영경비"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(b"1")
    (folder / "a_2.pdf").write_bytes(b"2")
    assert naming.destination(tmp_path, "09", "a.pdf") == folder / "a_3.pdf"


def test_destination_is_directly_under_bimok_folder(tmp_path):
    dest = naming.destination(tmp_path, "02", "x.pdf")
    assert dest.parent == tmp_path / "02. 장학금"
    assert naming.destination(tmp_path, "00", "x.pdf").parent.name == naming.UNSORTED


def test_upload_folder_is_refused(tmp_path):
    with pytest.raises(RuntimeError):
        naming.ensure_not_upload(tmp_path / "02. 장학금" / "업로드" / "x.pdf")


BUDGET = [["A10110002", "장학금"], ["A10110012", "연구시설/장비비"]]       # 대응자금 예산 탭(2026-10-21 담당자 그림)의 차례


@pytest.mark.parametrize("cont, info, expected", [
    ("02_연구장비 구입", {"bimok": "연구시설/장비비"}, "02"),           # 적요 앞 02_(사업비 장학금 번호)는 보지 않고 상세 표 '비목' 열
    ("근로장학금", {"bimok": "장학금"}, "01"),
    ("근로장학금", {"bimok": "A10110012"}, "02"),                      # 비목코드로 적혀 있어도
    ("[연구시설·장비비] 노트북", {}, "02"),                            # 적요 안 […]
    ("노트북", {"full": "비목 금액\n연구시설/장비비 1,234,000\n장학금 0"}, "02"),   # 금액 줄
    ("노트북", {"full": "장학금 안내\n연구시설/장비비 안내"}, "00"),      # 둘 다 나오면 추측하지 않는다
    ("노트북", {"bimok": "인건비"}, "00"),                             # 예산에 없는 비목 — 사업비 번호(01)로 보내지 않는다
])
def test_matching_fund_bimok_follows_budget_tab_order(cont, info, expected):
    code, name = naming.build_name(make_row(cont=cont, amt="1234000", budget=BUDGET), info)
    assert code == expected and name.startswith(expected + "_(")
    assert ") 02_" not in name                                               # 적요 앞 번호는 떼어 낸다


def test_matching_fund_with_one_budget_line_needs_no_evidence():
    assert naming.budget_code([["A10110002", "장학금"]], "아무 적요", {}, 0) == "01"


def test_matching_fund_folders(tmp_path):
    assert naming.folder_name("02", BUDGET) == "02. 연구시설장비비"
    assert naming.folder_name("00", BUDGET) == naming.folder_name("07", BUDGET) == naming.UNSORTED
    assert naming.destination(tmp_path, "01", "x.pdf", BUDGET).parent == tmp_path / "01. 장학금"
    mine = tmp_path / "02. 연구시설 · 장비비"                          # 담당자가 먼저 만든 같은 번호 · 같은 이름 폴더는 그대로 쓴다
    mine.mkdir()
    (tmp_path / "02. 인건비").mkdir()
    assert naming.destination(tmp_path, "02", "x.pdf", BUDGET).parent == mine
    assert naming.own_budget("(202409710003)_2026년도 대응자금_254,907,000") and naming.own_budget("", "사업[대응 자금-교내]")
    assert not naming.own_budget("(202408470003)_2026년도 사업비", "가짜사업_이월금")
    # 연구지원비 과제도 비목이 사업비와 달라 예산 탭 차례로(2026-10-22 — 사업비 '01. 인건비' 로 다 들어갔다)
    assert naming.own_budget("(202508100001)_2025년 연구지원비(책임자)_20,000,000")
    assert naming.budget_code([["A1", "인건비"], ["A2", "연구시설/장비비"], ["A3", "연구활동비"]], "",
                              {"bimok": "연구활동비"}, 404520) == "03"
