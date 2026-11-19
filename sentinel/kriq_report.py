"""KRI report format, chart editing and integrity checks (Step 24).

* Chart headings and chart types of the Power BI pages can be edited (and the best type is suggested); the edits are stored once and used by the screen and the PowerPoint.
* A report template (a .pptx the Risk Office already uses) can be uploaded: Sentinel reads its colours, font, logo, slide size and slide titles and adopts them as the KRI report format.
* Before a report goes out, the figures are checked (missing, unparsed, suspicious, differing between versions) and the checks travel with the report, so what is reported is traceable."""
import base64
import io
import json
import re
import threading
import zipfile
from xml.etree import ElementTree as ET

from . import core, kriq_pages as PG, kriq_parse as K
from .api import router, need, audit
from .kriq import build, narrative, get_setting, put_setting, _perm, _rep, SRC, INHERENT, APPETITE
from .web import HTTPError, Response

LOCK = threading.Lock()
NSA = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NSP = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
NSR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
DEFAULT = {"name": "EcoCash standard", "title": "KEY RISK INDICATORS", "org": "ECOCASH PVT LTD", "footer": "", "primary": "0E4C6E", "blue": "1F5FA6", "accent": "E4202E", "font": "Calibri", "logo_ratio": 43 / 236, "sections": []}
FIXED = [("trend", "KRI performance against target by quarter"), ("exec", "Executive Overview"), ("move", "Residual risk rating movement"), ("univ", "Indicator Universe")]
TAIL = [("resid", "Residual risk by quarter"), ("detail", "KRI detail by risk"), ("findings", "What the figures tell us"), ("watch", "Watch list: persistent breaches"), ("restated", "Figures that differ between versions of a report"),
        ("method", "Method and data sources"), ("checks", "Report integrity checks")]
KEYS = {"exec": ["executive", "overview", "key messages"], "move": ["movement", "residual risk rating", "rating movement"], "univ": ["indicator universe", "universe", "attainment", "scorecard"], "trend": ["against target", "kri performance", "kri status"],
        "r01": ["business performance"], "r03": ["operating expense", "economic"], "r02": ["competition", "strategic"], "r05": ["compliance", "regulatory"], "r07": ["cyber", "fraud"], "r08": ["bcm", "technology", "continuity"],
        "r10": ["people", "customer"], "r12": ["credit", "third"], "b01": ["trust risk", "board trust", "trust fund"], "mon": ["monetary"], "x1": ["additional kri"], "findings": ["findings", "commentary", "tells us", "key message"],
        "watch": ["watch", "persistent"], "restated": ["differ", "restated", "versions"], "method": ["method", "sources", "basis of"], "checks": ["integrity", "data quality", "checks"], "resid": ["residual risk by quarter"], "detail": ["detail"]}


# ------------------------------------------------------------------ chart headings and types
@router.route("PUT", "/api/kriq/charts")
def chart_edit(req):
    c = _perm(req, "edit")
    b = json.loads(req.body() or b"{}")
    page, idx = str(b.get("page") or ""), b.get("idx")
    if not re.match(r"^[a-z0-9]+$", page) or not isinstance(idx, int) or idx < 0 or idx > 11:
        raise HTTPError(400, "validation", "Choose the chart to edit.")
    typ = b.get("type")
    if typ not in (None, "") and typ not in PG.TYPE_IDS:
        raise HTTPError(400, "validation", "Choose one of: " + ", ".join(PG.TYPE_IDS) + ".")
    ov = get_setting(req.db, "kriq_charts", {}); cur = ov.get("%s:%d" % (page, idx), {})
    for k, mx in (("title", 140), ("sub", 240)):
        if k in b:
            v = re.sub(r"\s+", " ", str(b.get(k) or "")).strip()
            if len(v) > mx:
                raise HTTPError(400, "validation", "Keep the %s under %d characters." % ("heading" if k == "title" else "sub-heading", mx))
            cur[k] = v
    if "type" in b:
        cur["type"] = typ or ""
    cur = {k: v for k, v in cur.items() if v}
    if cur:
        ov["%s:%d" % (page, idx)] = cur
    else:
        ov.pop("%s:%d" % (page, idx), None)
    put_setting(req.db, "kriq_charts", ov)
    audit(req.db, "kriq.chart_edit", c.user, "kri_monitor", "Edited chart %s #%d: %s" % (page, idx + 1, ", ".join("%s=%s" % kv for kv in cur.items()) or "reset"), req.ip)
    return {"ok": True, "edit": cur}


