"""Writes a real .pptx with native, editable charts using only the standard library (a .pptx is a zip of XML parts).
The look follows the EcoCash weekly KPI deck: blue accent bar and section title, logo top right, charts in bordered tiles, a blue commentary box."""
import io
import os
import zipfile
from xml.sax.saxutils import escape

from . import xlsxbook

IN = 914400
W, H = 12192000, 6858000
BLUE, DARK, RED, GREEN, ORANGE, PURPLE, GREY = "1F5FA6", "0E4C6E", "E4202E", "1BA94C", "F58220", "6B4FBB", "5B6B7D"
PALETTE = ["1F5FBF", "E4202E", "1BA94C", "F58220", "6B4FBB", "00A3B4"]
NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ecocash_logo.png")


def emu(inches):
    return int(inches * IN)


def run(text, sz=1100, bold=False, color="000000", italic=False):
    return '<a:r><a:rPr lang="en-US" sz="%d" b="%d" i="%d" dirty="0"><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:latin typeface="Calibri"/></a:rPr><a:t>%s</a:t></a:r>' % (sz, bold, italic, color, escape(text))


def para(runs, bullet=False, align="l", space=0):
    ppr = '<a:pPr algn="%s"%s>%s%s</a:pPr>' % (align, ' marL="171450" indent="-171450"' if bullet else "", '<a:spcBef><a:spcPts val="%d"/></a:spcBef>' % space if space else "", '<a:buFont typeface="Arial"/><a:buChar char="&#8226;"/>' if bullet else "<a:buNone/>")
    return "<a:p>%s%s</a:p>" % (ppr, runs)


def box(i, name, x, y, cx, cy, paras="", fill=None, line=None, anchor="t", inset=0.06, prst="rect"):
    f = '<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % fill if fill else "<a:noFill/>"
    ln = '<a:ln w="9525"><a:solidFill><a:srgbClr val="%s"/></a:solidFill></a:ln>' % line if line else "<a:ln><a:noFill/></a:ln>"
    body = paras or "<a:p><a:endParaRPr lang=\"en-US\"/></a:p>"
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="%s"><a:avLst/></a:prstGeom>%s%s</p:spPr>'
            '<p:txBody><a:bodyPr wrap="square" lIns="%d" tIns="%d" rIns="%d" bIns="%d" anchor="%s"><a:normAutofit/></a:bodyPr><a:lstStyle/>%s</p:txBody></p:sp>') % (i, escape(name), x, y, cx, cy, prst, f, ln, emu(inset), emu(inset / 2), emu(inset), emu(inset / 2), anchor, body)


