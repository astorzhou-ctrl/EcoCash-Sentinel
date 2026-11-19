"""The approved content index (BRD 13.31): policies, regulations, the BRD, reports and notes the Copilot may rely on.
A document is uploaded (pending), extracted to text, and only becomes part of the index when a named person approves it. A new version of the same title is
compared with the one before it, so a change in a policy or regulation is seen at once. Retrieval is TF-IDF similarity over passages (the same engine as AI Insights)."""
import hashlib
import io
import json
import re
import zlib
import zipfile
from xml.etree import ElementTree as ET

from . import ai, xlsx
from .api import router, need, need_str
from .core import audit, now
from .web import HTTPError, Response

KINDS = ("policy", "regulation", "brd", "report", "standard", "procedure", "other")
MAX_BYTES = 40 * 1024 * 1024


# ------------------------------------------------------------------ text extraction (standard library only)
def _xml_text(data, para, text):
    out = []
    root = ET.fromstring(data)
    for p in root.iter(para):
        t = "".join(x.text or "" for x in p.iter(text)).strip()
        if t:
            out.append(t)
    return out


def docx_text(b):
    z = zipfile.ZipFile(io.BytesIO(b)); W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n\n".join(_xml_text(z.read("word/document.xml"), W + "p", W + "t"))


def pptx_text(b):
    z = zipfile.ZipFile(io.BytesIO(b)); A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"; out = []
    names = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[0]))
    for i, n in enumerate(names, 1):
        t = _xml_text(z.read(n), A + "p", A + "t")
        if t:
            out.append("[Slide %d]\n" % i + "\n".join(t))
    return "\n\n".join(out)


def xlsx_text(b):
    out = []
    for name, rows in xlsx.read(b).items():
        lines = [" | ".join(str(c) for c in r if c not in (None, "")) for r in rows]
        lines = [l for l in lines if l]
        if lines:
            out.append("[Sheet %s]\n" % name + "\n".join(lines[:600]))
    return "\n\n".join(out)


def _unescape_pdf(s):
    out, i = bytearray(), 0
    esc = {"n": 10, "r": 13, "t": 9, "b": 8, "f": 12, "(": 40, ")": 41, "\\": 92}
    while i < len(s):
        ch = s[i]
        if ch == 92 and i + 1 < len(s):
            nx = chr(s[i + 1])
            if nx in esc:
                out.append(esc[nx]); i += 2; continue
            if nx in "01234567":
                m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4]); out.append(int(m.group(0), 8) & 255); i += 1 + len(m.group(0)); continue
            i += 1; continue
        out.append(ch); i += 1
    return bytes(out)


def _streams(b):
    """The content streams of a PDF that can hold page text: small enough to be text, not the images and fonts that make up most of a big PDF."""
    pos = 0
    while True:
        i = b.find(b"stream", pos)
        if i < 0:
            return
        if b[max(0, i - 3):i] == b"end":
            pos = i + 6; continue
        start = i + 6
        if b[start:start + 2] == b"\r\n":
            start += 2
        elif b[start:start + 1] in (b"\n", b"\r"):
            start += 1
        j = b.find(b"endstream", start)
        if j < 0:
            return
        pos = j + 9; raw = b[start:j]
        if 20 <= len(raw) <= 400_000:
            yield raw


def pdf_text(b):
    """Text from a PDF with ordinary (non-CID) fonts. Returns (text, pages). Scanned or CID-font PDFs give little or gibberish: the quality check then flags
    the document so the model reads the PDF itself instead."""
    pages = []
    for raw in _streams(b):
        if raw[:1] == b"x":  # zlib header: a compressed content stream
            try:
                data = zlib.decompress(raw)
            except zlib.error:
                continue
        elif b"BT" in raw[:4000]:
            data = raw
        else:
            continue
        if len(data) > 3_000_000 or b"BT" not in data or b"ET" not in data:
            continue
        txt = []
        for blk in re.findall(rb"BT(.*?)ET", data, re.S):
            line = []
            for tj in re.finditer(rb"\[(.*?)\]\s*TJ|\((.*?)(?<!\\)\)\s*Tj|\((.*?)(?<!\\)\)\s*['\"]", blk, re.S):
                if tj.group(1) is not None:
                    parts = re.findall(rb"\((.*?)(?<!\\)\)|(-?\d+\.?\d*)", tj.group(1), re.S)
                    for s_, num in parts:
                        if s_:
                            line.append(_unescape_pdf(s_).decode("latin-1"))
                        elif num and float(num) < -250:
                            line.append(" ")
                else:
                    line.append(_unescape_pdf(tj.group(2) or tj.group(3)).decode("latin-1"))
            if line:
                txt.append("".join(line))
        if txt:
            pages.append(re.sub(r"\s+", " ", " ".join(txt)).strip())
    return "\n\n".join("[Page %d]\n%s" % (i, p) for i, p in enumerate(pages, 1)), len(pages)