@router.route("DELETE", "/api/kriq/charts")
def chart_reset(req):
    c = _perm(req, "edit")
    ov = get_setting(req.db, "kriq_charts", {})
    if req.query.get("all") == "1":
        n = len(ov); ov = {}
    else:
        n = 1 if ov.pop("%s:%s" % (req.query.get("page", ""), req.query.get("idx", "")), None) else 0
    put_setting(req.db, "kriq_charts", ov)
    audit(req.db, "kriq.chart_reset", c.user, "kri_monitor", "Reset %d chart edit(s)" % n, req.ip)
    return {"reset": n}


# ------------------------------------------------------------------ integrity checks
def checks(d):
    """What a careful reviewer would check before the report goes out. 'error' = the report is internally inconsistent; 'warn' = look at it; 'info' = for the record."""
    items = []; q = d["to"]; ql = PG.ql
    kr = [(rk, r) for rk in d["risks"] for r in rk["kris"]]
    add = lambda lv, kind, text, kri=None: items.append({"level": lv, "kind": kind, "text": text, "kri": kri})
    for rk, r in kr:
        if q not in r["q"]:
            add("warn", "missing", "%s (%s) has no %s figure." % (r["name"], rk["name"], ql(q)), r["id"])
    for rk, r in kr:
        for x in d["quarters"]:
            c = r["q"].get(x)
            if not c:
                continue
            if c["value"] is None and c["raw"] and not re.match(r"^\s*[<>]?\s*\d+\s*(hr|hrs|hours?)\s*$", c["raw"], re.I) and c["status"] == "info" and not re.search(r"[a-z]{3,}", c["raw"], re.I):
                add("warn", "unparsed", "%s, %s: \"%s\" could not be read as a number, so it is shown but not judged." % (r["name"], ql(x), c["raw"]), r["id"])
            if r["unit"] == "%" and c["value"] is not None and (c["value"] < 0 or c["value"] > 100) and not re.search(r"variance|growth|inflation|margin", r["name"], re.I):
                add("warn", "range", "%s, %s: %s is outside 0 to 100%% for a percentage KRI. Check the figure." % (r["name"], ql(x), c["raw"]), r["id"])
            if c["prev"] and K.norm(c["prev"]) != K.norm(c["raw"]):
                add("info", "versions", "%s, %s: %s (%s) replaced %s (%s). Confirm which is correct." % (r["name"], ql(x), c["raw"], c["source"] or "later report", c["prev"], c["prev_source"] or "earlier report"), r["id"])
        nums = [(x, r["q"][x]["value"]) for x in d["quarters"] if x in r["q"] and r["q"][x]["value"] is not None]
        if len(nums) >= 2 and nums[-2][1]:
            ch = abs(nums[-1][1] - nums[-2][1]) / abs(nums[-2][1]) * 100
            if ch >= 200:
                add("warn", "jump", "%s moved %.0f%% between %s and %s (%s to %s). Confirm the figure and the unit." % (r["name"], ch, ql(nums[-2][0]), ql(nums[-1][0]), r["q"][nums[-2][0]]["text"], r["q"][nums[-1][0]]["text"]), r["id"])
        tg = {r["q"][x]["target"] for x in d["quarters"] if x in r["q"] and r["q"][x]["target"]}
        if len({K.norm(t) for t in tg}) > 1:
            add("info", "target", "%s: the target differs between quarters (%s)." % (r["name"], ", ".join(sorted(tg))), r["id"])
    noT = [r["name"] for rk, r in kr if r["q"].get(q) and r["q"][q]["status"] == "info"]
    if noT:
        add("info", "no_target", "%d KRIs have no target or cannot be compared with one in %s, so they are shown but not judged: %s." % (len(noT), ql(q), "; ".join(noT[:12]) + (" and %d more" % (len(noT) - 12) if len(noT) > 12 else "")))
    for rk in d["risks"]:
        if rk["kris"] and rk["residual"].get(q) is None:
            add("warn", "residual", "%s has no residual rating for %s." % (rk["name"], ql(q)))
    cur = d["trend"][-1] if d["trend"] else None
    if cur and cur["green"] + cur["amber"] + cur["red"] + cur["info"] != cur["total"]:
        add("error", "reconcile", "The status counts for %s do not add up to the KRIs reported." % ql(q))
    c = {k: sum(1 for i in items if i["level"] == k) for k in ("error", "warn", "info")}
    return {"quarter": q, "items": items, "counts": c, "ok": c["error"] == 0, "generated": core.now(),
            "reconciliation": ("%d KRIs reported for %s = %d on target + %d near target + %d off target + %d without a target." % (cur["total"], ql(q), cur["green"], cur["amber"], cur["red"], cur["info"])) if cur else ""}


