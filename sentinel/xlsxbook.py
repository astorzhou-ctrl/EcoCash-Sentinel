"""Writes real .xlsx workbooks with several sheets, using only the standard library. Styles: 0 normal, 1 header, 2 date, 3 title, 4 group band, 5 good, 6 bad, 7 wrapped, 8 note."""
import datetime
import io
import zipfile
from xml.sax.saxutils import escape

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="6"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
<font><b/><sz val="16"/><color rgb="FF0B1F3A"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FF0B1F3A"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FF146C2E"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFB3261E"/><name val="Calibri"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF16345E"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE8EEF8"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="9"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right"/></xf><xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="3" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/><xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="0" fontId="5" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>"""


def col(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet(rows, widths, drawing=False):
    out = []
    for ri, row in enumerate(rows, 1):
        cells = []
        for ci, cell in enumerate(row):
            style = 0
            if isinstance(cell, tuple):
                if cell[0] == "date":
                    if cell[1]:
                        n = (datetime.date.fromisoformat(str(cell[1])[:10]) - datetime.date(1899, 12, 30)).days
                        cells.append('<c r="%s%d" s="2"><v>%d</v></c>' % (col(ci), ri, n))
                    continue
                cell, style = cell
            if cell is None or cell == "":
                if style:
                    cells.append('<c r="%s%d" s="%d"/>' % (col(ci), ri, style))
                continue
            if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                cells.append('<c r="%s%d" s="%d"><v>%s</v></c>' % (col(ci), ri, style, repr(cell)))
            else:
                cells.append('<c r="%s%d" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (col(ci), ri, style, escape(str(cell))))
        out.append('<row r="%d">%s</row>' % (ri, "".join(cells)))
    cols = "<cols>" + "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, w) for i, w in enumerate(widths)) + "</cols>" if widths else ""
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">%s<sheetData>%s</sheetData>%s</worksheet>' % (cols, "".join(out), '<drawing r:id="rId1"/>' if drawing else "")


def write(sheets):
    """sheets: list of (name, rows, widths). A cell is a value, (value, style) or ('date', 'YYYY-MM-DD')."""
    buf = io.BytesIO()
    sheets = [tuple(s) + (() if len(s) > 3 else ([],)) for s in sheets]
    n = len(sheets)
    chart_no, extra_ct = 0, ""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1) for i in range(n)) + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(name[:31]), i + 1, i + 1) for i, (name, _, _, _) in enumerate(sheets)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(n))
                   + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>' % (n + 1))
        z.writestr("xl/styles.xml", STYLES)
        for i, (_, rows, widths, charts) in enumerate(sheets):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), _sheet(rows, widths, bool(charts)))
            if charts:
                anchors, drels = [], []
                for k, ch in enumerate(charts, 1):
                    chart_no += 1
                    z.writestr("xl/charts/chart%d.xml" % chart_no, ch["xml"])
                    extra_ct += '<Override PartName="/xl/charts/chart%d.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>' % chart_no
                    drels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart%d.xml"/>' % (k, chart_no))
                    anchors.append('<xdr:oneCellAnchor><xdr:from><xdr:col>%d</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>%d</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:ext cx="%d" cy="%d"/><xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="%d" name="Chart %d"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="rId%d"/></a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:oneCellAnchor>' % (ch["col"], ch["row"], ch["cx"], ch["cy"], k + 1, k, k))
                z.writestr("xl/drawings/drawing%d.xml" % (i + 1), '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">%s</xdr:wsDr>' % "".join(anchors))
                z.writestr("xl/drawings/_rels/drawing%d.xml.rels" % (i + 1), '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(drels))
                z.writestr("xl/worksheets/_rels/sheet%d.xml.rels" % (i + 1), '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing%d.xml"/></Relationships>' % (i + 1))
                extra_ct += '<Override PartName="/xl/drawings/drawing%d.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>' % (i + 1)
        ct = z.getinfo("[Content_Types].xml")
    # content types are written first, so rewrite the archive with the final list
    data = buf.getvalue()
    if extra_ct:
        src = zipfile.ZipFile(io.BytesIO(data)); out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z2:
            for item in src.infolist():
                body = src.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    body = body.decode("utf-8").replace("</Types>", extra_ct + "</Types>").encode("utf-8")
                z2.writestr(item.filename, body)
        data = out.getvalue()
    return data