def quality_of(text):
    """'good' when the text reads like words; 'poor' when it is mostly unreadable (scanned page, special fonts)."""
    if not text or len(text) < 200:
        return "poor"
    words = re.findall(r"[A-Za-z]{3,}", text)
    common = sum(1 for w in words if w.lower() in COMMON)
    return "good" if len(words) > 40 and common / max(1, len(words)) > 0.12 else "poor"


COMMON = set("the and for that with this are from have has not will shall may must any all risk control policy management information system data security shall board committee company business which their such been were than into other more also only where when under".split())


def extract(name, data):
    """(text, quality, note)"""
    n = (name or "").lower()
    try:
        if n.endswith(".docx"):
            t = docx_text(data)
        elif n.endswith(".pptx"):
            t = pptx_text(data)
        elif n.endswith(".xlsx"):
            t = xlsx_text(data)
        elif n.endswith(".pdf"):
            try:
                t, _ = pdf_text(data)
            except Exception:  # an odd PDF must never fail the upload: it is simply read by the model instead
                t = ""
            q = quality_of(t)
            return (t if q == "good" else ""), q, "" if q == "good" else "The text could not be read reliably from this PDF (scanned or special fonts). The AI reads the PDF itself when you analyse it."
        elif n.endswith((".txt", ".md", ".csv", ".json", ".log", ".html", ".htm")):
            t = data.decode("utf-8", "replace")
            if n.endswith((".html", ".htm")):
                t = html_text(t)
        else:
            raise HTTPError(400, "unsupported", "Upload a .pdf, .docx, .pptx, .xlsx, .txt, .md or .csv file.")
    except HTTPError:
        raise
    except Exception:
        raise HTTPError(400, "bad_file", "The file could not be read. Check that it is not damaged or password-protected.")
    return t, quality_of(t) if n.endswith((".docx", ".pdf", ".txt", ".md", ".html", ".htm", ".pptx")) else "good", ""


def html_text(h):
    h = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|br|section|article)>|<br\s*/?>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    import html as _h
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", _h.unescape(h))).strip()


# ------------------------------------------------------------------ passages and retrieval
def _split_long(p, size):
    out = []
    while len(p) > size * 1.4:
        cut = max(p.rfind(". ", 0, size + 200), p.rfind("; ", 0, size + 200), p.rfind(" ", 0, size))
        cut = cut + 1 if cut > size // 3 else size
        out.append(p[:cut].strip()); p = p[cut:].strip()
    return out + ([p] if p else [])


def paged_passages(text, size=900):
    """[(page or None, passage)]. A '[Page n]' marker (PDFs and transcriptions) or '[Slide n]' gives the page."""
    out, page = [], None
    for blk in re.split(r"\n\s*\n|\n(?=\[Slide|\[Sheet|\[Page)", text or ""):
        blk = blk.strip()
        m = re.match(r"\[(?:Page|Slide) (\d+)\]\s*", blk)
        if m:
            page = int(m.group(1)); blk = blk[m.end():]
        p = re.sub(r"\s+", " ", blk).strip()
        if not p:
            continue
        if out and out[-1][0] == page and len(out[-1][1]) + len(p) + 1 <= size:
            out[-1] = (page, out[-1][1] + " " + p)
        else:
            for piece in _split_long(p, size):
                out.append((page, piece))
    return out


def passages(text, size=900):
    return [p for _, p in paged_passages(text, size)]


def visible(c, d):
    return d["status"] == "approved" or d["uploaded_by"] == c.user["id"] or "approve" in c.perms.get("sentinel_copilot", set())


def index_docs(db, c, only_ids=None):
    """Latest approved version of each title, plus the user's own pending uploads."""
    rows = db.execute("SELECT id, title, kind, version, status, uploaded_by, text FROM ai_docs WHERE deleted_at IS NULL AND status IN ('approved','pending') AND text IS NOT NULL").fetchall()
    best = {}
    for r in rows:
        if not visible(c, r) or (only_ids is not None and r["id"] not in only_ids):
            continue
        k = r["title"].lower()
        if k not in best or (r["status"] == "approved", r["version"]) > (best[k]["status"] == "approved", best[k]["version"]):
            best[k] = r
    return list(best.values())


