""".hwpx 생성 — 한글 2014 이상에서 열리는 개방형 한글 문서. 표준 라이브러리만 쓴다.

옛 도구(core.py)에서 그대로 옮겼다. **정리하거나 라이브러리로 바꾸지 않는다** — 한글이 못 연다.

표 병합이 .docx 와 반대다: .docx 는 병합할 셀을 모두 쓰고 vMerge 로 표시하지만, .hwpx 는 첫 셀에
rowSpan 을 주고 **이후 행에서는 셀을 아예 생략**한다. cellAddr(colAddr/rowAddr)과 cellSpan 이
정확해야 하고, 격자에 겹침이나 빈칸이 하나라도 있으면 한글이 "손상된 파일" 이라며 열지 않는다.
참석자 칸 수가 가변이라(schema._attendee_rows) 특히 위험하다 — 표를 건드렸으면
tests/test_minutes.py 의 격자 검사를 돌린다.

패키지 규칙: mimetype 은 첫 항목·무압축(STORED). header.xml 의 id 를 section0.xml 이 참조하므로
id 참조가 하나라도 깨지면 안 열린다. itemCnt 선언값과 실제 개수가 같아야 한다.
"""
from __future__ import annotations

import zipfile

from .schema import FONT, HEADER_TITLE, PROJECT_NAME, SHADE, _attendee_rows, _esc

# 단위: HWPUNIT = 1/7200 인치. docx 의 dxa(1/20 pt) 에 5 를 곱하면 된다.
HWPX_PAGE_W, HWPX_PAGE_H = 59528, 84188      # A4
HWPX_MARGIN = 7090                            # 25mm
HEADER_FOOTER_MARGIN = 4252
HWPX_TBL_W = 45000                            # 표 전체 너비
# 글자 모양: (굵게, docx 크기(하프포인트), 색). 목록 순서가 그대로 charPr id 가 된다.
HWPX_CHARS = [
    (False, 22, None),      # 0 본문
    (True, 22, None),       # 1 표 라벨
    (True, 24, None),       # 2 머리글
    (True, 36, None),       # 3 '회 의 록'
    (False, 20, "808080"),  # 4 보완사항 없음
    (True, 20, "C00000"),   # 5 보완요청
]
HWPX_ALIGNS = ["LEFT", "CENTER", "JUSTIFY"]   # paraPr id 0, 1, 2
HWPX_BF_NONE, HWPX_BF_CELL, HWPX_BF_SHADE = 1, 2, 3


def _hwpx_char_id(bold=False, size=22, color=None):
    return HWPX_CHARS.index((bool(bold), int(size), color))


def _hwpx_p(text, char_id=0, para_id=0):
    """문단 하나. 줄바꿈은 문단 분리로 처리한다."""
    out = ""
    for seg in str(text).split("\n"):
        out += ('<hp:p id="0" paraPrIDRef="%d" styleIDRef="0" pageBreak="0"'
                ' columnBreak="0" merged="0">'
                '<hp:run charPrIDRef="%d"><hp:t>%s</hp:t></hp:run>'
                '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000"'
                ' textheight="1000" baseline="850" spacing="600" horzpos="0"'
                ' horzsize="%d" flags="393216"/></hp:linesegarray>'
                '</hp:p>' % (para_id, char_id, _esc(seg), HWPX_TBL_W))
    return out


def _hwpx_tc(paras, col, row, colspan, rowspan, width, height, shade=False):
    bf = HWPX_BF_SHADE if shade else HWPX_BF_CELL
    return ('<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0"'
            ' dirty="0" borderFillIDRef="%d">'
            '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK"'
            ' vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0"'
            ' textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">%s</hp:subList>'
            '<hp:cellAddr colAddr="%d" rowAddr="%d"/>'
            '<hp:cellSpan colSpan="%d" rowSpan="%d"/>'
            '<hp:cellSz width="%d" height="%d"/>'
            '<hp:cellMargin left="510" right="510" top="141" bottom="141"/>'
            '</hp:tc>' % (bf, paras, col, row, colspan, rowspan, width, height))


