"""Builds the weekly KPI report as a .pptx with the standard library only, in the style of the September 2026 EcoCash deck.
The cover, theme, layouts, icons and artwork come from sentinel/kpi_template.zip (cut from that deck). Each content slide has: the large title and
subtitle, up to four titled charts, a blue footer panel with the commentary and four status tiles, and the source line. Charts are native
PowerPoint charts with an embedded workbook, so 'Edit Data' works. Series can sit on a second value axis (volumes with a success-rate line)."""
import datetime
import io
import os
import re
import zipfile
from xml.sax.saxutils import escape

from . import xlsxbook

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kpi_template.zip")
PALETTE = ["0070C0", "FF0000", "002060", "00B050", "7030A0", "ED7D31", "7F7F7F", "00B0F0"]
NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
CNS = 'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
FONT = '<a:latin typeface="Century Gothic"/>'
CTYPES = ("column", "bar", "line", "area", "pie", "doughnut")
E = 914400
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def emu(v):
    return int(round(v * E))


def _tx(text, sz, bold=False, rot=None):
    return ('<c:tx><c:rich><a:bodyPr%s/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="%d" b="%d">%s</a:defRPr></a:pPr><a:r><a:rPr lang="en-US" sz="%d" b="%d">%s</a:rPr><a:t>%s</a:t></a:r></a:p></c:rich></c:tx>'
            % ((' rot="%d" vert="horz"' % rot) if rot is not None else "", sz, bold, FONT, sz, bold, FONT, escape(text)))


def _txpr(sz, rot=None, bold=False):
    return '<c:txPr><a:bodyPr%s/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="%d" b="%d">%s</a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>' % ((' rot="%d" vert="horz"' % rot) if rot is not None else "", sz, bold, FONT)


