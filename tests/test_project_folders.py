"""과제 폴더(project_folders.py) — 담당자가 2026-10-21 에 저장 폴더를 '(과제번호)_…' 폴더로 나눴다. 폴더 이름은 실제 모양(과제번호 ·
연도 · 사업비)을 따랐고 금액은 공개된 사업비다. PDF 는 가짜로 만든다."""
from __future__ import annotations

from pathlib import Path

import pytest

from claim_downloader import archive, project_folders as pf

NAMES = ["(202408470001)_2024년도 사업비_4,179,251,000", "(202408470002)_2025년도 사업비(출연금)_4,462,000,000",
         "(202408470003)_2026년도 사업비_4,438,000,000", "(202502320001)_2024년 이월금_349,418,840"]


def make(tmp_path: Path, *extra: str) -> Path:
    root = tmp_path / "지출결의서"
    for name in NAMES + list(extra):
        (root / name).mkdir(parents=True)
    (root / "보조금 집행내역.xlsx").write_text("x")
    return root


def test_folders_are_read_from_names(tmp_path):
    root = make(tmp_path, "e나라도움 부정징후 현장점검 자료(24년도)", "청구서자동화")
    found = pf.folders(root)
    assert [f.no for f in found] == ["202408470001", "202408470002", "202408470003", "202502320001"]
    assert found[1].short() == "202408470002 2025년도 사업비(출연금)"           # 끝의 금액은 뺀다
    assert found[3].title == "2024년 이월금_349,418,840"
    assert pf.project_of("( 202603130001 ) 2025년 이월금") == "202603130001" and pf.project_of("청구서자동화") == ""


def test_signature_changes_when_a_project_folder_is_added(tmp_path):
    """앱을 켠 채 과제 폴더를 더 만들면(2026-10-22 연구지원비 다섯) 받기 화면이 열릴 때 과제 칸을 다시 채우는 근거."""
    root = make(tmp_path)
    before = pf.signature(root)
    assert before == ("202408470001", "202408470002", "202408470003", "202502320001")
    (root / "(202508100001)_2025년 연구지원비(책임자)_20,000,000").mkdir()          # 비목 폴더 없이 빈 폴더
    after = pf.signature(root)
    assert after != before and "202508100001" in after and pf.signature("") == ()


def test_save_root_goes_into_the_project_folder_only(tmp_path):
    root = make(tmp_path)
    where, why = pf.save_root(root, "202408470003")
    assert where == root / NAMES[2] and not why
    where, why = pf.save_root(root, "202409710003")                          # 폴더 없는 과제 — 받지 않는다
    assert where is None and "(202409710003)_" in why
    where, why = pf.save_root(root, "")
    assert where is None and "과제를 고르세요" in why
    (root / "(202408470003)_사본").mkdir()
    where, why = pf.save_root(root, "202408470003")
    assert where is None and "2개" in why
    # 저장 폴더를 과제 폴더 하나로 잡은 경우 — 그 과제만
    assert pf.save_root(root / NAMES[0], "202408470001") == (root / NAMES[0], "")
    assert pf.save_root(root / NAMES[0], "202408470003")[0] is None


def test_old_layout_without_project_folders_is_used_as_before(tmp_path):
    old = tmp_path / "2026년도(e나라도움)"
    (old / "09. 그 밖의사업운영경비").mkdir(parents=True)
    assert pf.save_root(old, "202408470003") == (old, "")
    assert pf.save_root(old, "") == (old, "")


def test_missing_old_folder_follows_to_the_parent_with_project_folders(tmp_path):
    root = make(tmp_path)
    assert pf.migrate(str(root / "2026년도(e나라도움)")) == str(root)
    assert pf.migrate(str(root)) == ""                                         # 있는 폴더는 그대로
    assert pf.migrate(str(tmp_path / "없는곳" / "2026년도")) == ""
    assert pf.migrate("") == ""