def _hwpx_header_xml():
    fonts = ""
    for lang in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"):
        fonts += ('<hh:fontface lang="%s" fontCnt="1">'
                  '<hh:font id="0" face="%s" type="TTF" isEmbedded="0">'
                  '<hh:typeInfo familyType="FCAT_GOTHIC" weight="0" proportion="0"'
                  ' contrast="0" strokeVariation="0" armStyle="0" letterform="0"'
                  ' midline="0" xHeight="0"/></hh:font></hh:fontface>' % (lang, FONT))

    def border_fill(bid, solid, fill):
        edge = ('<hh:%s type="%s" width="%s" color="%s"/>')
        sides = ""
        for s in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
            sides += (edge % (s, "SOLID", "0.12 mm", "#333333") if solid
                      else edge % (s, "NONE", "0.1 mm", "#000000"))
        brush = ('<hc:fillBrush><hc:winBrush faceColor="#%s" hatchColor="#999999"'
                 ' alpha="0"/></hc:fillBrush>' % fill) if fill else ""
        return ('<hh:borderFill id="%d" threeD="0" shadow="0" centerLine="NONE"'
                ' breakCellSeparateLine="0">'
                '<hh:slash type="NONE" Crooked="0" isCounter="0"/>'
                '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
                '%s<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>%s'
                '</hh:borderFill>' % (bid, sides, brush))

    fills = (border_fill(HWPX_BF_NONE, False, None)
             + border_fill(HWPX_BF_CELL, True, None)
             + border_fill(HWPX_BF_SHADE, True, SHADE))

    chars = ""
    for i, (bold, size, color) in enumerate(HWPX_CHARS):
        chars += ('<hh:charPr id="%d" height="%d" textColor="#%s" shadeColor="none"'
                  ' useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="%d">'
                  '<hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0"'
                  ' symbol="0" user="0"/>'
                  '<hh:ratio hangul="100" latin="100" hanja="100" japanese="100"'
                  ' other="100" symbol="100" user="100"/>'
                  '<hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0"'
                  ' symbol="0" user="0"/>'
                  '<hh:relSz hangul="100" latin="100" hanja="100" japanese="100"'
                  ' other="100" symbol="100" user="100"/>'
                  '<hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0"'
                  ' symbol="0" user="0"/>'
                  '%s</hh:charPr>'
                  % (i, size * 50, color or "000000", HWPX_BF_NONE,
                     "<hh:bold/>" if bold else ""))

    paras = ""
    for i, align in enumerate(HWPX_ALIGNS):
        paras += ('<hh:paraPr id="%d" tabPrIDRef="0" condense="0" fontLineHeight="0"'
                  ' snapToGrid="1" suppressLineNumbers="0" checked="0">'
                  '<hh:align horizontal="%s" vertical="BASELINE"/>'
                  '<hh:heading type="NONE" idRef="0" level="0"/>'
                  '<hh:breakSetting breakLatinWord="KEEP_WORD"'
                  ' breakNonLatinWord="BREAK_WORD" widowOrphan="0" keepWithNext="0"'
                  ' keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>'
                  '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
                  '<hh:margin>'
                  '<hc:intent value="0" unit="HWPUNIT"/>'
                  '<hc:left value="0" unit="HWPUNIT"/>'
                  '<hc:right value="0" unit="HWPUNIT"/>'
                  '<hc:prev value="0" unit="HWPUNIT"/>'
                  '<hc:next value="0" unit="HWPUNIT"/>'
                  '</hh:margin>'
                  '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>'
                  '<hh:border borderFillIDRef="%d" offsetLeft="0" offsetRight="0"'
                  ' offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>'
                  '</hh:paraPr>' % (i, align, HWPX_BF_NONE))

    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"'
            ' xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"'
            ' version="1.4" secCnt="1">'
            '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
            '<hh:refList>'
            '<hh:fontfaces itemCnt="7">' + fonts + '</hh:fontfaces>'
            '<hh:borderFills itemCnt="3">' + fills + '</hh:borderFills>'
            '<hh:charProperties itemCnt="%d">' % len(HWPX_CHARS) + chars
            + '</hh:charProperties>'
            '<hh:tabProperties itemCnt="1">'
            '<hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/>'
            '</hh:tabProperties>'
            '<hh:numberings itemCnt="0"/>'
            '<hh:paraProperties itemCnt="%d">' % len(HWPX_ALIGNS) + paras
            + '</hh:paraProperties>'
            '<hh:styles itemCnt="1">'
            '<hh:style id="0" type="PARA" name="바탕글" engName="Normal"'
            ' paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042"'
            ' lockForm="0"/>'
            '</hh:styles>'
            '</hh:refList>'
            '<hh:compatibleDocument targetProgram="HWP201X">'
            '<hh:layoutCompatibility/></hh:compatibleDocument>'
            '</hh:head>')