def search(db, c, query, k=6, only_ids=None):
    docs = index_docs(db, c, only_ids); chunks = []
    for d in docs:
        for i, (pg, p) in enumerate(paged_passages(d["text"])):
            chunks.append((d, i, p, pg))
    if not chunks or not query.strip():
        return []
    vecs, idf = ai.vectors([p + " " + d["title"] for d, i, p, pg in chunks]); q = ai.qvec(query, idf)
    scored = sorted(((ai.cos(q, v), j) for j, v in enumerate(vecs)), reverse=True)[:k]
    return [{"doc_id": chunks[j][0]["id"], "title": chunks[j][0]["title"], "kind": chunks[j][0]["kind"], "version": chunks[j][0]["version"], "status": chunks[j][0]["status"], "passage": chunks[j][1] + 1, "page": chunks[j][3], "text": chunks[j][2], "score": round(s, 3)} for s, j in scored if s > 0.04]


# ------------------------------------------------------------------ versions and change detection
def _sentences(text):
    out = []
    for blk in re.split(r"\n\s*\n|\[Page \d+\]|\[Slide \d+\]", text or ""):
        for s in re.split(r"(?<=[.;:])\s+", re.sub(r"\s+", " ", blk).strip()):
            if len(s) >= 25:
                out.append(s)
    return out


def diff_versions(old, new):
    """What changed between two versions, sentence by sentence (a changed clause shows as one removed and one added)."""
    a, b = _sentences(old), _sentences(new); sa, sb = set(a), set(b)
    added = [p for p in b if p not in sa]; removed = [p for p in a if p not in sb]
    return {"added": len(added), "removed": len(removed), "unchanged": len(sa & sb), "added_sample": [p[:260] for p in added[:8]], "removed_sample": [p[:260] for p in removed[:8]]}


def store_doc(db, c, title, kind, filename, data, confidentiality="internal"):
    if len(data) > MAX_BYTES:
        raise HTTPError(413, "too_large", "That file is larger than 40 MB.")
    text, quality, note = extract(filename, data)
    prev = db.execute("SELECT * FROM ai_docs WHERE lower(title)=lower(?) AND deleted_at IS NULL ORDER BY version DESC LIMIT 1", (title,)).fetchone()
    version = (prev["version"] + 1) if prev else 1; change = None
    sha = hashlib.sha256(data).hexdigest()
    if prev and (prev["sha256"] == sha or (text and prev["text"] and re.sub(r"\s+", " ", prev["text"]) == re.sub(r"\s+", " ", text))):  # the same file, or the same words saved again
        raise HTTPError(409, "duplicate", "That is identical to version %d of \"%s\" (nothing in the text has changed)." % (prev["version"], title))
    if prev and prev["text"] and text and quality == "good":
        change = diff_versions(prev["text"], text)
    did = db.execute("INSERT INTO ai_docs(title,kind,filename,version,status,confidentiality,text,chars,quality,sha256,data,uploaded_by,uploaded_by_name,uploaded_at,supersedes_id,change_summary) VALUES(?,?,?,?,'pending',?,?,?,?,?,?,?,?,?,?,?)",
                     (title[:200], kind, filename[:200], version, confidentiality, text, len(text or ""), quality, sha, data, c.user["id"], c.user["full_name"], now(), prev["id"] if prev else None, json.dumps(change) if change else None)).lastrowid
    return did, version, quality, note, change


def doc_row(r, c, full=False):
    d = {"id": r["id"], "title": r["title"], "kind": r["kind"], "filename": r["filename"], "version": r["version"], "status": r["status"], "confidentiality": r["confidentiality"], "chars": r["chars"], "quality": r["quality"], "uploaded_by": r["uploaded_by_name"], "uploaded_at": r["uploaded_at"],
         "approved_by": r["approved_by"], "approved_at": r["approved_at"], "change": json.loads(r["change_summary"]) if r["change_summary"] else None, "summary": r["summary"], "mine": r["uploaded_by"] == c.user["id"]}
    if full:
        d["preview"] = (r["text"] or "")[:6000]
    return d


@router.route("GET", "/api/ai/docs")
def docs_list(req):
    c = need(req, "sentinel_copilot", "view")
    rows = [r for r in req.db.execute("SELECT * FROM ai_docs WHERE deleted_at IS NULL ORDER BY title COLLATE NOCASE, version DESC").fetchall() if visible(c, r)]
    return {"docs": [doc_row(r, c) for r in rows], "kinds": list(KINDS), "can": {"upload": "create" in c.perms.get("sentinel_copilot", set()), "approve": "approve" in c.perms.get("sentinel_copilot", set())}}


