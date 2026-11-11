"""증빙의 학번 · 사번 — ERP 에서 사람을 번호로 먼저 찾게(담당자 2026-11-11 "증빙자료에 사번이나 학번이 있으면 그 번호로 먼저 조회를 하고 없으면 이름으로").

이름 · 번호는 모두 가짜다(10절).
"""
from __future__ import annotations

from claim_downloader.claims import idnums


def test_labeled_and_student_like_numbers():
    text = "성명 가나다  학번 : 202612345\n사번(123456) 연락처 010-1234-5678\n학번/사번 2026 00001 · 직번:100001"
    assert idnums.labeled(text) == ["202612345", "123456", "100001"]        # 띄어 쓴 번호 · 전화는 아님
    assert idnums.student_like("ID 202600009 날짜 20261019 계좌 110-202600001 금액 202,600,001") == ["202600009"]
    assert idnums.clean("학번 2024-00011") == "202400011" and idnums.clean("12") == "" and idnums.clean("1" * 14) == ""


def test_ranked_puts_labeled_numbers_first_then_the_most_frequent():
    texts = ["다른 학생 202600002 202600002 202600002", "학번: 202600009", "202600007"]
    assert idnums.ranked(texts) == ["202600009", "202600002", "202600007"]


def test_split_name_takes_the_number_out_of_the_name_cell():
    assert idnums.split_name("가나다(202612345)") == ("가나다", "202612345")
    assert idnums.split_name("202612345 가나다") == ("가나다", "202612345")
    assert idnums.split_name("가나다 학번: 202612345") == ("가나다", "202612345")
    assert idnums.split_name("가나다 외 3명") == ("가나다 외 3명", "") and idnums.split_name("") == ("", "")


def test_pairs_on_one_line_alternating_lines_and_the_next_line():
    names = ["가나다", "라마바", "사아자"]
    sheet = ("연번 소속 성명 학번 서명\n"
             "1 컴퓨터공학과 가나다 202600001 (서명)\n"
             "2 컴퓨터공학과 라 마 바 202600002\n"           # 서명부 PDF 는 이름 글자를 띄우기도 한다
             "가나다 202600001 라마바 202600002\n"          # 두 칸짜리 서명부 — 이름 · 번호가 번갈아
             "사아자\n202600003\n"                          # 표 칸이 줄마다 나뉘어 읽힌 것
             "회의일 2026.10.12 금액 45,000 연락처 010-1234-5678 가나다")   # 날짜 · 금액 · 전화는 번호가 아니다
    pairs = idnums.pairs_in_text(sheet, names)
    assert ("가나다", "202600001") in pairs and ("라마바", "202600002") in pairs and ("사아자", "202600003") in pairs
    assert all(no.startswith("2026000") for _n, no in pairs)
    assert idnums.pairs_in_text("202600005 가나다", names) == [("가나다", "202600005")]      # 번호가 앞에 와도
    assert idnums.pairs_in_text("가나다 라마바 202600001", names) == []                     # 이름 둘에 번호 하나 — 모른다
    assert idnums.pairs_in_text("김가나다 202600001", names) == []                          # 다른 이름의 일부(앞이 한글)


def test_numbers_for_names_drops_names_with_two_numbers_and_numbers_on_two_names():
    texts = ["가나다 202600001\n라마바 202600002", "가나다 202600009", "사아자 202600002\n차카타 100001"]
    got = idnums.numbers_for_names(texts, ["가나다", "라마바", "사아자", "차카타"])
    assert got == {"차카타": "100001"}             # 가나다: 번호 둘 · 라마바 · 사아자: 한 번호에 두 사람 — 번호로 찾지 않고 이름으로