def pic(i, name, rid, x, y, cx, cy):
    return ('<p:pic><p:nvPicPr><p:cNvPr id="%d" name="%s"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            '<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>') % (i, escape(name), rid, x, y, cx, cy)


def frame(i, name, rid, x, y, cx, cy):
    return ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="%d" name="%s"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></p:xfrm>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="%s"/></a:graphicData></a:graphic></p:graphicFrame>') % (i, escape(name), x, y, cx, cy, rid)


def slide_xml(shapes):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld %s><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>') % (NS, "".join(shapes))


# ------------------------------------------------------------------ charts
def _cache_str(vals):
    return '<c:strCache><c:ptCount val="%d"/>%s</c:strCache>' % (len(vals), "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (i, escape(str(v))) for i, v in enumerate(vals)))


def _cache_num(vals, fmt):
    return '<c:numCache><c:formatCode>%s</c:formatCode><c:ptCount val="%d"/>%s</c:numCache>' % (escape(fmt), len(vals), "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (i, repr(float(v))) for i, v in enumerate(vals) if v is not None))


def _col(i):
    return xlsxbook.col(i)


def chart_xml(spec):
    """spec: {type: column|bar|line|area, title, cats: [str], series: [{name, values, color, dashed}], fmt}"""
    t, cats, series, fmt = spec["type"], spec["cats"], spec["series"], spec.get("fmt") or "General"
    n = len(cats)
    labels = n * len(series) <= 24 and t in ("column", "bar", "line")
    sers = []
    for k, s in enumerate(series):
        color = s.get("color") or PALETTE[k % len(PALETTE)]
        c = _col(k + 1)
        tx = '<c:tx><c:strRef><c:f>Sheet1!$%s$1</c:f>%s</c:strRef></c:tx>' % (c, _cache_str([s["name"]]))
        cat = '<c:cat><c:strRef><c:f>Sheet1!$A$2:$A$%d</c:f>%s</c:strRef></c:cat>' % (n + 1, _cache_str(cats))
        val = '<c:val><c:numRef><c:f>Sheet1!$%s$2:$%s$%d</c:f>%s</c:numRef></c:val>' % (c, c, n + 1, _cache_num(s["values"], fmt))
        dl = ('<c:dLbls><c:numFmt formatCode="%s" sourceLinked="0"/><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr><c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="700"/></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr><c:showLegendKey val="0"/><c:showVal val="1"/><c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>' % escape(fmt)) if labels and not s.get("dashed") else ""
        if t in ("column", "bar"):
            sers.append('<c:ser><c:idx val="%d"/><c:order val="%d"/>%s<c:spPr><a:solidFill><a:srgbClr val="%s"/></a:solidFill></c:spPr><c:invertIfNegative val="0"/>%s%s%s</c:ser>' % (k, k, tx, color, dl, cat, val))
        elif t == "line":
            ln = '<a:ln w="%d" cap="rnd"><a:solidFill><a:srgbClr val="%s"/></a:solidFill>%s<a:round/></a:ln>' % (19050 if s.get("dashed") else 28575, color, '<a:prstDash val="dash"/>' if s.get("dashed") else "")
            mk = '<c:marker><c:symbol val="none"/></c:marker>' if s.get("dashed") else '<c:marker><c:symbol val="circle"/><c:size val="5"/><c:spPr><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:ln><a:noFill/></a:ln></c:spPr></c:marker>' % color
            sers.append('<c:ser><c:idx val="%d"/><c:order val="%d"/>%s<c:spPr>%s</c:spPr>%s%s%s%s<c:smooth val="0"/></c:ser>' % (k, k, tx, ln, mk, dl, cat, val))
        else:
            sers.append('<c:ser><c:idx val="%d"/><c:order val="%d"/>%s<c:spPr><a:solidFill><a:srgbClr val="%s"><a:alpha val="70000"/></a:srgbClr></a:solidFill></c:spPr>%s%s</c:ser>' % (k, k, tx, color, cat, val))
    ax = '<c:axId val="50010"/><c:axId val="50020"/>'
    if t in ("column", "bar"):
        plot = '<c:barChart><c:barDir val="%s"/><c:grouping val="%s"/><c:varyColors val="0"/>%s<c:gapWidth val="70"/>%s%s</c:barChart>' % ("bar" if t == "bar" else "col", "stacked" if spec.get("stacked") else "clustered", "".join(sers), '<c:overlap val="100"/>' if spec.get("stacked") else "", ax)
    elif t == "line":
        plot = '<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>%s<c:marker val="1"/>%s</c:lineChart>' % ("".join(sers), ax)
    else:
        plot = '<c:areaChart><c:grouping val="standard"/><c:varyColors val="0"/>%s%s</c:areaChart>' % ("".join(sers), ax)
    horiz = t == "bar"
    txpr = '<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="800"><a:solidFill><a:srgbClr val="404040"/></a:solidFill></a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>'
    cat_ax = '<c:catAx><c:axId val="50010"/><c:scaling><c:orientation val="%s"/></c:scaling><c:delete val="0"/><c:axPos val="%s"/><c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="low"/>%s<c:crossAx val="50020"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>' % ("maxMin" if horiz else "minMax", "l" if horiz else "b", txpr)
    val_ax = '<c:valAx><c:axId val="50020"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="%s"/><c:majorGridlines><c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="E1E6EE"/></a:solidFill></a:ln></c:spPr></c:majorGridlines><c:numFmt formatCode="%s" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>%s<c:crossAx val="50010"/><c:crosses val="%s"/><c:crossBetween val="%s"/></c:valAx>' % ("b" if horiz else "l", escape(fmt), txpr, "max" if horiz else "autoZero", "midCat" if t == "area" else "between")
    title = '<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="1100" b="1"/></a:pPr><a:r><a:rPr lang="en-US" sz="1100" b="1"><a:solidFill><a:srgbClr val="1A1A1A"/></a:solidFill></a:rPr><a:t>%s</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>' % escape(spec["title"])
    legend = '<c:legend><c:legendPos val="b"/><c:overlay val="0"/><c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="800"/></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr></c:legend>' if len(series) > 1 else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<c:date1904 val="0"/><c:roundedCorners val="0"/><c:chart>%s<c:autoTitleDeleted val="0"/><c:plotArea><c:layout/>%s%s%s</c:plotArea>%s<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
            '<c:spPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:ln w="9525"><a:solidFill><a:srgbClr val="BFC9D6"/></a:solidFill></a:ln></c:spPr><c:externalData r:id="rId1"><c:autoUpdate val="0"/></c:externalData></c:chartSpace>') % (title, plot, cat_ax, val_ax, legend)


def chart_workbook(spec):
    rows = [[("", 1)] + [(s["name"], 1) for s in spec["series"]]]
    for i, c in enumerate(spec["cats"]):
        rows.append([c] + [s["values"][i] for s in spec["series"]])
    return xlsxbook.write([("Sheet1", rows, [18] + [16] * len(spec["series"]))])


# ------------------------------------------------------------------ fixed parts
THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="EcoCash"><a:themeElements><a:clrScheme name="EcoCash"><a:dk1><a:srgbClr val="000000"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="0E4C6E"/></a:dk2><a:lt2><a:srgbClr val="EEF2F8"/></a:lt2>'
         '<a:accent1><a:srgbClr val="1F5FBF"/></a:accent1><a:accent2><a:srgbClr val="E4202E"/></a:accent2><a:accent3><a:srgbClr val="1BA94C"/></a:accent3><a:accent4><a:srgbClr val="F58220"/></a:accent4><a:accent5><a:srgbClr val="6B4FBB"/></a:accent5><a:accent6><a:srgbClr val="00A3B4"/></a:accent6><a:hlink><a:srgbClr val="1F5FBF"/></a:hlink><a:folHlink><a:srgbClr val="6B4FBB"/></a:folHlink></a:clrScheme>'
         '<a:fontScheme name="EcoCash"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
         '<a:fmtScheme name="Office"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
         '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
GRP = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
MASTER = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster %s><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>%s</p:spTree></p:cSld>'
          '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
          '<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="2000"/></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr><a:defRPr sz="1200"/></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr sz="1200"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>') % (NS, GRP)
LAYOUT = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout %s type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>' % (NS, GRP)
REL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def rel(i, typ, target):
    return '<Relationship Id="rId%d" Type="%s%s" Target="%s"/>' % (i, RT, typ, target)


# ------------------------------------------------------------------ the deck
class Deck:
    def __init__(self, org="ECOCASH PVT LTD"):
        self.slides, self.charts, self.org = [], [], org
        self.logo = open(LOGO, "rb").read() if os.path.exists(LOGO) else None
        self.logo_ratio = 43 / 236

    def _logo(self, sid, rels, x=None, y=None, w=1.35):
        if not self.logo:
            return ""
        rels.append(rel(len(rels) + 1, "image", "../media/logo.png"))
        h = w * self.logo_ratio
        return pic(sid, "EcoCash logo", "rId%d" % len(rels), emu(x if x is not None else 13.333 - w - 0.35), emu(y if y is not None else 0.22), emu(w), emu(h))

    def title_slide(self, title, subtitle):
        rels = [rel(1, "slideLayout", "../slideLayouts/slideLayout1.xml")]
        sh = [box(2, "Blue panel", emu(6.9), 0, W - emu(6.9), H, fill=BLUE), box(3, "Accent", emu(6.9), 0, emu(0.12), H, fill=RED)]
        lg = self._logo(4, rels, 1.2, 2.7, 3.8)
        if lg: sh.append(lg)
        sh.append(box(5, "Organisation", emu(7.4), emu(2.2), emu(5.4), emu(0.7), para(run(self.org, 2800, True, "FFFFFF")), anchor="b"))
        sh.append(box(6, "Title", emu(7.4), emu(2.95), emu(5.4), emu(1.0), para(run(title, 2400, True, "FFFFFF")), anchor="t"))
        sh.append(box(7, "Period", emu(7.4), emu(3.9), emu(5.4), emu(0.6), para(run(subtitle, 1800, False, "DCE8F8")), anchor="t"))
        self.slides.append((slide_xml(sh), rels, []))

    def chart_slide(self, title, charts, bullets=None, footer="", band=False):
        """charts: list of chart specs (1 to 4), laid out like the deck: 1 full, 2 side by side, 3 or 4 in a 2 x 2 grid."""
        rels = [rel(1, "slideLayout", "../slideLayouts/slideLayout1.xml")]
        sh, nid = [], 2
        if band:
            sh.append(box(nid, "Title band", emu(0.3), emu(0.28), emu(10.9), emu(0.5), para(run(title, 1600, True, "FFFFFF")), fill=DARK, anchor="ctr", inset=0.15)); nid += 1
        else:
            sh.append(box(nid, "Accent bar", emu(0.3), emu(0.3), emu(0.09), emu(0.5), fill=BLUE)); nid += 1
            sh.append(box(nid, "Title", emu(0.5), emu(0.25), emu(10.4), emu(0.6), para(run(title, 2000, True, BLUE)), anchor="ctr", inset=0.04)); nid += 1
        lg = self._logo(nid, rels); nid += 1
        if lg: sh.append(lg)
        top, bottom = 0.95, (5.5 if bullets else 6.55)
        n = len(charts); gx, gy = 0.1, 0.1; x0, x1 = 0.3, 13.033
        cells = []
        if n == 1: cells = [(x0, top, x1 - x0, bottom - top)]
        elif n == 2: cells = [(x0, top, (x1 - x0 - gx) / 2, bottom - top), (x0 + (x1 - x0 + gx) / 2, top, (x1 - x0 - gx) / 2, bottom - top)]
        elif n >= 5:
            cw, ch = (x1 - x0 - 2 * gx) / 3, (bottom - top - gy) / 2
            cells = [(x0 + (k % 3) * (cw + gx), top + (k // 3) * (ch + gy), cw, ch) for k in range(6)]
        else:
            cw, ch = (x1 - x0 - gx) / 2, (bottom - top - gy) / 2
            cells = [(x0, top, cw, ch), (x0 + cw + gx, top, cw, ch), (x0, top + ch + gy, cw, ch), (x0 + cw + gx, top + ch + gy, cw, ch)]
            if n == 3: cells[2] = (x0, top + ch + gy, x1 - x0, ch)
        chart_rels = []
        for k, spec in enumerate(charts[:6]):
            self.charts.append(spec); idx = len(self.charts)
            rels.append(rel(len(rels) + 1, "chart", "../charts/chart%d.xml" % idx)); chart_rels.append(idx)
            x, y, cw, ch = cells[k]
            sh.append(frame(nid, spec["title"], "rId%d" % len(rels), emu(x), emu(y), emu(cw), emu(ch))); nid += 1
        if bullets:
            ps = "".join(para(run(b, 1000, False, "FFFFFF"), bullet=True, space=200) for b in bullets[:6])
            sh.append(box(nid, "Commentary", emu(0.3), emu(5.6), emu(12.733), emu(0.98), ps, fill="0070C0", anchor="ctr", inset=0.12)); nid += 1
        sh.append(box(nid, "Footer", emu(0.3), emu(6.62), emu(11.2), emu(0.26), para(run(footer, 700, False, GREY)), anchor="ctr", inset=0.02)); nid += 1
        sh.append(box(nid, "Confidential", emu(11.6), emu(6.62), emu(1.45), emu(0.26), para(run("Confidential", 700, False, GREY), align="r"), anchor="ctr", inset=0.02))
        self.slides.append((slide_xml(sh), rels, chart_rels))

    def end_slide(self, text="THANK YOU"):
        rels = [rel(1, "slideLayout", "../slideLayouts/slideLayout1.xml")]
        sh = [box(2, "Panel", 0, 0, W, H, fill=BLUE), box(3, "Accent", 0, emu(6.9), W, emu(0.12), fill=RED)]
        lg = self._logo(4, rels, 5.4, 2.0, 2.5)
        if lg: sh.append(lg)
        sh.append(box(5, "Thanks", emu(1), emu(3.3), emu(11.333), emu(1.2), para(run(text, 4000, True, "FFFFFF"), align="ctr"), anchor="ctr"))
        self.slides.append((slide_xml(sh), rels, []))

    def save(self):
        buf = io.BytesIO(); n = len(self.slides)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            ct = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>', '<Default Extension="xml" ContentType="application/xml"/>', '<Default Extension="png" ContentType="image/png"/>',
                  '<Default Extension="xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/>', '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
                  '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>', '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
                  '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>']
            ct += ['<Override PartName="/ppt/slides/slide%d.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' % (i + 1) for i in range(n)]
            ct += ['<Override PartName="/ppt/charts/chart%d.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>' % (i + 1) for i in range(len(self.charts))]
            z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">%s</Types>' % "".join(ct))
            z.writestr("_rels/.rels", REL % rel(1, "officeDocument", "ppt/presentation.xml"))
            z.writestr("ppt/presentation.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation %s><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>%s</p:sldIdLst><p:sldSz cx="%d" cy="%d"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>' % (NS, "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, i + 2) for i in range(n)), W, H))
            z.writestr("ppt/_rels/presentation.xml.rels", REL % (rel(1, "slideMaster", "slideMasters/slideMaster1.xml") + "".join(rel(i + 2, "slide", "slides/slide%d.xml" % (i + 1)) for i in range(n))))
            z.writestr("ppt/slideMasters/slideMaster1.xml", MASTER)
            z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", REL % (rel(1, "slideLayout", "../slideLayouts/slideLayout1.xml") + rel(2, "theme", "../theme/theme1.xml")))
            z.writestr("ppt/slideLayouts/slideLayout1.xml", LAYOUT)
            z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", REL % rel(1, "slideMaster", "../slideMasters/slideMaster1.xml"))
            z.writestr("ppt/theme/theme1.xml", THEME)
            if self.logo:
                z.writestr("ppt/media/logo.png", self.logo)
            for i, (xml, rels, _) in enumerate(self.slides):
                z.writestr("ppt/slides/slide%d.xml" % (i + 1), xml)
                z.writestr("ppt/slides/_rels/slide%d.xml.rels" % (i + 1), REL % "".join(rels))
            for i, spec in enumerate(self.charts):
                z.writestr("ppt/charts/chart%d.xml" % (i + 1), chart_xml(spec))
                z.writestr("ppt/charts/_rels/chart%d.xml.rels" % (i + 1), REL % rel(1, "package", "../embeddings/Microsoft_Excel_Sheet%d.xlsx" % (i + 1)))
                z.writestr("ppt/embeddings/Microsoft_Excel_Sheet%d.xlsx" % (i + 1), chart_workbook(spec))
        return buf.getvalue()