def test_counts_and_scan_cover_only_project_folders(tmp_path, isolated_home):
    root = make(tmp_path, "e나라도움 부정징후 현장점검 자료(24년도)")
    for name, sub in ((NAMES[2], "09. 그 밖의사업운영경비"), (NAMES[0], "09. 그 밖의사업운영경비/업로드"),
                      ("e나라도움 부정징후 현장점검 자료(24년도)", "")):
        folder = root / name / sub
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name[:14]}.pdf").write_bytes(b"%PDF-1.4")
    counts = archive.folder_status(str(root))
    assert [(c.name, c.waiting, c.uploaded) for c in counts] == [("09. 그 밖의사업운영경비", 1, 1)]
    done: set[str] = set()
    read = []
    report = archive.scan_archive(str(root), isolated_home / "cache.json", done,
                                  reader=lambda p: read.append(p.name) or "202408470003-20261001-1")
    assert report.ok and report.total_pdfs == 2 and not any("현장" in name for name in read)     # 점검 자료 폴더는 보관본이 아니다


def test_chosen_projects_keep_folder_order_and_drop_missing():
    """여러 과제 고르기(담당자 요청 2026-10-21) — 설정에 남긴 번호 중 지금 폴더가 있는 것만, 폴더 차례대로."""
    found = ["202408470001", "202408470002", "202408470003", "202502320001"]
    assert pf.pick(found, "202502320001,202408470001") == ["202408470001", "202502320001"]
    assert pf.pick(found, "202409710003, 202408470003") == ["202408470003"]              # 폴더 없는 과제는 빠진다
    assert pf.pick(found, "") == [] and pf.pick([], "202408470001") == []


def test_counts_include_matching_fund_folders(tmp_path):
    """대응자금 과제의 비목 폴더는 예산 탭 차례의 'NN. 비목명'(담당자 2026-10-21) — 사업비 이름표에 없어도 대기 · 완료 수에 넣는다."""
    root = make(tmp_path)
    fund = root / "(202409710003)_2026년도 대응자금_254,907,000"
    for sub in ("01. 장학금", "02. 연구시설장비비/업로드"):
        (fund / sub).mkdir(parents=True)
        (fund / sub / "a.pdf").write_bytes(b"%PDF-1.4")
    (fund / "참고자료").mkdir()
    counts = {c.name: (c.waiting, c.uploaded) for c in archive.folder_status(str(root))}
    assert counts == {"01. 장학금": (1, 0), "02. 연구시설장비비": (0, 1)}


def test_initial_choice_and_scope():
    """증빙 다운로드 ② 의 과제 체크(담당자 2026-10-22 "체크체크해서 단일이나 복수") — 다음에 열 때 지난번 고른 그대로."""
    found = ["202408470001", "202408470003", "202409710003", "202508100000"]
    assert pf.initial_choice(found, "all", "", "202408470003") == found
    assert pf.initial_choice(found, "some", "202409710003,202408470001", "") == ["202408470001", "202409710003"]
    assert pf.initial_choice(found, "one", "", "202409710003") == ["202409710003"]
    assert pf.initial_choice(found, "one", "", "202699990001") == found           # 폴더를 지운 과제면 모두
    assert pf.initial_choice(found, "some", "202699990001", "") == found
    assert pf.scope_of(found, found) == "all" and pf.scope_of(found + ["x"], found) == "all"
    assert pf.scope_of(["202408470003"], found) == "one"
    assert pf.scope_of(["202408470003", "202508100000"], found) == "some"
    assert pf.scope_of(["202408470003"], ["202408470003"]) == "all"               # 과제 폴더가 하나뿐이면 모두 = 하나


def test_search_matches_number_name_and_words():
    """과제 찾기 칸(담당자 2026-10-22 "그리고 검색 기능도") — 번호 일부 · 이름 일부, 띄어쓰기 · 대소문자 무시, 낱말마다."""
    texts = ("202508100003", "(202508100003)_2025년 연구지원비(홍길동)_20,000,000", "")
    assert pf.matches("", *texts) and pf.matches("   ", *texts)
    assert pf.matches("연구지원비", *texts) and pf.matches("0003", *texts) and pf.matches("연구 지원비", *texts)
    assert pf.matches("2025 홍길동", *texts) and not pf.matches("2026 홍길동", *texts)
    assert not pf.matches("대응자금", *texts)
    assert pf.matches("data", "202408470003", "(202408470003)_2026년도 사업비", "Data보안 혁신융합대학")      # ERP 과제명 · 영문 대소문자