@router.route("GET", "/api/kriq/checks")
def checks_route(req):
    d, n = _rep(req)
    if d["empty"]:
        return {"items": [], "counts": {"error": 0, "warn": 0, "info": 0}, "ok": True}
    return checks(d)


# ------------------------------------------------------------------ the report format and the template
def _sections(d, saved):
    """The sections in the saved order, new ones appended: [{id, title, default, enabled}]."""
    pgs = PG.pages(d) if not d["empty"] else []
    base = FIXED + [(p["id"], p["title"]) for p in pgs] + TAIL
    names = dict(base); out, seen = [], set()
    for s in saved or []:
        if s.get("id") in names and s["id"] not in seen:
            out.append({"id": s["id"], "title": s.get("title") or names[s["id"]], "default": names[s["id"]], "enabled": bool(s.get("enabled", True))}); seen.add(s["id"])
    for i, t in base:
        if i not in seen:
            out.append({"id": i, "title": t, "default": t, "enabled": True})
    return out


def load_format(db, d):
    f = dict(DEFAULT); f.update(get_setting(db, "kriq_format", {}) or {})
    f["sections"] = _sections(d, f.get("sections"))
    f["has_logo"] = bool(get_setting(db, "kriq_logo", None))
    return f


@router.route("GET", "/api/kriq/format")
def format_get(req):
    c = _perm(req)
    d = build(req.db, req.query.get("from") or None, req.query.get("to") or None)
    return {"format": load_format(req.db, d), "can": {"edit": "edit" in c.perms.get("kri_monitor", set())}}


@router.route("PUT", "/api/kriq/format")
def format_put(req):
    c = _perm(req, "edit")
    b = json.loads(req.body() or b"{}")
    d = build(req.db)
    cur = get_setting(req.db, "kriq_format", {}) or {}
    for k, mx in (("title", 80), ("org", 60), ("footer", 160), ("name", 120)):
        if k in b:
            cur[k] = re.sub(r"\s+", " ", str(b[k] or "")).strip()[:mx]
    for k in ("primary", "blue", "accent"):
        if k in b:
            v = str(b[k] or "").lstrip("#").upper()
            if not re.match(r"^[0-9A-F]{6}$", v):
                raise HTTPError(400, "validation", "Colours are six hex digits, for example 0E4C6E.")
            cur[k] = v
    if "font" in b:
        cur["font"] = re.sub(r"[^A-Za-z0-9 \-]", "", str(b["font"] or ""))[:40] or "Calibri"
    if "sections" in b:
        cur["sections"] = [{"id": str(s.get("id")), "title": re.sub(r"\s+", " ", str(s.get("title") or "")).strip()[:120], "enabled": bool(s.get("enabled", True))} for s in b["sections"] if isinstance(s, dict)]
        if not any(s["enabled"] for s in cur["sections"]):
            raise HTTPError(400, "validation", "Keep at least one section in the report.")
    put_setting(req.db, "kriq_format", cur)
    audit(req.db, "kriq.format", c.user, "kri_monitor", "Changed the KRI report format", req.ip)
    return {"format": load_format(req.db, d)}


