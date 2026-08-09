"""CLI 종단 테스트 — 실제 PDF 파일을 만들어 파이프라인 전체를 통과시킨다.

다른 테스트는 텍스트에서 바로 Document 를 만들지만, 여기서는 진짜 PDF 를 써서
pdfplumber 추출·좌표 기반 표 재조립·손상 헤더 복구까지 함께 확인한다.

한글 글꼴이 없는 환경에서는 PDF 에 한글을 그릴 수 없으므로 건너뛴다.
"""
from pathlib import Path

import pytest

from app.cli import main

from . import fixtures as fx

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "C:/Windows/Fonts/malgun.ttf",
)


def _korean_font() -> str:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    pytest.skip("한글 글꼴이 없어 한글 PDF 를 만들 수 없습니다")


@pytest.fixture
def write_pdf():
    pytest.importorskip("reportlab")
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font = _korean_font()
    pdfmetrics.registerFont(TTFont("검토용한글", font))

    def write(path: Path, pages: list[str]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(path), pagesize=(595, 842))
        for text in pages:
            pdf.setFont("검토용한글", 10)
            y = 800
            for line in text.strip("\n").splitlines():
                pdf.drawString(50, y, line)
                y -= 14
            pdf.showPage()
        pdf.save()
        return path

    return write


def test_review_of_a_clean_case_exits_zero(tmp_path, write_pdf, capsys):
    root = tmp_path / "권석재"
    write_pdf(root / "26학년도 1학기 TA 기본서류(권석재).pdf",
              [fx.TA_FORM1, fx.TA_FORM2, fx.TA_FORM3, fx.TA_FORM4])
    write_pdf(root / "2026년도 3월 TA 근무상황부.pdf", [fx.TA_WORKLOG])
    write_pdf(root / "2026년도 3월 (나)형 근로장학금 지급내역.pdf", [fx.TA_ROSTER])

    code = main(["review", str(root), "--type", "근로장학금", "--subtype", "TA"])
    output = capsys.readouterr().out

    assert code == 0
    assert "🔴 수정 필요 0건" in output
    assert "자동 검토에서 문제를 찾지 못했습니다" in output


def test_review_flags_problems_and_recovers_a_broken_pdf(tmp_path, write_pdf, capsys):
    """이동재 건. 출장신청서는 헤더가 깨진 전자결재 출력본을 흉내 낸다."""
    root = tmp_path / "이동재"
    request = write_pdf(root / "국내 출장신청서(이동재).pdf", [fx.LEE_DJ_REQUEST])
    request.write_bytes(b"HandyReportGarbage" + request.read_bytes())

    write_pdf(root / "이동재 출장증빙.pdf", [fx.LEE_DJ_EVIDENCE])
    write_pdf(root / "하이패스 통행료.pdf", [fx.LEE_DJ_TOLLGATE])
    write_pdf(root / "COSS 강연정보 캡처.pdf", [fx.LEE_DJ_PURPOSE])

    code = main(["review", str(root), "--type", "출장비"])
    output = capsys.readouterr().out

    assert code == 1                                  # 🔴 가 있으면 1
    assert "R-TRV-006" in output                      # 총 이동경로 공란
    assert "164km 를 기재하세요" in output             # 계산된 정답 제시
    assert "R-TRV-004" in output                      # 체류 증빙 7/3 누락
    assert "R-TRV-011" in output                      # 7/3 13:20 통행료
    # 헤더가 깨진 신청서를 실제로 읽어 냈는가
    assert "국내 출장신청서 (전자결재본)" in output
    assert "출장기간" in output


def test_classify_command(tmp_path, write_pdf, capsys):
    root = tmp_path / "AIMPACT"
    write_pdf(root / "혁신인재_5월 AIMPACT_.pdf", [fx.INN_FORM8])
    write_pdf(root / "활동보고서 (AIMPACT_5월).pdf", [fx.INN_FORM7_1])

    assert main(["classify", str(root), "--type", "혁신인재지원금"]) == 0
    output = capsys.readouterr().out
    assert "form8_application" in output
    assert "form7_1_report" in output


def test_markdown_export(tmp_path, write_pdf, capsys):
    root = tmp_path / "이동재"
    write_pdf(root / "이동재 출장증빙.pdf", [fx.LEE_DJ_EVIDENCE])
    write_pdf(root / "국내 출장신청서(이동재).pdf", [fx.LEE_DJ_REQUEST])

    out = tmp_path / "수정요청서.md"
    main(["review", str(root), "--type", "출장비", "--format", "md", "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# 지출 서류 수정 요청")
    assert "**조치:**" in text


def test_subtype_is_required_for_scholarship(tmp_path, write_pdf):
    root = tmp_path / "권석재"
    write_pdf(root / "근무상황부.pdf", [fx.TA_WORKLOG])
    with pytest.raises(SystemExit):
        main(["review", str(root), "--type", "근로장학금"])
