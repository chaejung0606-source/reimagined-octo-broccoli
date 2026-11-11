"""폴더 고르기 — 업무마다 작업 폴더에서 열고 여러 개를 고른다(담당자 2026-11-11).

"카드청구에서 폴더고를때 바로 아래 폴더가 뜨도록 설정 C:\\Users\\…\\Desktop\\★★지출진행\\2. 카드" · "그리고 폴더 여러개 선택가능하도록 설정".
"""
from __future__ import annotations

import time

import pytest

from claim_downloader import work_folders
from claim_downloader.claims import kinds

PERIODS = ("26-09(09.09. ~ 10.08.)", "26-10(10.09. ~ 11.08.)")


def _desk(tmp_path):
    desk = tmp_path / "Desktop"
    work = desk / "★★지출진행"
    card = work / "2. 카드"
    for name in (*PERIODS, "★erp 청구"):
        (card / name).mkdir(parents=True)
    (work / "3. 출장비 및 프로그램참여지원비").mkdir()
    (work / "4. 장학금 및 혁신인재지원금").mkdir()
    return desk, card


def test_find_work_folder(tmp_path):
    desk, card = _desk(tmp_path)
    assert work_folders.find("", [tmp_path / "없음", desk], work_folders.CARD) == str(card)
    assert work_folders.find("", [desk], work_folders.TRAVEL).endswith("3. 출장비 및 프로그램참여지원비")
    assert work_folders.find(str(tmp_path), [desk], work_folders.CARD) == str(tmp_path)          # 설정이 먼저
    assert work_folders.find(str(tmp_path / "지운 폴더"), [desk], work_folders.CARD) == str(card)  # 설정한 폴더가 없어졌으면 찾는다
    assert work_folders.find("", [tmp_path / "없음"], work_folders.CARD) == ""


def _qt():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_picks_several_folders(tmp_path, monkeypatch):
    """Qt 폴더 창의 목록을 여러 줄 고르기로 — 둘을 고르고 [넣기] 하면 둘, 아무것도 안 고르면 지금 보는 폴더."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _qt()
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QAbstractItemView, QTreeView

    from claim_downloader.ui import folder_picker
    _desk_, card = _desk(tmp_path)
    dialog = folder_picker.folder_dialog(None, "카드 결제 기간 폴더 고르기", str(card))
    dialog.show()
    tree = next(v for v in dialog.findChildren(QTreeView) if v.objectName() == "treeView")
    assert tree.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    model, root = tree.model(), tree.rootIndex()
    for _ in range(200):                             # 폴더 목록은 뒤에서 읽힌다
        app.processEvents()
        if model.rowCount(root) == 3:
            break
        time.sleep(0.01)
    assert model.rowCount(root) == 3                 # 바로 아래 폴더가 뜬다
    for row in range(model.rowCount(root)):
        index = model.index(row, 0, root)
        if index.data() in PERIODS:
            tree.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    app.processEvents()
    dialog.accept()
    assert dialog.result() == 1
    assert sorted(folder_picker.chosen(dialog)) == sorted(str(card / n) for n in PERIODS)
    dialog.close()
    plain = folder_picker.folder_dialog(None, "t", str(card))
    plain.show()
    app.processEvents()
    plain.accept()
    assert folder_picker.chosen(plain) == [str(card)]
    plain.close()


def test_card_claim_opens_card_folder_and_adds_several(tmp_path, monkeypatch):
    """일반청구 ① 카드 → [지출 폴더 추가] 가 '2. 카드' 에서 열리고, 고른 기간 폴더 둘이 두 줄로 들어간다."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _qt()
    from claim_downloader import settings
    from claim_downloader.ui import folder_picker
    from claim_downloader.ui.pages import claim as claim_page
    from claim_downloader.ui.worker import SessionWorker
    desk, card = _desk(tmp_path)
    monkeypatch.setattr(folder_picker, "desktops", lambda: [desk])
    asked: list = []
    told: list = []
    monkeypatch.setattr(claim_page.QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    monkeypatch.setattr(folder_picker, "pick_folders", lambda parent, title, start: asked.append((title, start)) or [str(card / n) for n in PERIODS])
    page = claim_page.ClaimPage(worker=SessionWorker())
    page._add_one()                                  # 종류를 고르기 전 — 창을 열지 않고 한 번만 알린다
    assert asked == [] and len(told) == 1
    page._choose_kind(kinds.CARD)
    page._add_one()
    assert asked[-1][1] == str(card) and "여러 개" in asked[-1][0]
    assert page._dirs == [str(card / n) for n in PERIODS] and page._kinds == [kinds.CARD, kinds.CARD]
    settings.update(card_root=str(tmp_path))         # 설정한 폴더가 먼저
    page._add_one()
    assert asked[-1][1] == str(tmp_path)
    page._choose_kind(kinds.SCHOLARSHIP)             # 장학금은 전처럼 운영체제가 고른 곳
    page._add_one()
    assert asked[-1][1] == ""


def test_card_claim_folders_picked_together(tmp_path, monkeypatch):
    """담당자 2026-11-11 — 기간 폴더 안의 청구서 폴더('03_[비목명] …')를 하나든 여럿이든 골라 넣으면 폴더마다 청구서 하나, 대표적요는 폴더 이름."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _qt()
    from claim_downloader.ui import folder_picker
    from claim_downloader.ui.pages import claim as claim_page
    from claim_downloader.ui.worker import SessionWorker
    period = tmp_path / "26-10(10.09. ~ 11.08.)"
    names = ["03_[교육연구프로그램개발운영비] 카드 결제 건(26.10.09.~26.11.08.)",
             "07_[기업지원협력활동비] 2026학년도 2학기 WE-Meet 회의비 1차 지원 (10.09~10.27.)"]
    for name, item in zip(names, ["1021_(97)_ACK 2026 등록비 150,000원", "261020_(17)_군집방패 45,000원"]):
        (period / name / item).mkdir(parents=True)
    monkeypatch.setattr(folder_picker, "pick_folders", lambda parent, title, start: [str(period / n) for n in names])
    page = claim_page.ClaimPage(worker=SessionWorker())
    page._choose_kind(kinds.CARD)
    page._add_one()
    assert [job.sheets[0].main_summary for job in page._cards] == names
    assert [job.items[0].req_div for job in page._cards] == ["97", "17"]