@router.route("DELETE", "/api/kriq/format")
def format_reset(req):
    c = _perm(req, "edit")
    req.db.execute("DELETE FROM settings WHERE key IN ('kriq_format','kriq_logo')")
    audit(req.db, "kriq.format", c.user, "kri_monitor", "Reset the KRI report format to the EcoCash standard", req.ip)
    return {"ok": True}


def _txt(el):
    return "".join(t.text or "" for t in el.iter(NSA + "t")).strip()


def parse_template(data):
    """What a .pptx template tells us: colours, fonts, logo, slide shape and the titles of its slides in order."""
    if data[:2] != b"PK":
        raise HTTPError(400, "bad_file", "Upload a PowerPoint (.pptx) report as the template.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data)); names = set(z.namelist())
    except zipfile.BadZipFile:
        raise HTTPError(400, "bad_file", "That file could not be opened as a PowerPoint.")
    if "ppt/presentation.xml" not in names:
        raise HTTPError(400, "bad_file", "That is not a PowerPoint presentation.")
    out = {"colors": {}, "font": None, "logo": None, "ratio": None, "size": None, "titles": [], "warnings": []}
    th = next((n for n in sorted(names) if re.match(r"ppt/theme/theme\d+\.xml$", n)), None)
    if th:
        x = z.read(th).decode("utf8", "ignore")
        for k in ("dk2", "accent1", "accent2"):
            m = re.search(r"<a:%s>\s*<a:srgbClr val=\"([0-9A-Fa-f]{6})\"" % k, x)
            if m:
                out["colors"][k] = m.group(1).upper()
        m = re.search(r"<a:majorFont>\s*<a:latin typeface=\"([^\"]+)\"", x) or re.search(r"<a:minorFont>\s*<a:latin typeface=\"([^\"]+)\"", x)
        out["font"] = m.group(1) if m else None
    pres = ET.fromstring(z.read("ppt/presentation.xml")); sz = pres.find(NSP + "sldSz")
    if sz is not None:
        cx, cy = int(sz.get("cx")), int(sz.get("cy")); out["size"] = [round(cx / 914400, 2), round(cy / 914400, 2)]
        if abs(cx / cy - 16 / 9) > 0.05:
            out["warnings"].append("The template is %.1f x %.1f inches (not 16:9). The report is produced in widescreen 16:9; colours, font, logo and headings are adopted." % (cx / 914400, cy / 914400))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("ppt/_rels/presentation.xml.rels"))}
    for sid in pres.iter(NSP + "sldId"):
        tgt = rels.get(sid.get(NSR + "id"))
        if not tgt:
            continue
        path = "ppt/" + tgt.lstrip("/").replace("ppt/", "") if not tgt.startswith("/") else tgt.lstrip("/")
        if path not in names:
            continue
        root = ET.fromstring(z.read(path)); title = ""
        for sp in root.iter(NSP + "sp"):
            ph = sp.find(".//" + NSP + "ph")
            if ph is not None and ph.get("type") in ("title", "ctrTitle"):
                title = _txt(sp); break
        if not title:
            runs = [(_txt(p_)) for p_ in root.iter(NSA + "p")]
            title = next((t for t in runs if t), "")
        out["titles"].append(re.sub(r"\s+", " ", title)[:120])
    # a logo: the first PNG on a master, layout or slide that is small and wide like a logo
    cands = [n for n in sorted(names) if re.match(r"ppt/(slideMasters|slideLayouts)/_rels/.*\.rels$", n)] + [n for n in sorted(names) if re.match(r"ppt/slides/_rels/.*\.rels$", n)]
    for rn in cands:
        for r in ET.fromstring(z.read(rn)):
            t = r.get("Target") or ""
            if "image" not in (r.get("Type") or "") or not t.lower().endswith(".png"):
                continue
            mp = "ppt/media/" + t.split("/")[-1]
            if mp in names and len(z.read(mp)) < 1500000:
                b = z.read(mp)
                if b[:8] == b"\x89PNG\r\n\x1a\n":
                    w, h = int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
                    if h and 1.5 <= w / h <= 9 and w >= 120:
                        out["logo"], out["ratio"] = b, h / w; break
        if out["logo"]:
            break
    return out


