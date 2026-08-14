"""지급대상자별 묶기.

여러 학생의 서류를 한 폴더에 넣고 검토했더니, 서로 다른 사람의 성명·학번·
계좌·주민등록번호를 '불일치'로 판정하고 아홉 명의 개인정보를 한 명 것으로
통일하라는 수정 요청이 나갔다. 대사는 **같은 사람의 서류 안에서만** 해야 한다.
"""
from __future__ import annotations

from conftest import make_document

from expense_review.review import group_by_person


def _people(documents):
    return sorted(label for label, _ in group_by_person(documents))


# ── 사람을 가른다 ─────────────────────────────────────────────────────────

def test_different_students_become_separate_groups():
    documents = [
        make_document("claim_form", "배준영.pdf", name="배준영", student_id="202212069"),
        make_document("claim_form", "지영빈.pdf", name="지영빈", student_id="202312559"),
        make_document("claim_form", "최기범.pdf", name="최기범", student_id="202045678"),
    ]
    assert len(group_by_person(documents)) == 3
    assert _people(documents) == ["배준영", "지영빈", "최기범"]


def test_same_student_stays_in_one_group():
    """학번이 같으면 서류가 여러 장이어도 한 사람이다."""
    documents = [
        make_document("claim_form", "신청서.pdf", name="배준영", student_id="202212069"),
        make_document("bankbook", "통장사본.pdf", name="배준영", student_id="202212069"),
    ]
    groups = group_by_person(documents)
    assert len(groups) == 1 and len(groups[0][1]) == 2


def test_student_id_wins_over_name():
    """동명이인이 있어도 학번이 다르면 다른 사람이다."""
    documents = [
        make_document("claim_form", "a.pdf", name="김민수", student_id="202212069"),
        make_document("claim_form", "b.pdf", name="김민수", student_id="202312559"),
    ]
    assert len(group_by_person(documents)) == 2


def test_single_person_folder_is_one_group():
    documents = [
        make_document("claim_form", "신청서.pdf", name="배준영", student_id="202212069"),
        make_document("receipt_card", "영수증.jpg"),
    ]
    groups = group_by_person(documents)
    assert len(groups) == 1
    assert len(groups[0][1]) == 2          # 누구 것인지 모르는 영수증도 함께 간다


def test_unidentified_documents_go_to_every_group():
    """지급내역처럼 여러 사람이 실린 서류는 각 지급건의 대사 상대가 된다."""
    documents = [
        make_document("claim_form", "배준영.pdf", name="배준영", student_id="202212069"),
        make_document("claim_form", "지영빈.pdf", name="지영빈", student_id="202312559"),
        make_document("roster", "지급내역.pdf"),
    ]
    groups = group_by_person(documents)
    assert len(groups) == 2
    for _, docs in groups:
        assert any(d.doc_type == "roster" for d in docs)


# ── 다른 사람끼리 값이 다른 것은 오류가 아니다 ─────────────────────────────

def test_cross_person_differences_are_not_findings():
    """묶은 뒤에는 각 지급건 안에 값이 하나씩뿐이라 불일치가 나올 수 없다."""
    from conftest import ids, run

    documents = [
        make_document("claim_form", "배준영.pdf", name="배준영", student_id="202212069",
                      account_no="1002-123-456789", bank="국민은행"),
        make_document("claim_form", "지영빈.pdf", name="지영빈", student_id="202312559",
                      account_no="110-987-654321", bank="신한은행"),
    ]

    # 묶지 않고 한꺼번에 보면 성명·학번·계좌·은행이 모두 '불일치'로 잡힌다
    mixed = ids(run("혁신인재지원금", documents))
    assert {"R-CMN-003", "R-CMN-004", "R-CMN-005", "R-CMN-006"} & mixed

    # 사람별로 묶으면 하나도 나오지 않는다
    for label, group in group_by_person(documents):
        found = ids(run("혁신인재지원금", group, owner=label))
        assert not ({"R-CMN-003", "R-CMN-004", "R-CMN-005", "R-CMN-006"} & found)
