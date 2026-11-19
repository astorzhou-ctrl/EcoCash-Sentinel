"""Document Intelligence (BRD 9.19): turns a document (audit report, policy, incident report, regulation) into DRAFT risks for a named reviewer to accept, edit or reject.
It builds on the Copilot's document store and the built-in engine. Nothing is saved to the register until a named reviewer accepts; the document's text is treated as data, never as
instructions; every decision is logged for model validation. From a document it can also send the duties it finds to the Obligations Hub and log a regulatory change."""
import re

from . import ai, ai_agent, ai_docintel as di, ai_engine, ai_gov, ai_kb, kit
from .api import router, need
from .core import audit, now
from .kit import hist
from .web import HTTPError
from . import db as dbm

ENG = ai_engine.ENGINE_VERSION + "%"


def get_doc(db, c, did):
    r = db.execute("SELECT * FROM ai_docs WHERE id=? AND deleted_at IS NULL", (did,)).fetchone()
    if not r or not ai_kb.visible(c, r):
        raise HTTPError(404, "not_found", "Document not found, or it is not approved yet and not yours.")
    return r


def stats(db):
    q = {r["status"]: r["n"] for r in db.execute("SELECT status, COUNT(*) n FROM ai_proposals WHERE kind='risk' AND model LIKE ? GROUP BY status", (ENG,))}
    dec = q.get("accepted", 0) + q.get("edited", 0) + q.get("rejected", 0)
    return {"suggested": sum(q.values()), "pending": q.get("pending", 0), "accepted": q.get("accepted", 0), "edited": q.get("edited", 0), "rejected": q.get("rejected", 0), "acceptance_rate": round(100.0 * (q.get("accepted", 0) + q.get("edited", 0)) / dec) if dec else None, "decided": dec}


@router.route("GET", "/api/docint")
def home(req):
    c = need(req, "document_intelligence", "view")
    docs = [{"id": d["id"], "title": d["title"], "version": d["version"], "kind": d["kind"], "status": d["status"], "chars": d["chars"], "quality": d["quality"], "filename": d["filename"]} for d in req.db.execute("SELECT * FROM ai_docs WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 200") if ai_kb.visible(c, d)]
    log = [{"id": r["id"], "status": r["status"], "by": r["decided_by"], "at": r["decided_at"], "note": r["decision_note"], "ref": r["applied_ref"], "title": (re.search(r'"title": "([^"]*)"', r["payload"]) or [0, ""])[1][:90], "confidence": r["confidence"]} for r in req.db.execute("SELECT * FROM ai_proposals WHERE kind='risk' AND model LIKE ? AND status != 'pending' ORDER BY id DESC LIMIT 40", (ENG,))]
    return {"docs": docs, "stats": stats(req.db), "log": log, "can": {k: k in c.perms.get("document_intelligence", set()) for k in ("create", "edit")}, "can_decide": "edit" in c.perms.get("sentinel_copilot", set()), "can_upload": "create" in c.perms.get("sentinel_copilot", set())}


@router.route("GET", "/api/docint/<int:did>")
def view(req):
    c = need(req, "document_intelligence", "view"); d = get_doc(req.db, c, int(req.params["did"])); text = d["text"] or ""
    if not text.strip():
        raise HTTPError(409, "unreadable", "Sentinel cannot read text from this document (scanned or special-font PDF). Upload a Word or text version.")
    hl = di.risk_candidates(text, 14); pages = [{"page": p, "text": t} for p, t in ai_kb.paged_passages(di.clean_text(text), 1400)[:70]]
    props = [ai_agent.proposal_row(req.db, r["id"]) for r in req.db.execute("SELECT id FROM ai_proposals WHERE source_doc=? AND kind='risk' ORDER BY id DESC LIMIT 30", (d["id"],))]
    return {"doc": {"id": d["id"], "title": d["title"], "version": d["version"], "chars": d["chars"]}, "pages": pages, "highlights": hl, "suggestions": props}