def propose(d, t, name):
    """The report format that follows the template: its colours, font and logo, and its slide titles mapped to Sentinel's sections in the template's order."""
    base = {s["id"]: s for s in _sections(d, [])}
    order, used, matched = [], set(), []
    for ti in t["titles"]:
        low = ti.lower(); hit = None
        for sid, keys in KEYS.items():
            if sid in base and sid not in used and any(k in low for k in keys):
                hit = sid; break
        if hit:
            used.add(hit); order.append({"id": hit, "title": ti, "enabled": True}); matched.append({"template": ti, "section": base[hit]["default"], "id": hit})
    unmatched = [ti for ti in t["titles"] if ti and ti not in {m["template"] for m in matched}]
    rest = [{"id": i, "title": s["default"], "enabled": True} for i, s in base.items() if i not in used]
    c = t["colors"]
    return {"name": name, "primary": c.get("dk2") or DEFAULT["primary"], "blue": c.get("accent1") or DEFAULT["blue"], "accent": c.get("accent2") or DEFAULT["accent"], "font": t["font"] or "Calibri", "logo_ratio": t["ratio"] or DEFAULT["logo_ratio"],
            "sections": order + rest, "_matched": matched, "_unmatched": unmatched, "_warnings": t["warnings"], "_has_logo": bool(t["logo"]), "_slides": len(t["titles"])}


@router.route("POST", "/api/kriq/template")
def template_upload(req):
    c = _perm(req, "edit")
    data = req.body()
    if not data or len(data) > 25 * 1024 * 1024:
        raise HTTPError(400, "bad_file", "Choose a PowerPoint template (under 25 MB).")
    from urllib.parse import unquote
    name = unquote(req.headers.get("x-filename", "") or "template.pptx")[:120]
    t = parse_template(data); d = build(req.db)
    p = propose(d, t, name)
    if req.query.get("dry") == "1":
        return {"saved": False, "proposal": p}
    cur = get_setting(req.db, "kriq_format", {}) or {}
    cur.update({k: v for k, v in p.items() if not k.startswith("_")}); put_setting(req.db, "kriq_format", cur)
    if t["logo"]:
        put_setting(req.db, "kriq_logo", base64.b64encode(t["logo"]).decode("ascii"))
    audit(req.db, "kriq.template", c.user, "kri_monitor", "Adopted the report template %s (%d sections matched)" % (name, len(p["_matched"])), req.ip)
    return {"saved": True, "proposal": p, "format": load_format(req.db, d)}


# ------------------------------------------------------------------ the PowerPoint, built from the report format
def _chart_spec(p):
    t = p.get("type") or PG.BASE_TYPE.get(p["kind"], "bars"); G, A, R = "1BA94C", "F5A623", "E4202E"
    ser = [s for s in p["series"] if not (s.get("dashed") and t != "line")]
    out = []
    for s in ser:
        e = {"name": s["name"], "values": s["values"]}
        if s.get("dashed"):
            e.update(dashed=True, color=R)
        elif s.get("key"):
            e["color"] = {"green": G, "amber": A, "red": R}[s["key"]]
        out.append(e)
    typ = {"line": "line", "bars": "column", "hbars": "bar", "stacked": "column", "area": "area", "table": "column"}[t]
    spec = {"type": typ, "title": p["title"][:72], "cats": p["cats"], "series": out, "fmt": "General"}
    if t == "stacked":
        spec["stacked"] = True
    return spec


