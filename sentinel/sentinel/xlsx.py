"""A small .xlsx reader using only the standard library (an .xlsx file is a zip of XML files)."""
import io
import re
import zipfile
import xml.etree.ElementTree as ET

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def col_index(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read(data):
    """Return {sheet name: [row, row, ...]} where each row is a list of cell values (cached results for formulas)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("This is not a valid .xlsx file.")
    names = set(z.namelist())
    if "xl/workbook.xml" not in names:
        raise ValueError("This is not an Excel (.xlsx) workbook.")
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(M + "si"):
            shared.append("".join(t.text or "" for t in si.iter(M + "t")))
    rels = {}
    for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
        t = rel.get("Target")
        rels[rel.get("Id")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(M + "sheet"):
        path = rels.get(sh.get(R + "id"))
        if not path or path not in names:
            continue
        cells, maxc, maxr = {}, 0, 0
        for c in ET.fromstring(z.read(path)).iter(M + "c"):
            ref = c.get("r")
            if not ref:
                continue
            t, v = c.get("t"), c.find(M + "v")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(M + "t"))
            elif v is None or v.text is None:
                continue
            elif t == "s":
                val = shared[int(v.text)]
            elif t in ("str", "e"):
                val = v.text
            elif t == "b":
                val = v.text == "1"
            else:
                f = float(v.text)
                val = int(f) if f.is_integer() else f
            ci, ri = col_index(ref), int(re.search(r"\d+", ref).group(0))
            cells[(ri, ci)] = val
            maxc, maxr = max(maxc, ci + 1), max(maxr, ri)
        out[sh.get("name")] = [[cells.get((r, c)) for c in range(maxc)] for r in range(1, maxr + 1)]
    return out


def hyperlinks(data, sheet_name):
    """{cell reference: external link target} for one sheet (for example the Outlook links in the task tracker)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    rels = {}
    for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
        t = rel.get("Target")
        rels[rel.get("Id")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
    path = None
    for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(M + "sheet"):
        if sh.get("name") == sheet_name:
            path = rels.get(sh.get(R + "id"))
    if not path:
        return {}
    rp = path.rsplit("/", 1)[0] + "/_rels/" + path.rsplit("/", 1)[1] + ".rels"
    if rp not in z.namelist():
        return {}
    targets = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read(rp))}
    out = {}
    for h in ET.fromstring(z.read(path)).iter(M + "hyperlink"):
        t = targets.get(h.get(R + "id"))
        if t:
            out[h.get("ref")] = t
    return out


def excel_date(v):
    """Excel serial number (or text) to YYYY-MM-DD, or None."""
    import datetime
    if isinstance(v, (int, float)) and 20000 < v < 80000:
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))).isoformat()
    if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
        return v[:10]
    return None