def _col(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def default_refs(sheet, n, k, first_row=1):
    """Cell ranges for a table with categories in column A from first_row+1 and series in B, C, ... (header in first_row)."""
    q = "'%s'!" % sheet
    return {"cat": "%s$A$%d:$A$%d" % (q, first_row + 1, first_row + n), "series": [{"name": "%s$%s$%d" % (q, _col(i + 1), first_row), "val": "%s$%s$%d:$%s$%d" % (q, _col(i + 1), first_row + 1, _col(i + 1), first_row + n)} for i in range(k)]}


def chart_xml(title, ctype, cats, series, unit=None, labels=True, refs=None, embed=True, fmt="#,##0.##", sec_fmt="0%"):
    """series: [{name, values, color?, dashed?, axis? (1 or 2), fmt?, nolabels?, legend?}] with None for a gap."""
    n = len(cats)
    refs = refs or default_refs("Sheet1", n, len(series))
    if ctype in ("pie", "doughnut"):  # one series; point_colors gives each slice its colour (None hides it: half a doughnut is a gauge)
        s0 = series[0]; cols = s0.get("point_colors") or [PALETTE[i % len(PALETTE)] for i in range(n)]
        dpt = "".join('<c:dPt><c:idx val="%d"/><c:bubble3D val="0"/><c:spPr>%s<a:ln w="9525"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:ln></c:spPr></c:dPt>' % (i, '<a:noFill/>' if col is None else '<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % col) for i, col in enumerate(cols))
        dl = ('<c:dLbls><c:numFmt formatCode="%s" sourceLinked="0"/><c:spPr><a:noFill/></c:spPr>%s<c:showLegendKey val="0"/><c:showVal val="%d"/><c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="%d"/><c:showBubbleSize val="0"/><c:showLeaderLines val="1"/></c:dLbls>' % (escape(s0.get("fmt") or "0%", {'"': "&quot;"}), _txpr(900, None, True), 0 if s0.get("percent") else 1, 1 if s0.get("percent") else 0)) if labels and not s0.get("nolabels") else ""
        catx = '<c:cat><c:strRef><c:f>%s</c:f><c:strCache><c:ptCount val="%d"/>%s</c:strCache></c:strRef></c:cat>' % (escape(refs["cat"]), n, "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (k, escape(str(c))) for k, c in enumerate(cats)))
        valx = '<c:val><c:numRef><c:f>%s</c:f><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="%d"/>%s</c:numCache></c:numRef></c:val>' % (escape(refs["series"][0]["val"]), n, "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (k, repr(float(v))) for k, v in enumerate(s0["values"]) if v is not None))
        ser0 = '<c:ser><c:idx val="0"/><c:order val="0"/><c:tx><c:strRef><c:f>%s</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>%s</c:v></c:pt></c:strCache></c:strRef></c:tx>%s%s%s%s</c:ser>' % (escape(refs["series"][0]["name"]), escape(s0["name"]), dpt, dl, catx, valx)
        tail = '<c:firstSliceAng val="%d"/>' % s0.get("angle", 0) + ('<c:holeSize val="%d"/>' % s0.get("hole", 60) if ctype == "doughnut" else "")
        plot = '<c:%sChart><c:varyColors val="1"/>%s%s</c:%sChart>' % (ctype, ser0, tail, ctype)
        leg = '' if s0.get("nolegend") else '<c:legend><c:legendPos val="r"/><c:overlay val="0"/>%s</c:legend>' % _txpr(850)
        ttl = '<c:title>%s<c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/>' % _tx(title, 1100, True) if title else '<c:autoTitleDeleted val="1"/>'
        ext = '<c:externalData r:id="rId1"><c:autoUpdate val="0"/></c:externalData>' if embed else ""
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><c:chartSpace %s><c:date1904 val="0"/><c:roundedCorners val="0"/><c:chart>%s<c:plotArea><c:layout/>%s</c:plotArea>%s<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
                '<c:spPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:ln w="9525"><a:solidFill><a:srgbClr val="7F7F7F"/></a:solidFill></a:ln></c:spPr>%s%s</c:chartSpace>' % (CNS, ttl, plot, leg, _txpr(900), ext))
    prim = [i for i, s in enumerate(series) if s.get("axis", 1) == 1]
    sec = [i for i, s in enumerate(series) if s.get("axis", 1) == 2]

    def ser(i, kind, dlpos):
        s = series[i]; color = s.get("color") or PALETTE[i % len(PALETTE)]
        catx = '<c:cat><c:strRef><c:f>%s</c:f><c:strCache><c:ptCount val="%d"/>%s</c:strCache></c:strRef></c:cat>' % (escape(refs["cat"]), n, "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (k, escape(str(c))) for k, c in enumerate(cats)))
        valx = '<c:val><c:numRef><c:f>%s</c:f><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="%d"/>%s</c:numCache></c:numRef></c:val>' % (escape(refs["series"][i]["val"]), n, "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (k, repr(float(v))) for k, v in enumerate(s["values"]) if v is not None))
        name = '<c:tx><c:strRef><c:f>%s</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>%s</c:v></c:pt></c:strCache></c:strRef></c:tx>' % (escape(refs["series"][i]["name"]), escape(s["name"]))
        dl = ""
        if labels and not s.get("nolabels") and kind != "area":
            dl = '<c:dLbls><c:numFmt formatCode="%s" sourceLinked="0"/><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>%s<c:dLblPos val="%s"/><c:showLegendKey val="0"/><c:showVal val="1"/><c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>' % (escape(s.get("fmt") or (sec_fmt if s.get("axis") == 2 else fmt), {'"': "&quot;"}), _txpr(600 if n * len(series) > 30 else 700, None, True), dlpos)
        if kind == "line":
            dash = '<a:prstDash val="dash"/>' if s.get("dashed") else ""
            sp = '<c:spPr><a:ln w="%d" cap="rnd"><a:solidFill><a:srgbClr val="%s"/></a:solidFill>%s<a:round/></a:ln></c:spPr><c:marker><c:symbol val="%s"/><c:size val="5"/><c:spPr><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:ln w="9525"><a:solidFill><a:srgbClr val="%s"/></a:solidFill></a:ln></c:spPr></c:marker>' % (19050 if s.get("thin") else 28575, color, dash, "none" if (s.get("dashed") or s.get("thin")) else "circle", color, color)
            return '<c:ser><c:idx val="%d"/><c:order val="%d"/>%s%s%s%s%s<c:smooth val="0"/></c:ser>' % (i, i, name, sp, dl, catx, valx)
        if kind == "area":
            return '<c:ser><c:idx val="%d"/><c:order val="%d"/>%s<c:spPr><a:solidFill><a:srgbClr val="%s"><a:alpha val="70000"/></a:srgbClr></a:solidFill></c:spPr>%s%s</c:ser>' % (i, i, name, color, catx, valx)
        return '<c:ser><c:idx val="%d"/><c:order val="%d"/>%s<c:spPr><a:solidFill><a:srgbClr val="%s"/></a:solidFill></c:spPr><c:invertIfNegative val="0"/>%s%s%s</c:ser>' % (i, i, name, color, dl, catx, valx)

    ax1 = '<c:axId val="50010"/><c:axId val="50020"/>'
    dlp = "t" if ctype == "line" else "outEnd"
    body = "".join(ser(i, ctype if ctype != "column" and ctype != "bar" else "bar", dlp) for i in prim)
    if ctype == "line":
        plot = '<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>%s<c:marker val="1"/>%s</c:lineChart>' % (body, ax1)
    elif ctype == "area":
        plot = '<c:areaChart><c:grouping val="standard"/><c:varyColors val="0"/>%s%s</c:areaChart>' % (body, ax1)
    else:
        plot = '<c:barChart><c:barDir val="%s"/><c:grouping val="clustered"/><c:varyColors val="0"/>%s<c:gapWidth val="70"/><c:overlap val="-5"/>%s</c:barChart>' % ("bar" if ctype == "bar" else "col", body, ax1)
    if sec:
        plot += '<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>%s<c:marker val="1"/><c:axId val="50030"/><c:axId val="50040"/></c:lineChart>' % "".join(ser(i, "line", "t") for i in sec)
    horizontal = ctype == "bar"
    rot = -2700000 if (n > 10 and not horizontal) else None
    axis_ln = '<c:spPr><a:ln w="9525"><a:solidFill><a:srgbClr val="A6A6A6"/></a:solidFill></a:ln></c:spPr>'
    cat_ax = '<c:catAx><c:axId val="50010"/><c:scaling><c:orientation val="%s"/></c:scaling><c:delete val="0"/><c:axPos val="%s"/><c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="low"/>%s%s<c:crossAx val="50020"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>' % ("maxMin" if horizontal else "minMax", "l" if horizontal else "b", axis_ln, _txpr(800, rot))
    vtitle = "<c:title>%s<c:overlay val=\"0\"/></c:title>" % _tx(unit, 800, False, -5400000 if not horizontal else None) if unit else ""
    val_ax = '<c:valAx><c:axId val="50020"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="%s"/><c:majorGridlines><c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="D9D9D9"/></a:solidFill></a:ln></c:spPr></c:majorGridlines>%s<c:numFmt formatCode="#,##0.##" sourceLinked="0"/><c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>%s%s<c:crossAx val="50010"/><c:crosses val="%s"/><c:crossBetween val="between"/></c:valAx>' % ("b" if horizontal else "l", vtitle, axis_ln, _txpr(800), "max" if horizontal else "autoZero")
    sec_ax = ""
    if sec:
        sec_ax = ('<c:catAx><c:axId val="50030"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="1"/><c:axPos val="b"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="50040"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>'
                  '<c:valAx><c:axId val="50040"/><c:scaling><c:orientation val="minMax"/><c:max val="1"/><c:min val="0"/></c:scaling><c:delete val="0"/><c:axPos val="r"/><c:numFmt formatCode="%s" sourceLinked="0"/><c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>%s%s<c:crossAx val="50030"/><c:crosses val="max"/><c:crossBetween val="between"/></c:valAx>' % (escape(sec_fmt), axis_ln, _txpr(800)))
    legend = '<c:legend><c:legendPos val="b"/><c:overlay val="0"/>%s</c:legend>' % _txpr(750) if len(series) > 1 or (series and series[0].get("legend")) else ""
    ttl = '<c:title>%s<c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/>' % _tx(title, 1100, True) if title else '<c:autoTitleDeleted val="1"/>'
    ext = '<c:externalData r:id="rId1"><c:autoUpdate val="0"/></c:externalData>' if embed else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><c:chartSpace %s><c:date1904 val="0"/><c:roundedCorners val="0"/><c:chart>%s<c:plotArea><c:layout/>%s%s%s%s</c:plotArea>%s<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
            '<c:spPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:ln w="9525"><a:solidFill><a:srgbClr val="7F7F7F"/></a:solidFill></a:ln></c:spPr>%s%s</c:chartSpace>'
            % (CNS, ttl, plot, cat_ax, val_ax, sec_ax, legend, _txpr(900), ext))


def chart_workbook(cats, series):
    rows = [[("", 1)] + [(s["name"], 1) for s in series]]
    for k, c in enumerate(cats):
        rows.append([str(c)] + [s["values"][k] for s in series])
    return xlsxbook.write([("Sheet1", rows, [18] + [18] * len(series))])


# ------------------------------------------------------------------ slides in the September layout
def _tb(i, name, x, y, w, h, text, sz, color, bold=True, algn="l", anchor="t", wrap=True):
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            '<p:txBody><a:bodyPr wrap="%s" lIns="0" tIns="0" rIns="0" bIns="0" rtlCol="0" anchor="%s"><a:normAutofit/></a:bodyPr><a:lstStyle/><a:p><a:pPr algn="%s"/><a:r><a:rPr lang="en-US" sz="%d" b="%d"><a:solidFill><a:srgbClr val="%s"/></a:solidFill>%s</a:rPr><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>'
            % (i, name, emu(x), emu(y), emu(w), emu(h), "square" if wrap else "none", anchor, algn, int(sz * 100), bold, color, FONT, escape(text)))


def _rect(i, name, x, y, w, h, color, geom="rect", adj=None):
    av = '<a:avLst><a:gd name="adj" fmla="val %d"/></a:avLst>' % adj if adj else "<a:avLst/>"
    return '<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="%s">%s</a:prstGeom><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr></p:sp>' % (i, name, emu(x), emu(y), emu(w), emu(h), geom, av, color)


def _line(i, name, x, y, w, h, color, wd):
    return '<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="%d" name="%s"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom><a:ln w="%d"><a:solidFill><a:srgbClr val="%s"/></a:solidFill></a:ln></p:spPr></p:cxnSp>' % (i, name, emu(x), emu(y), emu(w), emu(h), wd, color)


def _pic(i, name, rid, x, y, w, h):
    return '<p:pic><p:nvPicPr><p:cNvPr id="%d" name="%s"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>' % (i, name, rid, emu(x), emu(y), emu(w), emu(h))


def _frame(i, rid, x, y, w, h, name):
    return ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="%d" name="%s"/><p:cNvGraphicFramePr><a:graphicFrameLocks/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="%s"/></a:graphicData></a:graphic></p:graphicFrame>' % (i, escape(name), emu(x), emu(y), emu(w), emu(h), rid))


def _bullets(i, lines):
    n = max(1, min(len(lines), 5))
    sz = 1019 if n <= 4 else 900
    paras = "".join('<a:p><a:pPr marL="0" indent="0"><a:spcBef><a:spcPts val="150"/></a:spcBef></a:pPr><a:r><a:rPr lang="en-US" sz="%d"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>%s</a:rPr><a:t>&#8226;  %s</a:t></a:r></a:p>' % (sz, FONT, escape(t)) for t in lines[:5])
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="Commentary"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            '<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" rtlCol="0" anchor="ctr"><a:normAutofit/></a:bodyPr><a:lstStyle/>%s</p:txBody></p:sp>' % (i, emu(1.24), emu(6.1), emu(6.64), emu(0.95), paras))


def grid(per, n):
    """(x, y, w, h) of each chart and the (x, y) of its heading, for n charts on one slide."""
    L, Rg, W, H = 0.67, 6.72, 5.93, 2.06
    Y1, Y2 = 1.34, 3.86
    if n == 1 or per <= 1:
        return [((L, Y1, 11.98, 4.52), (0.69, 1.0))]
    if per == 2 or n == 2:
        if n == 2 and per >= 4:
            return [((L, Y1, W, 4.52), (0.69, 1.0)), ((Rg, Y1, W, 4.52), (6.73, 1.0))]
        return [((L, Y1, 11.98, H), (0.69, 1.0)), ((L, Y2, 11.98, H), (0.69, 3.52))][:n]
    cells = [((L, Y1, W, H), (0.69, 1.0)), ((Rg, Y1, W, H), (6.73, 1.0)), ((L, Y2, W, H), (0.69, 3.52)), ((Rg, Y2, W, H), (6.73, 3.52))]
    if n == 3:
        cells[2] = ((L, Y2, 11.98, H), (0.69, 3.52))
        return cells[:3]
    return cells[:n]


def long_date(iso):
    d = datetime.date.fromisoformat(iso[:10])
    return "%d %s %d" % (d.day, d.strftime("%B"), d.year)


def build(deck):
    """deck = {as_of, slides: [{title, subtitle, source, per_slide, charts: [{title, ctype, cats, series, unit, labels}], bullets, tiles: [{word, caption}]}]}. Returns .pptx bytes."""
    tpl = zipfile.ZipFile(TEMPLATE)
    parts = {n: tpl.read(n) for n in tpl.namelist() if not n.startswith("tpl/")}
    as_of = deck["as_of"]; d = datetime.date.fromisoformat(as_of[:10])
    overrides, rels_slides, sld_ids, slides = [], [], [], []
    cover = tpl.read("tpl/cover.xml").decode("utf-8")
    cover = cover.replace("<a:t>WEEKLY KPIs REPORT</a:t>", "<a:t>%s</a:t>" % escape(deck.get("cover_title") or "WEEKLY KPIs REPORT"), 1)
    cover = cover.replace("<a:t>SEPTEMBER </a:t>", "<a:t>%s </a:t>" % d.strftime("%B").upper(), 1).replace("<a:t>2026</a:t>", "<a:t>%d</a:t>" % d.year, 1)
    slides.append((cover, tpl.read("tpl/cover.rels").decode("utf-8")))
    chart_no = 0
    for sno, sl in enumerate(deck["slides"], 2):
        sid = iter(range(2, 600))
        rel_media = {"deco": "image12.png", "logo": "image2.emf", "bar": "image3.png", "trend": "image4.png", "note": "image7.png", "t1": "image8.png", "t2": "image9.png", "t3": "image10.png", "t4": "image11.png"}
        rels = ['<Relationship Id="rId1" Type="%s/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>' % R]
        rid_of = {}
        for k, f in rel_media.items():
            rid_of[k] = "rId%d" % (len(rels) + 1)
            rels.append('<Relationship Id="%s" Type="%s/image" Target="../media/%s"/>' % (rid_of[k], R, f))
        sh = [_pic(next(sid), "Decor", rid_of["deco"], 0, 0, 0.38, 1.29)]
        t = sl["title"]
        sh.append(_tb(next(sid), "Title", 0.82, 0.10, 9.55, 0.49, t, min(35, max(18, 35 * 22 / max(len(t), 1))), "040A43", True, "l", "ctr", False))
        sh.append(_tb(next(sid), "Subtitle", 0.84, 0.66, 9.0, 0.19, sl.get("subtitle") or "", 11.5, "004FB5", True))
        sh.append(_pic(next(sid), "EcoCash logo", rid_of["logo"], 10.73, 0.22, 1.7, 0.3))
        sh.append(_rect(next(sid), "Rule", 0.72, 0.94, 11.88, 0.02, "D8E3F1")); sh.append(_rect(next(sid), "Rule accent", 0.72, 0.94, 0.88, 0.04, "F70012"))
        for (x, y, w, h), (hx, hy), ch in zip([g[0] for g in grid(sl.get("per_slide", 4), len(sl["charts"]))], [g[1] for g in grid(sl.get("per_slide", 4), len(sl["charts"]))], sl["charts"]):
            chart_no += 1
            cats, series = ch["cats"], ch["series"]
            parts["ppt/charts/chart%d.xml" % chart_no] = chart_xml(None, ch["ctype"], cats, series, ch.get("unit"), ch.get("labels", True), fmt=ch.get("fmt") or "#,##0.##").encode("utf-8")
            parts["ppt/charts/_rels/chart%d.xml.rels" % chart_no] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/package" Target="../embeddings/Microsoft_Excel_Sheet%d.xlsx"/></Relationships>' % (R, chart_no)).encode()
            parts["ppt/embeddings/Microsoft_Excel_Sheet%d.xlsx" % chart_no] = chart_workbook(cats, series)
            overrides.append('<Override PartName="/ppt/charts/chart%d.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>' % chart_no)
            rid = "rId%d" % (len(rels) + 1)
            rels.append('<Relationship Id="%s" Type="%s/chart" Target="../charts/chart%d.xml"/>' % (rid, R, chart_no))
            sh.append(_pic(next(sid), "Heading icon", rid_of["trend" if ch["ctype"] in ("line", "area") else "bar"], hx, hy, 0.3, 0.3))
            sh.append(_tb(next(sid), "Chart heading", hx + 0.39, hy + 0.06, (11.2 if w > 7 else 5.46), 0.22, ch["title"].upper(), 12.8, "040A43", True, "l", "t", False))
            sh.append(_frame(next(sid), rid, x, y, w, h, "Chart %d" % chart_no))
        sh.append(_rect(next(sid), "Footer panel", 0.35, 6.0, 12.39, 1.13, "004AA8", "roundRect", 8000)); sh.append(_rect(next(sid), "Footer stripe", 0.35, 6.0, 12.39, 0.04, "F70012"))
        sh.append(_pic(next(sid), "Commentary icon", rid_of["note"], 0.48, 6.23, 0.6, 0.6))
        if sl.get("bullets"):
            sh.append(_bullets(next(sid), sl["bullets"]))
        tiles = (sl.get("tiles") or [])[:4]
        if tiles:
            sh.append(_line(next(sid), "Divider", 8.05, 6.13, 0, 0.84, "F70012", 15875))
            for k, tl in enumerate(tiles):
                ix = 8.44 + 1.1 * k
                sh.append(_pic(next(sid), "Tile icon", rid_of["t%d" % (k + 1)], ix, 6.13, 0.35, 0.35))
                sh.append(_tb(next(sid), "Tile word", ix - 0.34, 6.52, 1.04, 0.17, tl.get("word") or "", 10, "FFFFFF", True, "ctr"))
                sh.append(_tb(next(sid), "Tile caption", ix - 0.35, 6.75, 1.06, 0.26, tl.get("caption") or "", 9, "FFFFFF", False, "ctr"))
        sh.append(_line(next(sid), "Footer rule", 0.35, 7.22, 12.38, 0, "D8DDE6", 8255))
        sh.append(_tb(next(sid), "Source", 0.91, 7.26, 3.6, 0.14, "Source: " + (sl.get("source") or "EcoCash Research"), 8.3, "040A43", True, "l", "t", False))
        sh.append(_tb(next(sid), "Footer", 4.7, 7.26, 3.0, 0.14, "ENTERPRISE RISK MANAGEMENT", 8.3, "002060", True, "l", "t", False))
        for k in range(3):
            sh.append('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="Dot"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr></p:sp>' % (next(sid), emu(11.86 + 0.16 * k), emu(7.28), emu(0.08), emu(0.08), ("040A43", "004AA8", "F70012")[k]))
        sh.append(_tb(next(sid), "Page", 12.44, 7.23, 0.32, 0.15, "%02d" % sno, 9, "040A43", False, "r", "t", False))
        xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld %s><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>' % (NS, "".join(sh))
        slides.append((xml, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(rels)))
    slides.append((tpl.read("tpl/thanks.xml").decode("utf-8"), tpl.read("tpl/thanks.rels").decode("utf-8")))
    for k, (xml, rels) in enumerate(slides, 1):
        parts["ppt/slides/slide%d.xml" % k] = xml.encode("utf-8"); parts["ppt/slides/_rels/slide%d.xml.rels" % k] = rels.encode("utf-8")
        overrides.append('<Override PartName="/ppt/slides/slide%d.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' % k)
        rels_slides.append('<Relationship Id="rId%d" Type="%s/slide" Target="slides/slide%d.xml"/>' % (100 + k, R, k)); sld_ids.append('<p:sldId id="%d" r:id="rId%d"/>' % (255 + k, 100 + k))
    parts["ppt/presentation.xml"] = tpl.read("tpl/presentation.xml").decode("utf-8").replace("{{SLDIDS}}", "<p:sldIdLst>%s</p:sldIdLst>" % "".join(sld_ids)).encode("utf-8")
    parts["ppt/_rels/presentation.xml.rels"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s%s</Relationships>' % (tpl.read("tpl/presentation.rels").decode("utf-8"), "".join(rels_slides))).encode("utf-8")
    ct = tpl.read("tpl/content_types.xml").decode("utf-8")
    if 'Extension="xlsx"' not in ct:
        ct = '<Default Extension="xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/>\n' + ct
    parts["[Content_Types].xml"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">%s%s</Types>' % (ct, "".join(overrides))).encode("utf-8")
    parts["_rels/.rels"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/officeDocument" Target="ppt/presentation.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>' % R).encode()
    core = parts.get("docProps/core.xml", b"").decode("utf-8")
    core = re.sub(r"<dc:title>.*?</dc:title>", "<dc:title>EcoCash Weekly KPI Report %s</dc:title>" % escape(long_date(as_of)), core, flags=re.S) if "<dc:title" in core else core
    parts["docProps/core.xml"] = core.encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", parts.pop("[Content_Types].xml"))
        for n, b in parts.items():
            z.writestr(n, b)
    return buf.getvalue()
