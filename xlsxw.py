"""Writes the task tracker as an .xlsx in the layout of the original workbook (standard library only)."""
import datetime
import io
import zipfile
from xml.sax.saxutils import escape

from .xlsx import col_index  # noqa: F401

HEAD = ["TASK", "COMMENT", "ASSIGNMENT STATUS", "Owner", "DEADLINE", "Revised Timelines", "Completion Status", "EMAIL LINK", "\u23f1\ufe0f DAYS REMAINING"]
WIDTH = [40, 50, 30, 24, 16, 18, 22, 34, 20]
STATUSES = ["Ongoing", "Under Review", "Submitted", "Completed", "Pending", "On Hold", "Cancelled", "Proposal Sent", "Under Template Alignment", "Sent to Ropa for Review", "Submitted for Management Comments", "Awaiting Date Confirmation"]
ICON = {"Completed": "\u2705 Completed", "Overdue": "\U0001f534 Overdue", "Due Soon": "\U0001f7e0 Due Soon", "On Track": "\U0001f7e2 On Track", "Rescheduled": "\U0001f4c5 Rescheduled", "Cancelled": "\u26d4 Cancelled", "On Hold": "\u23f8\ufe0f On Hold", "": ""}


def col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def serial(iso):
    return (datetime.date.fromisoformat(iso) - datetime.date(1899, 12, 30)).days if iso else None


# style ids (cellXfs order in STYLES below)
S_TITLE, S_LBL, S_T_TOTAL, S_T_OVER, S_T_TODAY, S_T_SOON, S_T_DONE, S_T_TRACK, S_HEAD, S_TXT, S_DATE, S_CENTER, S_LINK = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
FILLS = ["none", "gray125", "E8F4FD", "F2F2F2", "4472C4", "CC0000", "ED7D31", "FFC000", "00802B", "00A651", "1F4E79"]


def fill(i):
    return '<fill><patternFill patternType="%s"/></fill>' % FILLS[i] if i < 2 else '<fill><patternFill patternType="solid"><fgColor rgb="FF%s"/><bgColor indexed="64"/></patternFill></fill>' % FILLS[i]


def font(sz=11, bold=False, color="000000", underline=False):
    return '<font>%s%s<sz val="%s"/><color rgb="FF%s"/><name val="Calibri"/><family val="2"/></font>' % ("<b/>" if bold else "", "<u/>" if underline else "", sz, color)


FONTS = [font(), font(18, True, "1F4E79"), font(10, True), font(20, True, "FFFFFF"), font(20, True, "000000"), font(14, True, "FFFFFF"), font(11, False, "0563C1", True), font(11, True)]
BORDER = '<border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right><top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom><diagonal/></border>'


def xf(font_i=0, fill_i=0, border=0, align="", numfmt=0):
    return '<xf numFmtId="%d" fontId="%d" fillId="%d" borderId="%d" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1" applyNumberFormat="1">%s</xf>' % (numfmt, font_i, fill_i, border, align)


CEN = '<alignment horizontal="center" vertical="center" wrapText="1"/>'
WRAP = '<alignment vertical="center" wrapText="1"/>'
STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="dd\\ mmm\\ yyyy"/></numFmts>'
          '<fonts count="%d">%s</fonts><fills count="%d">%s</fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>%s</borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="14">%s</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
          '<dxfs count="5">%s</dxfs></styleSheet>') % (len(FONTS), "".join(FONTS), len(FILLS), "".join(fill(i) for i in range(len(FILLS))), BORDER,
    "".join([xf(), xf(1, 2, 0, '<alignment vertical="center"/>'), xf(2, 3, 1, CEN), xf(3, 4, 1, CEN), xf(3, 5, 1, CEN), xf(3, 6, 1, CEN), xf(4, 7, 1, CEN), xf(3, 8, 1, CEN), xf(3, 9, 1, CEN),
                  xf(5, 10, 1, CEN), xf(0, 0, 1, WRAP), xf(0, 0, 1, CEN, 164), xf(0, 0, 1, CEN), xf(6, 0, 1, WRAP)]),
    "".join('<dxf><font><b/><color rgb="FF%s"/></font><fill><patternFill patternType="solid"><fgColor rgb="FF%s"/><bgColor rgb="FF%s"/></patternFill></fill></dxf>' % (f, b, b) for f, b in [("FFFFFF", "CC0000"), ("000000", "FFC000"), ("FFFFFF", "00802B"), ("FFFFFF", "00A651"), ("FFFFFF", "7030A0")]))


