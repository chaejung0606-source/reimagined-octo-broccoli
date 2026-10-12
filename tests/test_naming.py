"""파일 이름 짓기와 저장 위치.

파일명은 기존 보관본과 같은 형식이어야 한다. 형식이 달라지면 담당자가 폴더에서
같은 건을 두 번 받은 것처럼 보거나, 플랫폼 업로드 때 이름을 다시 고쳐야 한다.
"""
from __future__ import annotations

import pytest

from claim_downloader import naming
from conftest import make_row


def test_readme_example():
    code, name = naming.build_name(make_row(), {"owners": ["코웨이(주)"]})
    assert code == "09"
    assert name == "(261008) 2026년 사업단 정수기 임차료(9월)_코웨이(주)_(51,900).pdf"


def test_old_macro_format_puts_code_first():
    _, name = naming.build_name(make_row(), {"owners": ["코웨이(주)"]}, name_date_first=False)
    assert name.startswith("09_(261008) ")


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
    assert name.startswith("(------) ")


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