def _qt_app():
    import os

    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _close(widget) -> None:
    """화면을 Qt 가 끝나기 전에 지운다 — 남겨 두면 파이썬이 끝날 때 QApplication 보다 늦게 지워져 시험 프로세스가 죽는다."""
    from PySide6.QtCore import QCoreApplication, QEvent

    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_checklist_single_multiple_and_search(tmp_path):
    """체크 하나 = 그 과제만, 여럿 = 차례로. 찾기는 줄만 숨기고 체크는 그대로 — 찾은 과제만 · 더하기 · 빼기."""
    _qt_app()
    from claim_downloader.ui.project_box import ProjectChecklist

    root = make(tmp_path, "(202508100000)_2025년 연구지원비(가)_20,000,000", "(202508100001)_2025년 연구지원비(나)_20,000,000")
    found = pf.folders(root)
    box = ProjectChecklist()
    fired = []
    box.changed.connect(lambda: fired.append(1))
    box.fill(found, ["202408470003"])
    assert box.chosen() == ["202408470003"] and "그 과제만" in box.count.text() and not fired
    box.search.setText("연구지원비")
    assert [c.text()[:12] for _f, c in box.checks if not c.isHidden()] == ["202508100000", "202508100001"]
    assert box.only.isVisibleTo(box) and box.every.text() == "찾은 과제 더하기"
    box.every.click()                                        # 찾은 과제 더하기 — 이미 고른 것은 그대로
    assert box.chosen() == ["202408470003", "202508100000", "202508100001"] and len(fired) == 1
    assert "안 보이는 체크 1개도 받습니다" in box.count.text()
    box.only.click()                                         # 찾은 과제만
    assert box.chosen() == ["202508100000", "202508100001"]
    box.none.click()                                         # 찾은 과제 빼기
    assert box.chosen() == [] and "하나 이상 체크" in box.count.text()
    box.search.setText("없는과제")
    assert box.empty.isVisibleTo(box) and not box.every.isEnabled()
    box.search.clear()
    assert box.every.text() == "모두 고르기" and not box.only.isVisibleTo(box)
    box.every.click()
    assert box.chosen() == [f.no for f in found]
    box.fill(found, ["202502320001"])                        # 다시 채워도 찾기 글은 그대로 두고 거른다
    assert box.chosen() == ["202502320001"] and box.label_of("202502320001") == "202502320001 2024년 이월금"
    _close(box)


def test_download_page_reads_checked_projects(tmp_path, monkeypatch):
    """증빙 다운로드 ② — 체크한 과제가 하나면 그 과제 목록(read_list), 여럿이면 차례로(read_lists). 고른 것은 설정에 남는다."""
    _qt_app()
    from claim_downloader import settings
    from claim_downloader.ui.pages.download import DownloadPage

    root = make(tmp_path)
    settings.update(out_root=str(root), download_scope="some", download_projects="202502320001,202408470002")
    page = DownloadPage()
    calls = []
    monkeypatch.setattr(page.worker, "read_list", lambda no: calls.append(("one", no)))
    monkeypatch.setattr(page.worker, "read_lists", lambda nos: calls.append(("many", list(nos))))
    assert page._projects() == ["202408470002", "202502320001"] and page._project_text() == "고른 과제 2개"
    page._read_list()
    assert calls[-1] == ("many", ["202408470002", "202502320001"])
    page.project_list.none.click()
    assert page._projects() == [] and not page.next_button.isEnabled()
    page._read_list()
    assert len(calls) == 1 and page.state_pill.text() == "과제 없음"            # 아무것도 체크하지 않으면 읽지 않는다
    assert settings.load().download_projects == "202502320001,202408470002"   # 다 푼 것은 남기지 않는다(지난번 그대로)
    for folder, check in page.project_list.checks:
        check.setChecked(folder.no == "202408470003")
    assert page._projects() == ["202408470003"] and page._project_text() == "과제 202408470003"
    page._read_list()
    assert calls[-1] == ("one", "202408470003")
    current = settings.load()
    assert (current.download_scope, current.download_projects, current.project_no) == ("one", "202408470003", "202408470003")
    page.project_list.every.click()
    assert settings.load().download_scope == "all" and page._project_text() == "폴더 만든 과제 4개"
    (root / "(202603130001)_2025년 이월금_100,000,000").mkdir()             # 앱을 켠 채 폴더를 더 만들면 — 모두 체크였으니 그것도
    page._refresh_projects()
    assert page._projects()[-1] == "202603130001" and len(page._projects()) == 5
    _close(page)