@router.route("POST", "/api/ai/docs")
def docs_upload(req):
    c = need(req, "sentinel_copilot", "create")
    data = req.body(); name = req.headers.get("X-Filename") or req.query.get("filename") or "document.txt"
    if not data:
        raise HTTPError(400, "validation", "No file received.")
    title = (req.query.get("title") or re.sub(r"\.[A-Za-z0-9]+$", "", name)).strip()[:200] or "Untitled"
    kind = req.query.get("kind") if req.query.get("kind") in KINDS else "other"
    conf = req.query.get("confidentiality") if req.query.get("confidentiality") in ("internal", "restricted") else "internal"
    did, version, quality, note, change = store_doc(req.db, c, title, kind, name, data, conf)
    audit(req.db, "ai.doc_uploaded", c.user, "sentinel_copilot", "Document \"%s\" version %d uploaded (%s, %d KB)%s" % (title, version, kind, len(data) // 1024, ", " + str(change["added"]) + " passages added, " + str(change["removed"]) + " removed against the previous version" if change else ""), req.ip)
    return {"id": did, "title": title, "version": version, "quality": quality, "note": note, "change": change, "status": "pending"}


@router.route("GET", "/api/ai/docs/<int:did>")
def docs_one(req):
    c = need(req, "sentinel_copilot", "view")
    r = req.db.execute("SELECT * FROM ai_docs WHERE id=? AND deleted_at IS NULL", (int(req.params["did"]),)).fetchone()
    if not r or not visible(c, r):
        raise HTTPError(404, "not_found", "Document not found.")
    return doc_row(r, c, True)


@router.route("GET", "/api/ai/docs/<int:did>/download")
def docs_download(req):
    c = need(req, "sentinel_copilot", "export")
    r = req.db.execute("SELECT * FROM ai_docs WHERE id=? AND deleted_at IS NULL", (int(req.params["did"]),)).fetchone()
    if not r or not visible(c, r):
        raise HTTPError(404, "not_found", "Document not found.")
    return Response(bytes(r["data"]), 200, "application/octet-stream", [("Content-Disposition", 'attachment; filename="%s"' % (r["filename"] or "document").replace('"', ""))])


@router.route("POST", "/api/ai/docs/<int:did>/approve")
def docs_approve(req):
    c = need(req, "sentinel_copilot", "approve")
    r = req.db.execute("SELECT * FROM ai_docs WHERE id=? AND deleted_at IS NULL", (int(req.params["did"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Document not found.")
    if r["uploaded_by"] == c.user["id"]:
        raise HTTPError(403, "separation", "The person who uploaded a document cannot approve it into the index. Ask another approver.")
    if r["quality"] == "poor" and not (r["text"] or "").strip():
        raise HTTPError(409, "unreadable", "Sentinel could not read text from this document, so it cannot be indexed. Upload a text version, or use Analyse (the AI reads the PDF itself).")
    req.db.execute("UPDATE ai_docs SET status='archived' WHERE lower(title)=lower(?) AND status='approved' AND id!=?", (r["title"], r["id"]))  # the new version supersedes the old
    req.db.execute("UPDATE ai_docs SET status='approved', approved_by=?, approved_at=? WHERE id=?", (c.user["full_name"], now(), r["id"]))
    audit(req.db, "ai.doc_approved", c.user, "sentinel_copilot", "Document \"%s\" version %d approved into the Copilot's index" % (r["title"], r["version"]), req.ip)
    return {"ok": True}


@router.route("POST", "/api/ai/docs/<int:did>/delete")
def docs_delete(req):
    c = need(req, "sentinel_copilot", "create")
    r = req.db.execute("SELECT * FROM ai_docs WHERE id=? AND deleted_at IS NULL", (int(req.params["did"]),)).fetchone()
    if not r or not (r["uploaded_by"] == c.user["id"] or "approve" in c.perms.get("sentinel_copilot", set())):
        raise HTTPError(404, "not_found", "Document not found.")
    why = need_str(req.json(), "reason", "Reason", 300)
    req.db.execute("UPDATE ai_docs SET deleted_at=? WHERE id=?", (now(), r["id"]))
    import datetime
    req.db.execute("INSERT INTO recycle(entity_type,entity_id,title,module,deleted_by,deleted_by_name,deleted_at,reason,purge_at) VALUES('ai_doc',?,?,?,?,?,?,?,?)", (r["id"], "AI document %s v%d" % (r["title"], r["version"]), "sentinel_copilot", c.user["id"], c.user["full_name"], now(), why, (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    audit(req.db, "ai.doc_deleted", c.user, "sentinel_copilot", "Document \"%s\" v%d deleted to the Recycle Bin: %s" % (r["title"], r["version"], why), req.ip)
    return {"ok": True}


@router.route("GET", "/api/ai/docs/search")
def docs_search(req):
    c = need(req, "sentinel_copilot", "view")
    return {"results": search(req.db, c, req.query.get("q") or "", 8)}