def build(tasks, today):
    """tasks: list of dicts (title, comment, assignment, owner, deadline, revised, status, email_label, email_url, days). Returns .xlsx bytes."""
    n = len(tasks)
    first, last = 7, max(7 + n - 1, 93)
    rows = {}

    def put(r, c, v=None, s=0, f=None, t=None):
        rows.setdefault(r, []).append((c, v, s, f, t))
    put(1, 0, "\U0001f4ca TASK TRACKER DASHBOARD", S_TITLE)
    for c in range(1, 9):
        put(1, c, None, S_TITLE)
    labels = ["\U0001f4cb TOTAL TASKS", "STATUS", "\U0001f534 OVERDUE", "\U0001f4c5 DUE TODAY", "\U0001f7e0 DUE SOON", "\u2705 COMPLETED", "\U0001f7e2 ON TRACK"]
    for i, l in enumerate(labels):
        put(3, i, l, S_LBL)
    rng = lambda c: "%s%d:%s%d" % (c, first, c, last)
    cnt = lambda key: sum(1 for t in tasks if t["status"] == key)
    tiles = [(S_T_TOTAL, 'COUNTA(%s)' % rng("A"), n), (S_LBL, None, None), (S_T_OVER, 'COUNTIF(%s,"*Overdue*")' % rng("G"), cnt("Overdue")), (S_T_TODAY, 'SUMPRODUCT((%s=TODAY())*1)' % rng("E"), sum(1 for t in tasks if t.get("effective") == today and t["status"] in ("Overdue", "Due Soon", "On Track", "Rescheduled"))),
             (S_T_SOON, 'COUNTIF(%s,"*Due Soon*")' % rng("G"), cnt("Due Soon")), (S_T_DONE, 'COUNTIF(%s,"*Completed*")' % rng("G"), cnt("Completed")), (S_T_TRACK, 'COUNTIF(%s,"*On Track*")+COUNTIF(%s,"*Rescheduled*")' % (rng("G"), rng("G")), cnt("On Track") + cnt("Rescheduled"))]
    for i, (s, f, v) in enumerate(tiles):
        put(4, i, v, s, f)
    for i, h in enumerate(HEAD):
        put(6, i, h, S_HEAD)
    for k in range(first, last + 1):
        t = tasks[k - first] if k - first < n else None
        r = k
        put(r, 0, t["title"] if t else None, S_TXT)
        put(r, 1, t["comment"] if t else None, S_TXT)
        put(r, 2, t["assignment"] if t else None, S_CENTER)
        put(r, 3, t["owner"] if t else None, S_CENTER)
        put(r, 4, serial(t["deadline"]) if t else None, S_DATE)
        put(r, 5, serial(t["revised"]) if t else None, S_DATE)
        gf = 'IF(A%d="","",IF(OR(C%d="Submitted",C%d="Completed"),"\u2705 Completed",IF(C%d="Cancelled","\u26d4 Cancelled",IF(C%d="On Hold","\u23f8\ufe0f On Hold",IF(AND(F%d<>"",F%d>=TODAY()),"\U0001f4c5 Rescheduled",IF(F%d<>"",IF(F%d<TODAY(),"\U0001f534 Overdue",""),IF(E%d="","",IF(E%d<TODAY(),"\U0001f534 Overdue",IF(E%d<=TODAY()+3,"\U0001f7e0 Due Soon","\U0001f7e2 On Track")))))))))' % ((r,) * 3 + (r,) * 2 + (r,) * 2 + (r,) * 2 + (r,) * 3)
        put(r, 6, ICON.get(t["status"], t["status"]) if t else "", S_CENTER, gf, "str")
        put(r, 7, (t["email_label"] or t["email_url"]) if t and (t["email_label"] or t["email_url"]) else None, S_LINK)
        put(r, 8, t["days"] if t and t["days"] is not None else ("" if t else ""), S_CENTER, 'IF(A%d="","",IF(F%d<>"",F%d-TODAY(),IF(E%d="","",E%d-TODAY())))' % ((r,) * 5), None)
    sd = []
    for r in sorted(rows):
        cells = []
        for c, v, s, f, t in sorted(rows[r], key=lambda x: x[0]):
            ref = "%s%d" % (col(c), r)
            fx = "<f>%s</f>" % escape(f) if f else ""
            if v is None or v == "":
                if f:
                    cells.append('<c r="%s" s="%d" t="str">%s<v></v></c>' % (ref, s, fx))
                else:
                    cells.append('<c r="%s" s="%d"/>' % (ref, s))
            elif isinstance(v, (int, float)):
                cells.append('<c r="%s" s="%d">%s<v>%s</v></c>' % (ref, s, fx, v))
            elif f:
                cells.append('<c r="%s" s="%d" t="str">%s<v>%s</v></c>' % (ref, s, fx, escape(str(v))))
            else:
                cells.append('<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, s, escape(str(v))))
        ht = ' ht="38" customHeight="1"' if r == 1 else ' ht="24" customHeight="1"' if r in (3, 6) else ' ht="40" customHeight="1"' if r == 4 else ""
        sd.append('<row r="%d"%s>%s</row>' % (r, ht, "".join(cells)))
    links = "".join('<hyperlink ref="H%d" r:id="rId%d"/>' % (7 + i, i + 1) for i, t in enumerate(tasks) if t["email_url"])
    rel_ids = [(7 + i, t["email_url"]) for i, t in enumerate(tasks) if t["email_url"]]
    cf = "".join('<cfRule type="containsText" dxfId="%d" priority="%d" operator="containsText" text="%s"><formula>NOT(ISERROR(SEARCH("%s",G%d)))</formula></cfRule>' % (i, i + 1, k, k, first) for i, k in enumerate(["Overdue", "Due Soon", "Completed", "On Track", "Rescheduled"]))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
             '<sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="6" topLeftCell="A7" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="18"/>'
             '<cols>%s</cols><sheetData>%s</sheetData><autoFilter ref="A6:I%d"/><mergeCells count="1"><mergeCell ref="A1:I1"/></mergeCells>'
             '<conditionalFormatting sqref="G%d:G%d">%s</conditionalFormatting>'
             '<dataValidations count="1"><dataValidation type="list" allowBlank="1" showInputMessage="1" showErrorMessage="1" sqref="C%d:C%d"><formula1>"%s"</formula1></dataValidation></dataValidations>%s</worksheet>') % (
        "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, w) for i, w in enumerate(WIDTH)), "".join(sd), last, first, last, cf, first, last, ",".join(STATUSES),
        ("<hyperlinks>%s</hyperlinks>" % links) if links else "")
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets><sheet name="TRACKER" sheetId="1" r:id="rId1"/></sheets><definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">TRACKER!$A$6:$I$%d</definedName></definedNames><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>') % last
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", STYLES)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        if rel_ids:
            z.writestr("xl/worksheets/_rels/sheet1.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
                '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="%s" TargetMode="External"/>' % (i + 1, escape(u, {'"': "&quot;"})) for i, (_, u) in enumerate(rel_ids)) + "</Relationships>")
    return buf.getvalue()