def build_deck(db, d, n, fmt, W):
    sm = PG.summary(d); t = sm["tiles"]; q = sm["period"]; ql = PG.ql; qs = d["quarters"]
    pgs = PG.decorate(PG.pages(d), get_setting(db, "kriq_charts", {})); byid = {p["id"]: p for p in pgs}
    chk = checks(d)
    batches = [dict(r) for r in db.execute("SELECT ts, username, filename, rows_new, rows_replaced FROM kpi_imports WHERE kind='kriq' AND deleted_at IS NULL ORDER BY id")]
    G, A, Rr = "1BA94C", "F5A623", "E4202E"
    foot = (" " + fmt["footer"]) if fmt.get("footer") else ""
    dk = W.Deck(fmt.get("org") or "ECOCASH PVT LTD")
    lg = get_setting(db, "kriq_logo", None)
    if lg:
        dk.logo = base64.b64decode(lg); dk.logo_ratio = fmt.get("logo_ratio") or dk.logo_ratio
    dk.title_slide(fmt.get("title") or "KEY RISK INDICATORS", "Quarterly KRI report: %s to %s" % (ql(qs[0]), ql(q)))
    rated = sorted([x for x in sm["risks"] if x["current"] is not None], key=lambda x: -x["current"])

    def sec_trend(ti):
        dk.chart_slide(ti, [{"type": "column", "title": "Number of KRIs by status", "cats": [ql(x) for x in qs], "series": [{"name": "On target", "values": [x["green"] for x in d["trend"]], "color": G}, {"name": "Near target", "values": [x["amber"] for x in d["trend"]], "color": A}, {"name": "Off target", "values": [x["red"] for x in d["trend"]], "color": Rr}]},
                             {"type": "line", "title": "Share of KRIs on target (%)", "cats": [ql(x) for x in qs], "series": [{"name": "On target %", "values": [round(100 * x["green"] / max(1, x["green"] + x["amber"] + x["red"])) for x in d["trend"]], "color": "1F5FBF"}], "fmt": "0"}],
                       bullets=[n["headline"]] + n["points"][:2], footer="Source: BoT and Risk Committee reports, stored in Sentinel" + foot)

    def sec_exec(ti):
        cats = {}
        for x in rated:
            cats.setdefault(x["category"], []).append(x["current"])
        dk.chart_slide("%s | %s" % (ti, ql(q)), [
            {"type": "column", "title": "Top 10 risks: residual rating (inherent %d, appetite %d)" % (PG.INH, PG.APP), "cats": [x["code"] + " " + x["name"][:22] for x in rated[:10]], "series": [{"name": "Residual", "values": [x["current"] for x in rated[:10]], "color": "1F5FBF"}], "fmt": "General"},
            {"type": "column", "title": "Average residual vs inherent by risk category", "cats": list(cats), "series": [{"name": "Average residual", "values": [round(sum(v) / len(v), 1) for v in cats.values()], "color": "1F5FBF"}, {"name": "Inherent", "values": [PG.INH] * len(cats), "color": Rr}], "fmt": "General"}],
            bullets=["%d risks rated; average residual %s of %d; %d outside appetite, %d within." % (t["rated"], t["avg_residual"], PG.INH, t["outside"], t["within"]),
                     "Implied control effect %s%%. KRI attainment %s%% (%d assessed: %d met, %d near target, %d breached, %d without a target)." % (t["effect"], t["attainment"], t["assessed"], t["met"], t["near"], t["breached"], t["info"])],
            footer="Attainment = KRIs met plus half of those near target, over KRIs assessed. Source: Sentinel KRI figures" + foot, band=True)

    def sec_move(ti):
        mv = [x for x in sm["risks"] if x["current"] is not None]
        for i in range(0, len(mv), 6):
            _text(dk, W, "%s | %s to %s (%d of %d)" % (ti, ql(qs[0]), ql(q), i // 6 + 1, (len(mv) + 5) // 6),
                  ["%s %s: %s; %s. %s" % (x["code"], x["name"], " > ".join("%g" % x["residual"][y] for y in qs if x["residual"].get(y) is not None), x["appetite"].lower(), x["impact"]) for x in mv[i:i + 6]], foot)

    def sec_univ(ti):
        by = {}
        for x in sm["indicators"]:
            c = by.setdefault(x["category"], {"green": 0, "amber": 0, "red": 0})
            if x["status"] in c:
                c[x["status"]] += 1
        dk.chart_slide("%s | KRIs against target in %s" % (ti, ql(q)), [{"type": "column", "title": "KRIs by status and risk category", "cats": list(by), "series": [{"name": "On target", "values": [v["green"] for v in by.values()], "color": G}, {"name": "Near target", "values": [v["amber"] for v in by.values()], "color": A}, {"name": "Off target", "values": [v["red"] for v in by.values()], "color": Rr}]}],
                       bullets=["%d KRIs assessed: %d met, %d near target, %d breached; %d have no target. Attainment %s%%." % (t["assessed"], t["met"], t["near"], t["breached"], t["info"], t["attainment"])], footer="Green = target met, amber = within 10% of target, red = breached" + foot, band=True)

    def sec_page(pid, ti):
        pg = byid.get(pid)
        if not pg:
            return
        ch = [_chart_spec(p) for p in pg["panels"] if not p.get("empty") and p["series"]]
        if ch:
            dk.chart_slide(ti[:80], ch[:6], footer=(pg["panels"][0].get("sub") or "")[:150] + " Source: Sentinel KRI figures" + foot, band=True)

    def sec_resid(ti):
        rr = [rk for rk in d["risks"] if any(v is not None for v in rk["residual"].values())]
        if rr:
            dk.chart_slide(ti, [{"type": "column", "title": "Residual risk rating", "cats": [PG.short_name(rk)[:26] for rk in rr], "series": [{"name": ql(x), "values": [rk["residual"].get(x) for rk in rr]} for x in qs]}], footer="Residual risk on the GRC scale (inherent %d, appetite %d)" % (PG.INH, PG.APP) + foot)

    def sec_detail(ti):
        for rk in d["risks"]:
            nums = [r for r in rk["kris"] if any(x["value"] is not None for x in r["q"].values())]
            for i in range(0, len(nums), 4):
                charts = []
                for r in nums[i:i + 4]:
                    vs = [r["q"][x]["value"] if x in r["q"] else None for x in qs]
                    mx = max([abs(v) for v in vs if v is not None] + [0]); div, suf = (1e6, " (millions)") if mx >= 1e6 else (1e3, " (thousands)") if mx >= 1e5 else (1, "")
                    if r["unit"] == "mm:ss":
                        div, suf = 60, " (minutes)"
                    tv = None
                    for x in qs:
                        if x in r["q"] and r["q"][x]["target"]:
                            tv = K.parse_target(r["q"][x]["target"], r["name"])[1]
                    ser = [{"name": "Actual", "values": [None if v is None else v / div for v in vs], "color": "1F5FBF"}]
                    if tv is not None and K.parse_target(r["target"], r["name"])[1] is not None:
                        ser.append({"name": "Target", "values": [tv / div] * len(qs), "color": Rr, "dashed": True})
                    charts.append({"type": "line", "title": (r["name"] + (" [%s]" % r["unit"] if r["unit"] == "%" else "") + suf)[:70], "cats": [ql(x) for x in qs], "series": ser, "fmt": "General"})
                red = [r for r in rk["kris"] if r["current"] and r["current"]["status"] == "red"]
                dk.chart_slide(rk["name"], charts, bullets=["%s: %d of %d KRIs on target in %s%s" % (rk["name"], rk["counts"]["green"], rk["counts"]["green"] + rk["counts"]["amber"] + rk["counts"]["red"], ql(q), ("; off target: " + ", ".join("%s %s" % (r["name"], r["current"]["text"]) for r in red[:3])) if red else "")], footer="Dashed red line = target. Source: BoT and Risk Committee reports" + foot)

    def sec_method(ti):
        _text(dk, W, ti, ["Period: %s to %s. The financial year starts on 1 March, so Q3 FY27 is September to November 2026." % (ql(qs[0]), ql(q)),
                          "Status: on target = target met; near target = within 10%% of the target; off target = otherwise; no target = shown but not judged. %d KRIs are tracked across %d risks; %d are reported for %s." % (d["tiles"]["kris"], len(d["risks"]), d["tiles"]["reported"], ql(q)),
                          "KRI attainment = (KRIs met + half of those near target) / KRIs assessed. Residual ratings are whole numbers on the GRC scale: inherent %d, appetite %d, so a rating above %d is outside appetite." % (INHERENT, APPETITE, APPETITE),
                          "Where two reports give different figures for the same quarter, the later report is used and the difference is listed under the figures that differ between versions.",
                          "Sources loaded: " + "; ".join("%s (%s, %s)" % (b["filename"], (b["ts"] or "")[:10], b["username"] or "") for b in batches[-6:]) + ".",
                          "Prepared by Sentinel on %s from the stored figures. Reconciliation: %s" % (core.now()[:16].replace("T", " "), chk["reconciliation"])], foot)

    def sec_checks(ti):
        c = chk["counts"]; lv = {"error": 0, "warn": 1, "info": 2}
        its = sorted(chk["items"], key=lambda i: lv[i["level"]])
        _text(dk, W, "%s: %d to confirm, %d for the record" % (ti, c["error"] + c["warn"], c["info"]), ([("[%s] %s" % (i["level"].upper(), i["text"])) for i in its[:8]] or ["No issues found."]) + ([("%d more checks are listed in Sentinel (KRI Monitor > Report format)." % (len(its) - 8))] if len(its) > 8 else []), foot)

    def sec_text(key, ti, lines):
        if lines:
            _text(dk, W, ti if key != "findings" else "%s: %s" % (ti, ql(q)), lines[:9], foot)

    build = {"trend": lambda ti: sec_trend(ti), "exec": sec_exec, "move": sec_move, "univ": sec_univ, "resid": sec_resid, "detail": sec_detail, "method": sec_method, "checks": sec_checks,
             "findings": lambda ti: sec_text("findings", ti, [n["headline"]] + n["points"]), "watch": lambda ti: sec_text("watch", ti, n["watch"]), "restated": lambda ti: sec_text("restated", ti, n["restated"])}
    for s in fmt["sections"]:
        if not s["enabled"]:
            continue
        if s["id"] in build:
            build[s["id"]](s["title"])
        else:
            sec_page(s["id"], s["title"])
    dk.end_slide()
    return dk


def _text(dk, W, title, lines, foot=""):
    rels = [W.rel(1, "slideLayout", "../slideLayouts/slideLayout1.xml")]
    sh = [W.box(2, "Accent bar", W.emu(0.3), W.emu(0.3), W.emu(0.09), W.emu(0.5), fill=W.BLUE), W.box(3, "Title", W.emu(0.5), W.emu(0.25), W.emu(10.4), W.emu(0.6), W.para(W.run(title[:95], 2000, True, W.BLUE)), anchor="ctr", inset=0.04)]
    lg = dk._logo(4, rels)
    if lg:
        sh.append(lg)
    ps = "".join(W.para(W.run(t[:420], 1300, False, "1A1A1A"), bullet=True, space=600) for t in lines)
    sh.append(W.box(5, "Findings", W.emu(0.5), W.emu(1.1), W.emu(12.3), W.emu(5.3), ps, anchor="t", inset=0.1))
    sh.append(W.box(6, "Footer", W.emu(0.3), W.emu(6.62), W.emu(11.2), W.emu(0.26), W.para(W.run("Prepared by Sentinel from the stored KRI figures. Check against the source reports before use." + foot, 700, False, W.GREY)), anchor="ctr", inset=0.02))
    dk.slides.append((W.slide_xml(sh), rels, []))


@router.route("GET", "/api/kriq/export.pptx")
def export_pptx(req):
    from . import pptx_writer as W
    _perm(req)
    d, n = _rep(req)
    if d["empty"]:
        raise HTTPError(404, "empty", "There are no quarterly KRI figures to export yet.")
    fmt = load_format(req.db, d)
    with LOCK:  # the colours and font are module-level in the writer: set, build, put back
        old = (W.BLUE, W.DARK, W.RED, W.THEME)
        try:
            W.BLUE, W.DARK, W.RED = fmt["blue"], fmt["primary"], fmt["accent"]
            W.THEME = old[3].replace('typeface="Calibri"', 'typeface="%s"' % fmt["font"])
            data = build_deck(req.db, d, n, fmt, W).save()
        finally:
            W.BLUE, W.DARK, W.RED, W.THEME = old
    return Response(data, 200, "application/vnd.openxmlformats-officedocument.presentationml.presentation", [("Content-Disposition", 'attachment; filename="EcoCash_KRI_Report_%s.pptx"' % d["to"])])