def _hwpx_section_xml(data):
    agenda = data.get("agenda", "")
    content = data.get("content", [])
    if isinstance(content, str):
        content = [content]
    supplement = str(data.get("supplement", "") or "").strip() or "보완사항 없음"
    has_issue = supplement != "보완사항 없음"
    attendees = _attendee_rows(data)

    w = [int(round(HWPX_TBL_W * n / 9200.0)) for n in (1900, 1900)]
    w.append(HWPX_TBL_W - w[0] - w[1])
    RH = 1700                                   # 기본 행 높이

    label = _hwpx_char_id(True, 22)
    body_c = _hwpx_char_id(False, 22)
    rows_xml, r = "", 0

    def tr(cells):
        return "<hp:tr>" + "".join(cells) + "</hp:tr>"

    # 머리글
    rows_xml += tr([_hwpx_tc(_hwpx_p(HEADER_TITLE, _hwpx_char_id(True, 24), 1),
                             0, r, 3, 1, HWPX_TBL_W, RH, shade=True)])
    r += 1
    for lab, val in (("사 업 명", PROJECT_NAME), ("회의안건", agenda),
                     ("회의일시", data.get("date", "")), ("회의장소", data.get("place", "")),
                     ("회의비 사용처", data.get("expensePlace", "")),
                     ("금액", data.get("amount", ""))):
        rows_xml += tr([_hwpx_tc(_hwpx_p(lab, label, 1), 0, r, 1, 1, w[0], RH, shade=True),
                        _hwpx_tc(_hwpx_p(val, body_c, 0), 1, r, 2, 1, w[1] + w[2], RH)])
        r += 1

    # 참석자 (세로 병합은 rowSpan 으로 표현하고, 병합된 행에서는 셀을 아예 넣지 않는다)
    att = attendees
    span = 1 + len(att)
    rows_xml += tr([_hwpx_tc(_hwpx_p("참석자", label, 1), 0, r, 1, span, w[0], RH, shade=True),
                    _hwpx_tc(_hwpx_p("소속", label, 1), 1, r, 1, 1, w[1], RH, shade=True),
                    _hwpx_tc(_hwpx_p("이름", label, 1), 2, r, 1, 1, w[2], RH, shade=True)])
    r += 1
    i = 0
    while i < len(att):
        j = i
        while j + 1 < len(att) and att[j + 1][0] == att[i][0]:
            j += 1
        group = j - i + 1
        for k in range(i, j + 1):
            cells = []
            if k == i:
                cells.append(_hwpx_tc(_hwpx_p(att[i][0], body_c, 1), 1, r, 1, group, w[1], RH))
            cells.append(_hwpx_tc(_hwpx_p(att[k][1], body_c, 1), 2, r, 1, 1, w[2], RH))
            rows_xml += tr(cells)
            r += 1
        i = j + 1

    # 회의내용
    rows_xml += tr([_hwpx_tc(_hwpx_p("회의내용 및 협의사항", label, 1),
                             0, r, 3, 1, HWPX_TBL_W, RH, shade=True)])
    r += 1
    paras = "".join(_hwpx_p(p, body_c, 2) for p in content if str(p).strip()) \
        or _hwpx_p("", body_c, 2)
    rows_xml += tr([_hwpx_tc(paras, 0, r, 3, 1, HWPX_TBL_W, RH * 6)])
    r += 1

    tbl = ('<hp:tbl id="1" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM"'
           ' textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL"'
           ' repeatHeader="1" rowCnt="%d" colCnt="3" cellSpacing="0"'
           ' borderFillIDRef="%d" noAdjust="0">'
           '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d" heightRelTo="ABSOLUTE"'
           ' protect="0"/>'
           '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0"'
           ' holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP"'
           ' horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
           '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
           '<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
           '%s</hp:tbl>' % (r, HWPX_BF_CELL, HWPX_TBL_W, RH * r, rows_xml))

    sec_pr = ('<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134"'
              ' tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1"'
              ' memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">'
              '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0" strtnum="0"/>'
              '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
              '<hp:visibility hideFirstHeader="0" hideFirstFooter="0"'
              ' hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL"'
              ' hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
              '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
              '<hp:pagePr landscape="WIDELY" width="%d" height="%d" gutterType="LEFT_ONLY">'
              '<hp:margin header="%d" footer="%d" gutter="0" left="%d" right="%d"'
              ' top="%d" bottom="%d"/></hp:pagePr>'
              '<hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar=""'
              ' suffixChar=")" supscript="0"/><hp:noteLine length="-1" type="SOLID"'
              ' width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="850"'
              ' belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS"'
              ' newNum="1"/><hp:placement place="EACH_COLUMN" beneathText="0"/>'
              '</hp:footNotePr>'
              '<hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar=""'
              ' suffixChar=")" supscript="0"/><hp:noteLine length="14692" type="SOLID"'
              ' width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="0"'
              ' belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS"'
              ' newNum="1"/><hp:placement place="END_OF_DOCUMENT" beneathText="0"/>'
              '</hp:endNotePr>'
              % (HWPX_PAGE_W, HWPX_PAGE_H, HEADER_FOOTER_MARGIN, HEADER_FOOTER_MARGIN,
                 HWPX_MARGIN, HWPX_MARGIN, HWPX_MARGIN, HWPX_MARGIN))
    for kind in ("BOTH", "EVEN", "ODD"):
        sec_pr += ('<hp:pageBorderFill type="%s" borderFillIDRef="%d" textBorder="PAPER"'
                   ' headerInside="0" footerInside="0" fillArea="PAPER">'
                   '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/>'
                   '</hp:pageBorderFill>' % (kind, HWPX_BF_NONE))
    sec_pr += '</hp:secPr>'

    note_text = ("[보완요청] " + supplement) if has_issue else "[보완사항 없음]"
    note_char = _hwpx_char_id(True, 20, "C00000") if has_issue \
        else _hwpx_char_id(False, 20, "808080")

    first = ('<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0"'
             ' columnBreak="0" merged="0"><hp:run charPrIDRef="%d">%s<hp:t>%s</hp:t>'
             '</hp:run>'
             '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000"'
             ' textheight="1000" baseline="850" spacing="600" horzpos="0"'
             ' horzsize="%d" flags="393216"/></hp:linesegarray></hp:p>'
             % (note_char, sec_pr, _esc(note_text), HWPX_TBL_W))

    title = _hwpx_p("회 의 록", _hwpx_char_id(True, 36), 1)
    tbl_p = ('<hp:p id="0" paraPrIDRef="1" styleIDRef="0" pageBreak="0"'
             ' columnBreak="0" merged="0"><hp:run charPrIDRef="%d">%s</hp:run>'
             '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000"'
             ' textheight="1000" baseline="850" spacing="600" horzpos="0"'
             ' horzsize="%d" flags="393216"/></hp:linesegarray></hp:p>'
             % (body_c, tbl, HWPX_TBL_W))

    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
            ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
            ' xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">'
            + first + title + tbl_p + _hwpx_p("", body_c, 0) + '</hs:sec>')