@router.route("POST", "/api/docint/<int:did>/suggest")
def suggest(req):
    c = need(req, "document_intelligence", "create"); d = get_doc(req.db, c, int(req.params["did"])); b = req.json(); text = d["text"] or ""
    if ai_gov.settings(req.db).get("mode") in (None, "off"):
        raise HTTPError(409, "ai_off", "AI is switched off. Only a System Administrator can switch it on (AI Governance).")
    if not text.strip():
        raise HTTPError(409, "unreadable", "Sentinel cannot read text from this document. Upload a Word or text version.")
    made, notes = ai_engine.draft_risks(req.db, c, c.user, text, d["title"], d["id"], limit=max(1, min(12, int(b.get("max") or 6)))); out = []
    for pid in made:
        p = ai_agent.proposal_row(req.db, pid); sim = ai.similar(req.db, c, (p["payload"].get("description") or p["payload"].get("title") or ""))["risks"]; p["match"] = {"ref": sim[0]["ref"], "title": sim[0]["title"][:80], "similarity": round(sim[0]["similarity"], 2)} if sim and sim[0]["similarity"] >= 0.25 else None; out.append(p)
    audit(req.db, "docint.suggest", c.user, "document_intelligence", "%d draft risks suggested from '%s' v%d" % (len(out), d["title"], d["version"]), req.ip)
    return {"suggestions": out, "notes": notes}


@router.route("POST", "/api/docint/<int:did>/to-obligations")
def to_obligations(req):
    """The duties the document imposes ('must', 'shall'), as obligations to assess in the Obligations Hub. Existing names are not repeated."""
    c = need(req, "document_intelligence", "view"); need(req, "obligations_hub", "create"); d = get_doc(req.db, c, int(req.params["did"])); kit.ensure_seed(req.db, "obligations_hub")
    have = {(x["name"] or "").lower() for x in kit.load(req.db, "obligations_hub", "obligation")}; added = []
    for o in [x for x in di.obligations(d["text"] or "", 60) if x["strength"] == "must"][:int(req.json().get("max") or 15)]:
        name = ("%s must %s" % (o["who"], o["what"]))[:200]
        if name.lower() in have:
            continue
        it = kit.create(req.db, c, "obligations_hub", "obligation", {"name": name, "regulator": "", "citation": "%s v%d p.%s" % (d["title"], d["version"], o["page"] or "-"), "owner": "", "frequency": "Event-driven" if not o["when"] else "Monthly" if "month" in (o["when"] or "") else "Annual" if "year" in (o["when"] or "") or "annual" in (o["when"] or "") else "Event-driven", "notes": "From Document Intelligence. Deadline in the text: %s" % (o["when"] or "none")}); added.append(it["ref"]); have.add(name.lower())
    audit(req.db, "docint.to_obligations", c.user, "document_intelligence", "%d obligations sent to the Obligations Hub from '%s'" % (len(added), d["title"]), req.ip)
    return {"added": added}


@router.route("POST", "/api/docint/<int:did>/to-change")
def to_change(req):
    """Logs the document (or what changed in its new version) as a regulatory change to assess."""
    c = need(req, "document_intelligence", "view"); need(req, "regulatory_change", "create"); d = get_doc(req.db, c, int(req.params["did"])); prev = req.db.execute("SELECT * FROM ai_docs WHERE id=?", (d["supersedes_id"],)).fetchone() if d["supersedes_id"] else None
    if prev:
        ch = di.compare(prev["text"] or "", d["text"] or ""); summ = "Version %d against version %d: %d changed, %d new and %d removed statements; %d new duties. %s" % (d["version"], prev["version"], len(ch["changed"]), len(ch["added"]), len(ch["removed"]), len(ch["new_duties"]), " ".join("%s -> %s" % (", ".join(x["from"]), ", ".join(x["to"])) for x in ch["changed"] if x["numbers_changed"])[:300])
    else:
        s = di.summarise(d["text"] or "", 4); summ = " ".join(x for _, x in s["points"])[:700]
    it = kit.create(req.db, c, "regulatory_change", "change", {"title": ("Change in %s (v%d)" % (d["title"], d["version"]))[:200], "reference": "%s v%d" % (d["title"], d["version"]), "summary": summ, "impact": "Medium", "owner": req.json().get("owner") or "Head of Compliance and ML/CTF"})
    audit(req.db, "docint.to_change", c.user, "document_intelligence", "Regulatory change %s logged from '%s'" % (it["ref"], d["title"]), req.ip)
    return {"ref": it["ref"]}
