""".docx 대체본 — 한글 문서(.hwpx)를 만들지 못했을 때 회의록을 통째로 잃지 않기 위한 것.

표준 라이브러리만 쓴다. 옛 도구(core.py)에서 그대로 옮겼다. 고치지 않는다.
"""
from __future__ import annotations

import zipfile

from .schema import DEFAULT_ORG, FONT, HEADER_TITLE, PROJECT_NAME, SHADE, _attendee_rows, _esc


def _rpr(bold=False, size=22, color=None):
    s = '<w:rPr><w:rFonts w:ascii="%s" w:eastAsia="%s" w:hAnsi="%s"/>' % (FONT, FONT, FONT)
    if bold:
        s += '<w:b/>'
    if color:
        s += '<w:color w:val="%s"/>' % color
    s += '<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>' % (size, size)
    return s


def _runs(text, rpr):
    segs = str(text).split("\n")
    out = ""
    for i, seg in enumerate(segs):
        if i > 0:
            out += '<w:r><w:br/></w:r>'
        out += '<w:r>' + rpr + '<w:t xml:space="preserve">' + _esc(seg) + '</w:t></w:r>'
    return out


def _para(text, bold=False, size=22, color=None, align=None, after=120):
    ppr = '<w:pPr><w:spacing w:after="%d" w:line="288" w:lineRule="auto"/>' % after
    if align:
        ppr += '<w:jc w:val="%s"/>' % align
    ppr += '</w:pPr>'
    return '<w:p>' + ppr + _runs(text, _rpr(bold, size, color)) + '</w:p>'


def _cp(text, bold=False, align=None, size=22, after=0):
    # 표 셀 안 문단
    ppr = '<w:pPr><w:spacing w:after="%d" w:line="264" w:lineRule="auto"/>' % after
    if align:
        ppr += '<w:jc w:val="%s"/>' % align
    ppr += '</w:pPr>'
    return '<w:p>' + ppr + _runs(text, _rpr(bold=bold, size=size)) + '</w:p>'


def _tc(inner, w=None, gridspan=None, vmerge=None, shade=None, valign="center"):
    tcpr = '<w:tcPr>'
    tcpr += ('<w:tcW w:w="%d" w:type="dxa"/>' % w) if w else '<w:tcW w:w="0" w:type="auto"/>'
    if gridspan:
        tcpr += '<w:gridSpan w:val="%d"/>' % gridspan
    if vmerge == "restart":
        tcpr += '<w:vMerge w:val="restart"/>'
    elif vmerge == "continue":
        tcpr += '<w:vMerge/>'
    if shade:
        tcpr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % shade
    tcpr += '<w:vAlign w:val="%s"/></w:tcPr>' % valign
    return '<w:tc>' + tcpr + inner + '</w:tc>'


def build_docx(data, out_path):
    agenda = data.get("agenda", "")
    date = data.get("date", "")
    place = data.get("place", "")
    content = data.get("content", [])
    if isinstance(content, str):
        content = [content]
    supplement = str(data.get("supplement", "") or "").strip() or "보완사항 없음"
    has_issue = supplement != "보완사항 없음"
    attendees = _attendee_rows(data)

    def kv(label, value):
        return ('<w:tr>' + _tc(_cp(label, bold=True, align="center"), w=1900, shade=SHADE)
                + _tc(_cp(value), gridspan=2) + '</w:tr>')

    rows = ""
    # 머리글
    rows += '<w:tr>' + _tc(_cp(HEADER_TITLE, bold=True, align="center", size=24), gridspan=3, shade=SHADE) + '</w:tr>'
    rows += kv("사 업 명", PROJECT_NAME)
    rows += kv("회의안건", agenda)
    rows += kv("회의일시", date)
    rows += kv("회의장소", place)
    rows += kv("회의비 사용처", data.get("expensePlace", ""))
    rows += kv("금액", data.get("amount", ""))

    # 참석자 (소속/이름)
    rows += ('<w:tr>'
             + _tc(_cp("참석자", bold=True, align="center"), w=1900, vmerge="restart", shade=SHADE)
             + _tc(_cp("소속", bold=True, align="center"), w=1900, shade=SHADE)
             + _tc(_cp("이름", bold=True, align="center"), w=5400, shade=SHADE)
             + '</w:tr>')
    if attendees:
        for i, (org, name) in enumerate(attendees):
            label_cell = _tc(_cp(""), w=1900, vmerge="continue")
            if i == 0 or attendees[i - 1][0] != org:
                org_cell = _tc(_cp(org, align="center"), w=1900, vmerge="restart")
            else:
                org_cell = _tc(_cp(""), w=1900, vmerge="continue")
            name_cell = _tc(_cp(name, align="center"), w=5400)
            rows += '<w:tr>' + label_cell + org_cell + name_cell + '</w:tr>'
    else:
        rows += ('<w:tr>' + _tc(_cp(""), w=1900, vmerge="continue")
                 + _tc(_cp(DEFAULT_ORG, align="center"), w=1900)
                 + _tc(_cp(""), w=5400) + '</w:tr>')

    # 회의내용 및 협의사항
    rows += '<w:tr>' + _tc(_cp("회의내용 및 협의사항", bold=True, align="center"), gridspan=3, shade=SHADE) + '</w:tr>'
    body_paras = "".join(_cp(p, after=60) for p in content if str(p).strip()) or _cp("")
    rows += '<w:tr>' + _tc(body_paras, gridspan=3, valign="top") + '</w:tr>'

    borders = "".join(
        '<w:%s w:val="single" w:sz="4" w:space="0" w:color="333333"/>' % e
        for e in ["top", "left", "bottom", "right", "insideH", "insideV"])
    tbl = ('<w:tbl><w:tblPr><w:tblW w:w="9200" w:type="dxa"/><w:jc w:val="center"/>'
           '<w:tblLayout w:type="fixed"/><w:tblBorders>'
           + borders + '</w:tblBorders></w:tblPr>'
           + '<w:tblGrid><w:gridCol w:w="1900"/><w:gridCol w:w="1900"/><w:gridCol w:w="5400"/></w:tblGrid>'
           + rows + '</w:tbl>')

    # 회의록 위쪽 보완요청 표시 (문제 있으면 빨간색, 없으면 회색)
    note_text = ("[보완요청] " + supplement) if has_issue else "[보완사항 없음]"
    note_color = "C00000" if has_issue else "808080"
    body = _para(note_text, bold=has_issue, size=20, color=note_color, align="left", after=120)
    body += _para("회 의 록", bold=True, size=36, align="center", after=200)
    body += tbl
    body += _para("", after=0)

    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1418" '
            'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body>' + body + sect + '</w:body></w:document>')

    # 한글(HWP)에서도 안전하게 열리도록 styles.xml 과 관계 파일을 포함한다.
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:docDefaults><w:rPrDefault><w:rPr>'
              '<w:rFonts w:ascii="%s" w:eastAsia="%s" w:hAnsi="%s" w:cs="%s"/>'
              '<w:sz w:val="22"/><w:szCs w:val="22"/>'
              '</w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr>'
              '<w:spacing w:after="0" w:line="264" w:lineRule="auto"/>'
              '</w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
              '<w:name w:val="Normal"/><w:qFormat/></w:style>'
              '</w:styles>' % (FONT, FONT, FONT, FONT))

    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                     '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                '</Relationships>')

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