def build_hwpx(data, out_path):
    """한글(HWPX) 문서를 만든다. 표준 라이브러리만 사용한다."""
    header = _hwpx_header_xml()
    section = _hwpx_section_xml(data)

    version = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version"'
               ' tagetApplication="WORDPROCESSOR" major="5" minor="0" micro="5"'
               ' buildNumber="0" os="1" xmlVersion="1.4"'
               ' application="Hancom Office Hangul" appVersion="9.1.1.5656"/>')
    container = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container"'
                 ' xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">'
                 '<ocf:rootfiles>'
                 '<ocf:rootfile full-path="Contents/content.hpf"'
                 ' media-type="application/hwpml-package+xml"/>'
                 '</ocf:rootfiles></ocf:container>')
    parts = [("Contents/content.hpf", "application/hwpml-package+xml"),
             ("Contents/header.xml", "application/xml"),
             ("Contents/section0.xml", "application/xml"),
             ("settings.xml", "application/xml")]
    manifest = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"'
                ' version="1.2">'
                + "".join('<odf:file-entry full-path="%s" media-type="%s"/>' % p
                          for p in parts)
                + '</odf:manifest>')
    content_hpf = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/"'
                   ' xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"'
                   ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
                   ' version="" unique-identifier="" id="">'
                   '<opf:metadata>'
                   '<opf:title>%s</opf:title>'
                   '<opf:language>ko</opf:language>'
                   '<opf:meta name="creator" content=""/>'
                   '</opf:metadata>'
                   '<opf:manifest>'
                   '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
                   '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
                   '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>'
                   '</opf:manifest>'
                   '<opf:spine>'
                   '<opf:itemref idref="header" linear="yes"/>'
                   '<opf:itemref idref="section0" linear="yes"/>'
                   '</opf:spine>'
                   '</opf:package>' % _esc(HEADER_TITLE))
    settings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<ha:HWPApplicationSetting'
                ' xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"'
                ' xmlns:config="http://www.hancom.co.kr/hwpml/2011/configItemSet">'
                '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>'
                '</ha:HWPApplicationSetting>')

    # 미리보기 텍스트 (한글이 파일 목록에서 쓰는 값. 없어도 열리지만 넣어 둔다)
    preview = "\n".join([HEADER_TITLE, str(data.get("agenda", "") or ""),
                         str(data.get("date", "") or "")])

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype 은 반드시 첫 항목이며 압축하지 않는다.
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("version.xml", version)
        z.writestr("META-INF/container.xml", container)
        z.writestr("META-INF/manifest.xml", manifest)
        z.writestr("Contents/content.hpf", content_hpf)
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/section0.xml", section)
        z.writestr("settings.xml", settings)
        z.writestr("Preview/PrvText.txt", preview)
