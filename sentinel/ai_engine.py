"""Sentinel's built-in AI engine: free, runs on this computer, needs no key, no internet and no model provider.
It is not a generative language model. It is a transparent reasoning engine built for enterprise risk management:
  * it understands the question (intents, risk references, filters, follow-ups to the previous answer);
  * it reads the live register, controls, actions, indicators, incidents and the approved documents through the same permission-checked tools as the Claude engine;
  * it composes the answer from those facts in plain language, with the sources, and says plainly what it could not find;
  * it drafts risks and rates them from EVIDENCE: the ratings of similar risks in your register, the effectiveness of their controls, the incidents and indicators of the
    same category, and what reviewers changed before (so it learns from decisions); every rating comes with the factors that produced it;
  * it analyses a development (a monetary-policy decision, a new directive) against your risks and indicators;
  * it researches the web through free search engines and approved sources and cites what it finds.
Every result is a proposal for a named person to accept or reject (BRD 4.2); nothing is written to a record."""
import datetime
import json
import re

from . import ai, ai_docintel as di, ai_kb, ai_tools, ai_web, analytics, depts, erm_knowledge as erm, matrix as mx, register
from . import db as dbm
from .core import now

ENGINE_VERSION = "sentinel-engine-1.0"
ENGINE_LABEL = "Sentinel built-in engine (runs on this computer)"
REF = re.compile(r"\b(?:(ISMS|BCMS)\s*[-]?\s*0*(\d{1,2})|R-0*(\d{1,4}))\b", re.I)
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def money(v):
    if v is None:
        return "n/a"
    return "$%.1fM" % (v / 1e6) if abs(v) >= 1e6 else "$%dK" % round(v / 1e3) if abs(v) >= 1e3 else "$%d" % round(v)


def pct(v):
    return "n/a" if v is None else "%d%%" % round(v * 100)


def norm_ref(m):
    return "%s %02d" % (m.group(1).upper(), int(m.group(2))) if m.group(1) else "R-%03d" % int(m.group(3))


def refs_in(text):
    return [norm_ref(m) for m in REF.finditer(text or "")]


def want_n(text, default=5):
    m = re.search(r"\b(?:top|first|biggest|highest|worst)\s+(\d{1,2}|" + "|".join(NUM_WORDS) + r")\b", text, re.I) or re.search(r"\b(\d{1,2}|" + "|".join(NUM_WORDS) + r")\s+(?:risks|points|items|bullets)\b", text, re.I)
    if not m:
        return default
    v = m.group(1).lower()
    return NUM_WORDS.get(v) or int(v)


class A:
    """An answer being built."""
    def __init__(self, intent):
        self.intent = intent; self.parts = []; self.sources = []; self.tools = []; self.follow = []; self.proposals = []; self.web = None; self.flags = []; self.confidence = None; self.auto_web = False; self.web_failed = False; self.web_note = None

    def say(self, t):
        self.parts.append(t)

    def src(self, s):
        if not any(x.get("type") == s.get("type") and (x.get("ref") or x.get("url") or x.get("doc_id") or x.get("title")) == (s.get("ref") or s.get("url") or s.get("doc_id") or s.get("title")) and x.get("page") == s.get("page") for x in self.sources):
            self.sources.append(s)

    def used(self, name, args=""):
        self.tools.append({"name": name, "args": str(args)[:200]})

    def out(self):
        txt = "\n\n".join(p for p in self.parts + [self.web_note] if p)
        for s in self.sources:
            s["cited"] = (s["type"] == "record" and (s["ref"] in txt)) or (s["type"] in ("doc", "knowledge")) or s["type"] == "web"
        return {"text": txt, "sources": self.sources, "tools": self.tools, "follow_ups": self.follow[:4], "intent": self.intent, "proposals": self.proposals, "web": self.web, "flags": self.flags, "engine": ENGINE_VERSION, "auto_web": self.auto_web}


def rec(r):
    return {"type": "record", "kind": "risk", "ref": r["source_ref"] or r["ref"], "label": r["title"][:80], "id": r["id"]}


def line(r):
    ref = r["source_ref"] or r["ref"]; pos = register.position(r)
    return "**[%s]** %s: RRR %s (%s), LoA %s, EMV-r %s, owner %s" % (ref, r["title"][:110].rstrip(".") , "n/a" if r["rrr"] is None else "%.1f" % r["rrr"], pos.lower(), pct(r["loa"]), money(r["emv_r"]), r["dept"])


def scope_rows(db, c):
    rows, ctl = analytics.risk_rows(db, c)
    return rows, ctl


def find_risk(rows, ref):
    ref = (ref or "").lower()
    return next((r for r in rows if (r["source_ref"] or "").lower() == ref or (r["ref"] or "").lower() == ref), None)


# ------------------------------------------------------------------ evidence around a risk
def evidence(db, c, r):
    """Everything the register knows about one risk: indicators in alert, incidents, overdue actions, control strength."""
    ev = {"kris": [], "incidents": 0, "loss": 0.0, "overdue": [], "weak_domains": [], "untested": 0}
    for k in db.execute("SELECT * FROM kpis WHERE risk_id=? AND active=1 AND deleted_at IS NULL", (r["id"],)):
        rs = db.execute("SELECT period, value FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 1", (k["id"],)).fetchone()
        if not rs:
            continue
        try:
            from . import p2
            s = p2.status_of(k, rs["value"]); s = s if isinstance(s, str) else (s or {}).get("status")
        except Exception:
            s = None
        if s and str(s).lower() not in ("ok", "green", "on_target", "none"):
            ev["kris"].append({"code": k["code"], "name": k["name"], "status": s, "value": rs["value"]})
    inc = db.execute("SELECT COUNT(*) n, COALESCE(SUM(gross_loss),0) l FROM incidents WHERE risk_id=? AND deleted_at IS NULL AND COALESCE(occurred_on, created_at) >= ?", (r["id"], (dbm.today() - datetime.timedelta(days=365)).isoformat())).fetchone()
    ev["incidents"], ev["loss"] = inc["n"], inc["l"]
    ev["overdue"] = [dict(x) for x in db.execute("SELECT ref, title, COALESCE(revised_due, due_date) due FROM actions WHERE risk_id=? AND deleted_at IS NULL AND status NOT IN ('closed','cancelled') AND COALESCE(revised_due, due_date) < ?", (r["id"], now()[:10]))]
    for d in analytics.DOMAINS:
        x = r["domains"][d]
        if x["n"] and x["ice"] is not None and (1 - x["ice"]) < 0.65:
            ev["weak_domains"].append((d, 1 - x["ice"], x["n"]))
    ev["untested"] = db.execute("SELECT COUNT(*) n FROM risk_controls WHERE risk_id=? AND COALESCE(ice_source,'self')!='test'", (r["id"],)).fetchone()["n"]
    return ev


def why_lines(r, ev):
    out = []
    if r["rrr"] is not None:
        t = r.get("rr_appetite") or 12.0
        out.append("Residual rating %.1f is above the appetite of %s%s." % (r["rrr"], int(t) if t == int(t) else t, " and the tolerance of %s" % int(r.get("rr_tolerance") or 15) if r["rrr"] > (r.get("rr_tolerance") or 15) else ""))
    if r["loa"] is not None:
        out.append("Level of assurance is %s against the 80%% target%s." % (pct(r["loa"]), " (controls are not giving enough comfort)" if r["loa"] < 0.8 else ""))
    if ev["weak_domains"]:
        w = sorted(ev["weak_domains"], key=lambda z: z[1])[0]; out.append("The weakest control category is %s at %s effectiveness across %d controls." % (w[0], pct(w[1]), w[2]))
    if ev["kris"]:
        out.append("%d linked indicator(s) in alert: %s." % (len(ev["kris"]), "; ".join("%s (%s)" % (k["name"], k["status"]) for k in ev["kris"][:3])))
    if ev["incidents"]:
        out.append("%d incident(s) in the last 12 months, gross loss %s." % (ev["incidents"], money(ev["loss"])))
    if ev["overdue"]:
        out.append("%d treatment action(s) overdue: %s." % (len(ev["overdue"]), ", ".join(x["ref"] for x in ev["overdue"][:3])))
    return out


# ------------------------------------------------------------------ handlers: the register
def h_help(db, c, a, q, ctx):
    a.say("I am **Sentinel Copilot**, running on the built-in engine: it works on this computer, with no key and no cost. I read your live register, controls, actions, indicators, incidents and the documents approved into my index, and I always show where an answer comes from. I can:")
    a.say("- answer questions about **risks, controls, actions, KRIs and incidents** (for example *Which risks are above appetite and why?*)\n- **read and summarise documents**, list their **obligations** and **answer questions** about them with page numbers\n- **explain** enterprise risk management concepts and how EcoCash applies them\n- **draft risks** from a document or a description and **review ratings**, as proposals for you to accept or reject\n- **analyse a development** (a policy-rate change, a new directive) against your risks\n- **search the web** through free search engines and approved sources, and open any search in your own browser")
    a.say("I never change a record or send anything myself: I draft, and a named person decides. I am not a generative AI model, so for open-ended questions I will say what I could not find rather than guess.")
    a.follow = ["Which risks are above appetite and why?", "Summarise our risk position for the Board in five points.", "What is residual risk?", "Which actions are overdue?"]


def h_overview(db, c, a, q, ctx):
    rows, ctl = scope_rows(db, c); sm = analytics.summarise(rows); a_ = [r for r in rows if r["rrr"] is not None]
    if not rows:
        a.say("There are no risks in the register that you may see yet. Import the assessment workbook (Risk Register > Assessment register) or add a risk."); return
    above = [r for r in a_ if register.position(r) in ("Above appetite", "Above tolerance")]; top = sorted(a_, key=lambda r: -r["rrr"])[:3]
    od = db.execute("SELECT COUNT(*) n FROM actions WHERE deleted_at IS NULL AND status NOT IN ('closed','cancelled') AND COALESCE(revised_due, due_date) < ?", (now()[:10],)).fetchone()["n"] if ai_tools.can(c, "actions_issues") else None
    alerts = ai_tools.t_kpi_status(db, c, {"only_alerts": True, "limit": 50}, {})[0] if (ai_tools.can(c, "weekly_kpi") or ai_tools.can(c, "kri_monitor")) else {"count": None}
    a.used("portfolio", "summary")
    pts = ["**Exposure.** %d risks assessed; inherent exposure %s, residual %s." % (sm["assessed"], money(sm["emv_i"]), money(sm["emv_r"])),
           "**Assurance.** Average level of assurance %s against the 80%% target; average level of risk %s against 20%%." % (pct(sm["loa"]), pct(sm["lor"])),
           "**Appetite.** %d risk(s) are above appetite%s." % (len(above), ": " + ", ".join("[%s]" % (r["source_ref"] or r["ref"]) for r in sorted(above, key=lambda z: -z["rrr"])[:5]) if above else ""),
           "**Highest residual risks.** " + "; ".join("[%s] %.1f" % (r["source_ref"] or r["ref"], r["rrr"]) for r in top) + "."]
    if od is not None:
        pts.append("**Actions.** %d overdue." % od)
    if alerts.get("count") is not None:
        pts.append("**Indicators.** %d KPI/KRI value(s) in alert." % alerts["count"])
    n = want_n(q, 5)
    a.say("Here is the risk position%s:" % (" in %d points for the Board" % n if re.search(r"board|points", q, re.I) else "")); a.say("\n".join("%d. %s" % (i + 1, p) for i, p in enumerate(pts[:max(n, 3)])))
    for r in top:
        a.src(rec(r))
    a.src({"type": "record", "kind": "analytics", "ref": "Performance Analytics", "label": "Performance Analytics"})
    a.follow = ["Which risks are above appetite and why?", "Which KRIs are in alert?", "Which actions are overdue?"]


def h_above(db, c, a, q, ctx):
    rows, _ = scope_rows(db, c); a_ = [r for r in rows if r["rrr"] is not None]; above = sorted([r for r in a_ if register.position(r) in ("Above appetite", "Above tolerance")], key=lambda r: -r["rrr"])
    a.used("register", "above appetite")
    if not above:
        a.say("No assessed risk is above appetite (%d assessed)." % len(a_)); return
    a.say("**%d of %d assessed risks are above appetite.** Each with the reasons the register gives:" % (len(above), len(a_)))
    for r in above[:8]:
        ev = evidence(db, c, r); a.src(rec(r)); a.say(line(r) + "\n" + "\n".join("  - " + w for w in why_lines(r, ev)[:4]))
    a.say("Risks above appetite need a dated, costed treatment plan; above tolerance needs Board attention.")
    a.follow = ["Tell me about %s" % (above[0]["source_ref"] or above[0]["ref"]), "Which actions are overdue?", "Review the rating of %s" % (above[0]["source_ref"] or above[0]["ref"])]


def h_top(db, c, a, q, ctx):
    rows, _ = scope_rows(db, c); n = want_n(q, 5); top = sorted([r for r in rows if r["rrr"] is not None], key=lambda r: -r["rrr"])[:n]; a.used("register", "top %d by RRR" % n)
    if not top:
        a.say("No assessed risks to rank yet."); return
    a.say("The **top %d risks by residual risk rating** (RRR, 0\u201325):" % len(top)); a.say("\n".join("%d. %s" % (i + 1, line(r)) for i, r in enumerate(top)))
    for r in top:
        a.src(rec(r))
    a.follow = ["Tell me about %s" % (top[0]["source_ref"] or top[0]["ref"]), "Which risks are above appetite and why?"]


def h_risk(db, c, a, q, ctx, ref):
    rows, _ = scope_rows(db, c); r = find_risk(rows, ref)
    if not r:
        a.say("I could not find a risk **%s** among the risks you may see. Try the reference as shown in the register (for example ISMS 06 or R-015)." % ref); return
    e = db.execute("SELECT description, root_cause, implication, treatment, objective, action_date FROM risks WHERE id=?", (r["id"],)).fetchone(); ev = evidence(db, c, r); a.used("register", ref); a.src(rec(r))
    r_ref = r["source_ref"] or r["ref"]
    a.say("**[%s] %s**" % (r_ref, r["title"]))
    facts = ["Category **%s**, system %s, strategic objective %s" % (r["category"] or "n/a", r["system"] or "n/a", r["so"]), "Owner **%s** (%s); status **%s**" % (r["owner"] or "n/a", r["dept"], r["status"]),
             "Residual rating **%s**, %s; level of assurance %s; inherent exposure %s, residual %s" % ("n/a" if r["rrr"] is None else "%.1f" % r["rrr"], register.position(r).lower(), pct(r["loa"]), money(r["emv_i"]), money(r["emv_r"]))]
    a.say("\n".join("- " + f for f in facts))
    if e["root_cause"]:
        a.say("**Cause.** %s" % e["root_cause"][:400])
    if e["implication"]:
        a.say("**Consequences.** %s" % e["implication"][:400])
    cs = ", ".join("%s %s (%d)" % (d, pct(1 - r["domains"][d]["ice"]), r["domains"][d]["n"]) for d in analytics.DOMAINS if r["domains"][d]["ice"] is not None)
    a.say("**Controls.** %d linked; effectiveness by category: %s." % (r["controls"], cs or "not rated yet"))
    if e["treatment"]:
        a.say("**Treatment.** %s%s" % (e["treatment"][:300], " (due %s)" % e["action_date"] if e["action_date"] else ""))
    w = why_lines(r, ev)
    if w:
        a.say("**What the register shows around it:**\n" + "\n".join("- " + x for x in w))
    a.follow = ["What are the controls for %s?" % r_ref, "Review the rating of %s" % r_ref, "Which actions are overdue?"]


def h_controls_for(db, c, a, q, ctx, ref):
    rows, _ = scope_rows(db, c); r = find_risk(rows, ref)
    if not r:
        a.say("I could not find that risk among the risks you may see."); return
    res, src = ai_tools.t_risk_controls(db, c, {"ref": ref, "limit": 200}, {}); a.used("controls", ref); [a.src(s) for s in src]
    cs = sorted(res["controls"], key=lambda x: (x["effectiveness"] if x["effectiveness"] is not None else 2))
    by = {}
    for x in cs:
        by.setdefault(x["category"], []).append(x)
    a.say("**[%s]** has **%d controls**. By P2ST2 category: %s." % (ref, res["total_controls"], ", ".join("%s %d" % (k, len(v)) for k, v in sorted(by.items()))))
    a.say("The **weakest** controls (lowest effectiveness) first:\n" + "\n".join("- %s **%s** %s: %s (%s)" % (x["category"], x["ref"] or "", "%s" % (pct(x["effectiveness"]) if x["effectiveness"] is not None else "not rated"), (x["statement"] or "no statement recorded")[:110], x["department"]) for x in cs[:6]))
    a.follow = ["Tell me about %s" % ref]


def h_controls_status(db, c, a, q, ctx):
    rows, _ = scope_rows(db, c); ids = [r["id"] for r in rows]
    if not ids:
        a.say("No controls to review yet."); return
    ks = [k for k in db.execute("SELECT risk_id, ref, domain, ice, ice_source, owner FROM risk_controls") if k["risk_id"] in set(ids)]; n = len(ks); a.used("controls", "status")
    rated = [k for k in ks if k["ice"] is not None]; weak = [k for k in rated if (1 - k["ice"]) < 0.5]; noowner = [k for k in ks if not (k["owner"] or "").strip() or (k["owner"] or "").strip().lower() == "none"]; tested = [k for k in ks if (k["ice_source"] or "self") == "test"]
    avg = 1 - sum(k["ice"] for k in rated) / len(rated) if rated else None
    a.say("**%d controls** are linked to the risks you may see; average effectiveness **%s** against the 80%% target." % (n, pct(avg)))
    a.say("- **%d** (%d%%) are weak (effectiveness below 50%%)\n- **%d** have no named owner (their department is inferred from the same control elsewhere or from the risk owner)\n- **%d** (%d%%) have a rating from an independent test; the rest are self-assessed or imported" % (len(weak), round(100 * len(weak) / max(1, n)), len(noowner), len(tested), round(100 * len(tested) / max(1, n))))
    wk = {}
    for k in weak:
        wk[k["domain"]] = wk.get(k["domain"], 0) + 1
    if wk:
        a.say("Weak controls by category: " + ", ".join("%s %d" % (k, v) for k, v in sorted(wk.items(), key=lambda z: -z[1])) + ".")
    a.say("Failed independent tests raise an action automatically; retests are due after 6 or 12 months depending on the risk rank.")
    a.follow = ["Which risks are above appetite and why?", "Which actions are overdue?"]


def h_actions(db, c, a, q, ctx):
    res, src = ai_tools.t_list_actions(db, c, {"overdue": bool(re.search(r"overdue|late|past due", q, re.I)), "limit": 25}, {}); a.used("actions", "overdue" if re.search("overdue|late", q, re.I) else "all")
    if res.get("error"):
        a.say(res["error"]); return
    [a.src(s) for s in src]
    if not res["count"]:
        a.say("There are no %sactions to report." % ("overdue " if re.search("overdue|late", q, re.I) else "")); return
    by = {}
    for x in res["actions"]:
        by.setdefault(x["owner"] or "no owner", []).append(x)
    a.say("**%d %saction(s)**%s:" % (res["count"], "overdue " if re.search("overdue|late", q, re.I) else "", " (showing the first %d)" % len(res["actions"]) if res["count"] > len(res["actions"]) else ""))
    a.say("\n".join("- **%s** %s: due %s, owner %s, escalation level %s" % (x["ref"], x["title"][:90], x["due"], x["owner"], x["escalation_level"]) for x in res["actions"][:12]))
    a.say("Overdue actions escalate: owner on day 1, Head of Risk on day 3, MD on day 7. Closing needs evidence and an approver who is not the owner or creator.")
    a.follow = ["Which risks are above appetite and why?", "Which KRIs are in alert?"]


def h_kpi(db, c, a, q, ctx):
    res, src = ai_tools.t_kpi_status(db, c, {"only_alerts": True, "limit": 20}, {}); a.used("indicators", "alerts")
    if res.get("error"):
        a.say(res["error"]); return
    [a.src(s) for s in src]
    if not res["count"]:
        a.say("No indicator is in alert at the latest reading."); return
    a.say("**%d indicator value(s) are in alert** (latest reading against the target, amber and red thresholds):" % res["count"])
    nice = {"red": "red", "amber": "amber", "off": "off target"}
    a.say("\n".join("- **%s** %s (%s): %s%s, **%s**%s" % (x["code"], x["name"][:70], x["kind"].upper(), x["latest"], x["unit"] or "", nice.get(x["status"], x["status"]), " (red at %s)" % x["red"] if x["status"] in ("red", "amber") and x["red"] is not None else (" (target %s)" % x["target"] if x["target"] is not None else "")) for x in res["indicators"][:10]))
    a.say("A red KRI should open an action; check the trend in KRI Monitor before deciding.")
    a.follow = ["Which risks are above appetite and why?", "Which actions are overdue?"]


def h_incidents(db, c, a, q, ctx):
    res, src = ai_tools.t_recent_incidents(db, c, {"limit": 8}, {}); a.used("incidents", "recent")
    if res.get("error"):
        a.say(res["error"]); return
    [a.src(s) for s in src]
    if not res["count"]:
        a.say("No incidents or losses are recorded."); return
    tot = sum(i["gross_loss"] or 0 for i in res["incidents"])
    a.say("**%d recent incident(s)**, gross loss %s:" % (res["count"], money(tot))); a.say("\n".join("- **%s** %s: %s, %s severity, %s, loss %s" % (i["ref"], i["title"][:80], i["category"] or "n/a", i["severity"], i["status"], money(i["gross_loss"] or 0)) for i in res["incidents"]))
    a.follow = ["Which risks are above appetite and why?"]


def h_coverage(db, c, a, q, ctx):
    rows = register.register_rows(db, c); cov = register.coverage(rows); a.used("register", "strategic coverage")
    if not cov:
        a.say("No strategic objective data yet: import the assessment workbook."); return
    a.say("**Strategic coverage** (how the ISMS and BCMS objectives cover the strategic objectives): %d objectives, %d covered by both." % (len(cov), sum(1 for x in cov if x["status"] == "Covered")))
    a.say("\n".join("- **%s**: BCMS %d, ISMS %d, total %d, %s" % (x["so"], x["bcms"], x["isms"], x["total"], x["status"].lower()) for x in cov))
    a.src({"type": "record", "kind": "analytics", "ref": "Risk Register > Strategic coverage", "label": "Strategic coverage"})


def h_search(db, c, a, q, ctx):
    words = re.sub(r"(?i)\b(risks?|any|about|related|relating|to|on|for|show|me|list|find|which|are|there|the|of|with|regarding|concerning)\b", " ", q).strip()
    res, src = ai_tools.t_search_register(db, c, {"query": words or q, "limit": 8}, {}); a.used("register", words)
    system = re.search(r"\b(ISMS|BCMS)\b", q, re.I)
    if system:
        res, src = ai_tools.t_search_register(db, c, {"query": words or q, "system": system.group(1).upper(), "limit": 10}, {})
    if not res["count"]:
        return False
    [a.src(s) for s in src]
    a.say("I found **%d risk(s)** that match:" % res["count"]); a.say("\n".join("- **[%s]** %s: RRR %s, %s, owner %s" % (x["ref"], x["title"][:105], x["residual_risk_rating_0_25"], x["assessment_basis"], x["department"]) for x in res["risks"]))
    a.follow = ["Tell me about %s" % res["risks"][0]["ref"], "What are the controls for %s?" % res["risks"][0]["ref"]]
    return True


def h_changes(db, c, a, q, ctx):
    rows, _ = scope_rows(db, c); ids = {r["id"]: r for r in rows}
    since = (dbm.today() - datetime.timedelta(days=30)).isoformat() + "T00:00:00Z"; hs = [h for h in db.execute("SELECT risk_id, action, ts, username FROM risk_history WHERE ts>=? ORDER BY ts DESC", (since,)) if h["risk_id"] in ids]; a.used("history", "30 days")
    if not hs:
        a.say("No changes to the risks you may see in the last 30 days."); return
    by = {}
    for h in hs:
        by.setdefault(h["action"], []).append(h)
    a.say("**%d change(s) in the last 30 days** across %d risk(s):" % (len(hs), len({h["risk_id"] for h in hs}))); a.say("\n".join("- %s: %d" % (k, len(v)) for k, v in sorted(by.items(), key=lambda z: -len(z[1]))[:8]))
    a.say("Most recent: " + "; ".join("[%s] %s (%s)" % (ids[h["risk_id"]]["source_ref"] or ids[h["risk_id"]]["ref"], h["action"], h["ts"][:10]) for h in hs[:4]) + ".")
    for h in hs[:4]:
        a.src(rec(ids[h["risk_id"]]))


# ------------------------------------------------------------------ concepts
def h_define(db, c, a, q, ctx):
    hits = erm.lookup(q)
    if not hits or hits[0][0] < 3:
        return False
    a.used("knowledge", hits[0][1]["id"])
    for s, e in hits[:2 if hits[0][0] - (hits[1][0] if len(hits) > 1 else 0) < 2 else 1]:
        body = erm.render(e)
        a.say(body if body.lower().startswith("**" + e["title"].lower().split(" (")[0]) else "**%s.** %s" % (e["title"], body)); a.src({"type": "knowledge", "title": e["title"], "refs": e["refs"]})
    a.say("*General reference from the Sentinel ERM knowledge pack. EcoCash's own rules are in the GRC Policy and the approved documents; for outside facts check the official source.*")
    a.follow = ["Which risks are above appetite and why?", "Search the web for the latest on this"] if erm.lookup(q)[0][1]["id"] in ("monetary", "regulators", "data_protection", "aml") else ["Which risks are above appetite and why?"]
    return True


# ------------------------------------------------------------------ documents
def pick_docs(db, c, q, doc_ids):
    docs = []
    for did in doc_ids or []:
        r = db.execute("SELECT * FROM ai_docs WHERE id=? AND deleted_at IS NULL", (int(did),)).fetchone()
        if r and ai_kb.visible(c, r) and r["text"]:
            docs.append(r)
    if docs:
        return docs
    ql = q.lower(); best = []
    for d in ai_kb.index_docs(db, c):
        t = d["title"].lower()
        if t in ql or any(w in ql for w in re.findall(r"[a-z]{4,}", t) if w not in ("policy", "document", "version")) and ("policy" in ql or "document" in ql or "brd" in ql or "directive" in ql):
            best.append(d)
    if not best and re.search(r"\b(grc|policy|brd|the document|regulation|directive|standard)\b", ql):
        best = ai_kb.index_docs(db, c)
    return [db.execute("SELECT * FROM ai_docs WHERE id=?", (d["id"],)).fetchone() for d in best[:3]]


def doc_src(d, page=None):
    return {"type": "doc", "doc_id": d["id"], "title": d["title"], "version": d["version"], "page": page}


def h_doc_summary(db, c, a, q, ctx, docs):
    if not docs:
        a.say("Tell me which document, or attach one: I can only summarise documents you may see (approved ones, or your own uploads)."); return
    d = docs[0]; s = di.summarise(d["text"], want_n(q, 7)); ob = di.obligations(d["text"], 6); a.used("document", d["title"])
    a.say("**%s** (version %d; %s words; %d sentences read)" % (d["title"], d["version"], "{:,}".format(s["stats"].get("words", 0)), s["stats"].get("sentences", 0)))
    if s["purpose"]:
        a.say("**Purpose.** %s *(p.%s)*" % (s["purpose"][1][:360], s["purpose"][0] or "\u2013")); a.src(doc_src(d, s["purpose"][0]))
    a.say("**Key points**\n" + "\n".join("- %s *(p.%s)*" % (x[:300], p or "\u2013") for p, x in s["points"])); [a.src(doc_src(d, p)) for p, _ in s["points"][:4]]
    must = [o for o in ob if o["strength"] == "must"][:4]
    if must:
        a.say("**Main duties**\n" + "\n".join("- %s must %s%s *(p.%s)*" % (o["who"], o["what"][:150].rstrip("."), " \u2014 %s" % o["when"] if o["when"] else "", o["page"] or "\u2013") for o in must))
    f = s["facts"]
    bits = [("Dates", f["dates"]), ("Amounts", f["amounts"]), ("Percentages", f["percentages"][:6]), ("Periods", f["periods"][:6])]
    bits = ["%s: %s" % (k, ", ".join(v)) for k, v in bits if v]
    if bits:
        a.say("**Dates and numbers mentioned.** " + "; ".join(bits))
    a.say("*Extractive summary: these are the document's own sentences, chosen for how central they are. Read the pages cited before relying on them.*")
    a.follow = ["List the obligations in %s" % d["title"], "What does %s say about control effectiveness?" % d["title"]]


def h_obligations(db, c, a, q, ctx, docs):
    if not docs:
        a.say("Tell me which document, or attach one."); return
    d = docs[0]; ob = di.obligations(d["text"], 40); a.used("document", "obligations"); a.src(doc_src(d))
    if not ob:
        a.say("I did not find sentences imposing duties (shall, must, is required to) in **%s**." % d["title"]); return
    by = {}
    for o in ob:
        by.setdefault(o["theme"], []).append(o)
    a.say("**%d duties found in %s.** %d have a stated deadline or frequency." % (len(ob), d["title"], sum(1 for o in ob if o["when"])))
    rows = ["| Who | Must | When | Page |", "|---|---|---|---|"] + ["| %s | %s | %s | %s |" % (o["who"][:50].replace("|", "/"), o["what"][:120].replace("|", "/"), o["when"] or "not stated", o["page"] or "\u2013") for o in ob[:18]]
    a.say("\n".join(rows))
    a.say("Themes: " + ", ".join("%s (%d)" % (k, len(v)) for k, v in sorted(by.items(), key=lambda z: -len(z[1]))) + ". Check the duties with **no stated deadline** and no named owner first: those are the ones that slip.")
    a.follow = ["Summarise %s" % d["title"]]


FILLER = set("what does do did the a an and of in on to for is are was were say says said about according state states provide provides define defines rule rules tell me please explain document documents policy policies grc brd regulation directive standard manual version our ecocash".split())


def doc_query(q, docs):
    """The words that carry the question: filler and the document's own name match every sentence, so they are dropped."""
    drop = set(FILLER)
    for d in docs or []:
        drop |= set(re.findall(r"[a-z]{3,}", d["title"].lower()))
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+", q) if w.lower() not in drop]
    return " ".join(words) or q


def h_doc_qa(db, c, a, q, ctx, docs):
    """Answer a question from the approved documents (or the attached ones): the best sentences, quoted, with pages."""
    only = [d["id"] for d in docs] if docs else None; qq = doc_query(q, docs or ai_kb.index_docs(db, c))
    passages = ai_kb.search(db, c, qq, 8, only_ids=only); a.used("documents", qq[:80])
    found = []
    for pz in passages:
        d = db.execute("SELECT * FROM ai_docs WHERE id=?", (pz["doc_id"],)).fetchone()
        for sc, p, s in di.answer(d["text"], qq, 2):
            if not any(s == x[3] for x in found):
                found.append((sc + pz["score"], d, p, s))
    if not found:
        return False
    found.sort(key=lambda z: -z[0]); a.say("From the approved documents:")
    for sc, d, p, s in found[:4]:
        a.say("> %s\n> \u2014 **%s** v%d, page %s" % (s[:420], d["title"], d["version"], p or "\u2013")); a.src(doc_src(d, p))
    a.say("*These are quotations, ranked by how well they match your question. If they do not answer it, the documents may not cover it: say so before relying on a conclusion.*")
    a.follow = ["Summarise %s" % found[0][1]["title"], "List the obligations in %s" % found[0][1]["title"]]
    return True


def h_compare(db, c, a, q, ctx, docs):
    d = docs[0] if docs else None
    if not d or not d["supersedes_id"]:
        a.say("That document has no earlier version to compare with. Upload a new version with the same title."); return
    old = db.execute("SELECT * FROM ai_docs WHERE id=?", (d["supersedes_id"],)).fetchone(); ch = di.compare(old["text"] or "", d["text"] or ""); a.used("document", "compare versions"); a.src(doc_src(d)); a.src(doc_src(old))
    a.say("**%s: version %d against version %d.** %d changed, %d new and %d removed statement(s)." % (d["title"], d["version"], old["version"], len(ch["changed"]), len(ch["added"]), len(ch["removed"])))
    nums = [x for x in ch["changed"] if x["numbers_changed"]]
    if nums:
        a.say("**Changed numbers or periods**\n" + "\n".join("- %s \u2192 %s: \u201C%s\u201D" % (", ".join(x["from"]) or "?", ", ".join(x["to"]) or "?", x["new"][:200]) for x in nums[:6]))
    if ch["new_duties"]:
        a.say("**New duties**\n" + "\n".join("- %s *(p.%s)*" % (s[:220], p or "\u2013") for p, s in ch["new_duties"][:6]))
    if ch["dropped_duties"]:
        a.say("**Duties dropped**\n" + "\n".join("- %s *(p.%s)*" % (s[:220], p or "\u2013") for p, s in ch["dropped_duties"][:4]))
    a.say("Use **Impact of the change** on the document to see which risks it may touch.")


# ------------------------------------------------------------------ draft risks and rate them from evidence
BASE_C = {"Fraud": 4, "Cyber": 4, "Technology": 4, "Regulatory": 4, "Third party": 3, "Financial": 3, "Operational": 3, "People": 3, "Reputational": 3, "Strategic": 3, "Model / AI": 3}
DEFAULT_CONS = {"Fraud": "Customer losses, complaints, regulatory scrutiny and loss of trust.", "Cyber": "Loss or exposure of data, service disruption, regulatory penalties and reputational damage.", "Technology": "Service downtime, failed transactions, customer dissatisfaction and revenue loss.", "Regulatory": "Fines, sanctions or licence conditions, remediation cost and reputational damage.", "Third party": "Service interruption, financial loss and difficulty switching supplier.", "Financial": "Funding pressure, losses and constrained operations.", "Operational": "Delays, errors, rework, customer impact and cost.", "People": "Loss of capability, errors and weakened controls.", "Reputational": "Loss of customer trust and stakeholder confidence.", "Strategic": "Missed objectives and lost opportunity.", "Model / AI": "Unfair or wrong outcomes and loss of trust in decisions."}
DEFAULT_KRI = {"Fraud": ["Fraud cases per week", "SIM replacement requests per outlet per week"], "Cyber": ["Critical vulnerabilities open", "Security incidents per month"], "Technology": ["Platform availability %", "Failed transaction rate"], "Regulatory": ["Overdue regulatory obligations", "Regulatory findings open"], "Third party": ["Suppliers without a tested continuity plan", "Supplier SLA breaches"], "Financial": ["Agent float shortages per day", "Liquidity buffer days"], "Operational": ["Reconciliation breaks open", "Processing backlog"], "People": ["Vacancies in critical roles", "Staff turnover %"], "Reputational": ["Customer complaints per week", "Negative media mentions"], "Strategic": ["Milestones delayed"], "Model / AI": ["Model accuracy and drift index"]}
DEFAULT_CTL = {"Fraud": [("Process", "Strong identity verification and a cooling-off period after account or SIM changes"), ("Systems", "Real-time fraud monitoring with velocity rules")], "Cyber": [("Technology", "Multi-factor authentication and least-privilege access"), ("Process", "Regular vulnerability scanning and patching with agreed deadlines")], "Technology": [("Technology", "Redundant platform with failover tested against the recovery objective"), ("Tools", "Availability monitoring with alerts")], "Regulatory": [("Process", "Obligations register with named owners and evidence"), ("People", "Compliance review before change goes live")], "Third party": [("Process", "Supplier criticality assessment and tested continuity plans"), ("Process", "Contract exit and step-in terms")], "Financial": [("Process", "Daily float and liquidity monitoring with rebalancing triggers"), ("Tools", "Early-warning dashboard")], "Operational": [("Process", "Documented procedure with maker-checker approval"), ("Tools", "Automated reconciliation")], "People": [("People", "Succession and cross-training for critical roles")], "Reputational": [("Process", "Crisis communication plan exercised twice a year")], "Strategic": [("Process", "Stage-gate review of milestones")], "Model / AI": [("Process", "Fairness and drift monitoring with human review")]}


def similar_to(db, c, text, n=5):
    """Register risks most like this text, with their ratings and assurance: the neighbours the rating is learned from."""
    s = ai.similar(db, c, text); rows, _ = scope_rows(db, c); by = {r["id"]: r for r in rows}; out = []
    for x in s["risks"][:n]:
        r = by.get(x["id"])
        if not r:
            continue
        inh = db.execute("SELECT inh_l, inh_c FROM risks WHERE id=?", (r["id"],)).fetchone()
        out.append({"row": r, "sim": x["similarity"], "inh_l": inh["inh_l"], "inh_c": inh["inh_c"], "res_l": r["res_l"], "res_c": r["res_c"], "loa": r["loa"], "ref": r["source_ref"] or r["ref"], "assessed": not r["needs_assessment"]})
    return out, s["controls"]


def reviewer_calibration(db, category):
    """What reviewers did to earlier drafts in this category: the average rank change they made. Used to lean the next draft, and shown when it is."""
    rows = db.execute("SELECT p.ai_values, p.final_values, p.payload FROM ai_proposals p WHERE p.kind='risk' AND p.status IN ('accepted','edited') AND p.model LIKE ?", (ENGINE_VERSION + "%",)).fetchall()
    diffs = []
    for r in rows:
        try:
            pay, a_, f_ = json.loads(r["payload"]), json.loads(r["ai_values"] or "{}"), json.loads(r["final_values"] or "{}")
            if pay.get("category") == category and a_.get("res_l") and f_.get("res_l"):
                diffs.append(mx.rank(f_["res_l"], f_["res_c"]) - mx.rank(a_["res_l"], a_["res_c"]))
        except (ValueError, KeyError, TypeError):
            pass
    return (sum(diffs) / len(diffs), len(diffs)) if len(diffs) >= 3 else (0.0, len(diffs))


def rate(db, c, text, category, learning=True):
    """Evidence-based rating. Returns the cells, a confidence, and the list of factors that produced it so a reviewer can check every step."""
    factors = []; t = text.lower()
    nb, ctl = similar_to(db, c, text); nb_ok = [n for n in nb if n["sim"] >= 0.2 and n["assessed"]]
    base_c = BASE_C.get(category, 3); cval = base_c; lval = 3.0
    factors.append("Starting point for a %s risk: consequence %d, likelihood 3 (EcoCash rubric)." % (category.lower(), base_c))
    if nb_ok:
        w = sum(n["sim"] for n in nb_ok); nc = sum(n["inh_c"] * n["sim"] for n in nb_ok) / w; nl = sum(n["inh_l"] * n["sim"] for n in nb_ok) / w
        cval = 0.4 * cval + 0.6 * nc; lval = 0.4 * lval + 0.6 * nl
        factors.append("Calibrated on %d similar risk(s) already rated in your register (%s): their inherent ratings average likelihood %.1f and consequence %.1f." % (len(nb_ok), ", ".join("%s %.0f%%" % (n["ref"], n["sim"] * 100) for n in nb_ok[:3]), nl, nc))
    if re.search(r"\b(customers?|all (?:users|agents|transactions|channels)|nationwide|platform.wide|every|regulator|licen[cs]e|fine[sd]?|penalt|public|media|national|wallets?)\b", t):
        cval += 1; factors.append("Consequence +1: the text points to customers, regulators or the whole platform.")
    if re.search(r"(?:us\$|\$|usd)\s?\d[\d,]*(?:\.\d+)?\s?(?:m\b|million|bn|billion)|\b\d{1,3},\d{3},\d{3}\b", t):
        cval += 1; factors.append("Consequence +1: a monetary amount of a million or more is mentioned.")
    if re.search(r"\b(limited|minor|single|isolated|few|small|low impact)\b", t):
        cval -= 1; factors.append("Consequence \u22121: the text describes a limited or isolated effect.")
    if re.search(r"\b(already|has occurred|have occurred|recurring|repeated|last year|twice|several times|frequent\w*|increasing|rising|most (?:fridays|days|weeks)|currently takes|ongoing)\b", t):
        lval += 1; factors.append("Likelihood +1: the text says it has already happened or is recurring.")
    if re.search(r"\b(rare|unlikely|never|no history|has not occurred)\b", t):
        lval -= 1; factors.append("Likelihood \u22121: the text says it is rare or has not occurred.")
    cat_inc = db.execute("SELECT COUNT(*) n FROM incidents WHERE deleted_at IS NULL AND lower(COALESCE(category,''))=lower(?) AND COALESCE(occurred_on, created_at) >= ?", (category, (dbm.today() - datetime.timedelta(days=365)).isoformat())).fetchone()["n"]
    ev_found = 0
    if cat_inc >= 3:
        lval += 1; ev_found += 1; factors.append("Likelihood +1: %d %s incidents were recorded in the last 12 months." % (cat_inc, category.lower()))
    inh_l = max(1, min(5, int(round(lval)))); inh_c = max(1, min(5, int(round(cval))))
    loa = sum(n["loa"] for n in nb_ok if n["loa"] is not None) / max(1, sum(1 for n in nb_ok if n["loa"] is not None)) if any(n["loa"] is not None for n in nb_ok) else None
    la = loa if loa is not None else 0.5
    factors.append("Controls: %s." % ("similar risks have an average level of assurance of %d%%" % round(la * 100) if loa is not None else "no similar rated risk to learn from, so assurance is assumed at 50%"))
    if re.search(r"\b(tested|independent(?:ly)?|automated|real.time|monitored|reviewed quarterly)\b", t):
        la += 0.1; factors.append("Assurance +10%: the text mentions tested, independent or automated controls.")
    if re.search(r"\b(no (?:tested )?(?:control|continuity|backup|failover|owner|plan)s?|weak|manual|untested|not tested|lack of|absence of|single.?source|no tested)\b", t):
        la -= 0.15; factors.append("Assurance \u221215%: the text describes weak, manual or untested controls.")
    la = max(0.2, min(0.9, la)); inh_rank = mx.rank(inh_l, inh_c); rrr = inh_rank * ((1 - la) + 0.04)
    best = None
    for l in range(1, inh_l + 1):
        for cc in range(1, inh_c + 1):
            k = (abs(mx.rank(l, cc) - rrr), -cc, l)
            if best is None or k < best[0]:
                best = (k, l, cc)
    res_l, res_c = best[1], best[2]
    factors.append("Residual: inherent rank %d \u00D7 (level of risk %.2f + 0.04) = %.1f, the nearest cell on the ranked matrix is %d\u00D7%d (rank %d)." % (inh_rank, 1 - la, rrr, res_l, res_c, mx.rank(res_l, res_c)))
    if learning:
        adj, n = reviewer_calibration(db, category)
        if n and abs(adj) >= 2:
            res_l = max(1, min(inh_l, res_l + (1 if adj > 0 else -1))); factors.append("Residual %s one step: reviewers changed %d earlier %s drafts by %+.1f rank points on average (learned from their decisions)." % ("raised" if adj > 0 else "lowered", n, category.lower(), adj))
    conf = 0.30 + 0.35 * (max([n["sim"] for n in nb_ok] or [0])) + 0.10 * min(1, len(nb_ok) / 3) + 0.08 * ev_found + (0.07 if re.search(r"\d", t) else 0)
    conf = round(max(0.25, min(0.78, conf)), 2)
    return {"inh_l": inh_l, "inh_c": inh_c, "res_l": res_l, "res_c": res_c, "confidence": conf, "factors": factors, "neighbours": nb_ok, "controls": ctl, "loa": la}


def clause_parts(s):
    cause = re.split(r"\b(?:because|due to|as a result of|caused by|since|owing to|so that|so)\b", s, maxsplit=1, flags=re.I)
    cons = re.split(r"\b(?:resulting in|leading to|could result in|may result in|would result in|which could|which may|and customers|means that|causing|so that)\b", s, maxsplit=1, flags=re.I)
    return (cause[1].strip(" ,.;") if len(cause) > 1 else None), (cons[1].strip(" ,.;") if len(cons) > 1 else None)


def title_of(s, cat):
    t = re.sub(r"^(?:\d+(?:\.\d+)*\.?\s+)?(?:the\s+(?:system|platform)\s+(?:shall|must|should)\s+)?", "", s.strip(), flags=re.I)
    t = re.split(r"[.;]", t)[0]
    t = (t[:118].rsplit(" ", 1)[0] if len(t) > 118 else t).strip(" ,")
    return t[:1].upper() + t[1:]


def draft_risks(db, c, user, text, source_title=None, source_doc=None, limit=6):
    """Drafts risks from text and stores them as PROPOSALS. Returns (proposals, notes)."""
    gs = None
    from . import ai_gov
    learning = ai_gov.settings(db).get("learning", True); cands = di.risk_candidates(text, limit * 2); notes = []; made = []; st = {"model": ENGINE_VERSION, "source_doc": source_doc, "proposed": 0, "proposal_ids": []}
    if not cands:
        return [], ["I did not find sentences that describe something that could go wrong. Describe the situation in more detail (what could fail, why, with what effect)."]
    for cand in cands:
        if len(made) >= limit:
            break
        s, cat = cand["sentence"], cand["category"]; sim = ai.similar(db, c, s); dup = next((x for x in sim["risks"] if x["similarity"] >= 0.5), None)
        if dup:
            notes.append("Skipped a duplicate: \u201C%s\u201D is already covered by [%s] %s (%d%% similar)." % (s[:90], dup["ref"], dup["title"][:60], round(dup["similarity"] * 100))); continue
        rt = rate(db, c, s, cat, learning); cause, cons = clause_parts(s)
        ctl = [{"statement": x["statement"][:200], "category": x["domain"] if x["domain"] in analytics.DOMAINS else "Process"} for x in rt["controls"][:3] if x.get("statement")] or [{"statement": t, "category": d} for d, t in DEFAULT_CTL.get(cat, [])][:2]
        owner = {"Fraud": "Head of Compliance and ML/CTF", "Cyber": "CISO", "Technology": "CTO", "Regulatory": "Head of Compliance and ML/CTF", "Third party": "Head of Procurement", "Financial": "CFO", "People": "People and Culture Head", "Reputational": "Head of Marketing & Communications", "Model / AI": "CTO"}.get(cat, "Head of Operations")
        payload = {"title": title_of(s, cat), "description": s, "category": cat, "root_cause": cause or "Not stated in the source: to be confirmed with the owner.", "consequences": cons or DEFAULT_CONS.get(cat, ""), "owner_role": owner, "inh_l": rt["inh_l"], "inh_c": rt["inh_c"], "res_l": rt["res_l"], "res_c": rt["res_c"], "emv_i": 0, "treatment": "Mitigate: strengthen the controls listed and monitor the indicators; confirm the owner and dates.",
                   "controls": ctl, "kris": DEFAULT_KRI.get(cat, [])[:3]}
        rationale = "Drafted by the built-in engine from the source sentence%s. How it was rated: %s Confidence is limited because this is a rule-based estimate: confirm cause, owner, exposure and the controls before accepting." % (" on page %s of %s" % (cand["page"], source_title) if cand["page"] and source_title else "", " ".join(rt["factors"]))
        evd = (["%s%s" % (source_title, " p.%s" % cand["page"] if cand["page"] else "")] if source_title else ["Source text"]) + ["[%s]" % n["ref"] for n in rt["neighbours"][:3]]
        out = ai_tools._store(db, c, "risk", payload, {"rationale": rationale[:2900], "confidence": rt["confidence"], "evidence": evd}, st)
        if "proposal_id" in out:
            made.append(out["proposal_id"])
    return made, notes


def review_rating(db, c, r):
    """Does the evidence around an existing risk support its current residual rating? Returns the finding and the suggested cell when it does not."""
    ev = evidence(db, c, r); inh = db.execute("SELECT inh_l, inh_c FROM risks WHERE id=?", (r["id"],)).fetchone(); cur = mx.rank(r["res_l"], r["res_c"]); adj = 0.0; reasons = []
    if ev["kris"]:
        add = min(3.0, 1.0 * len(ev["kris"])); adj += add; reasons.append("+%.1f: %d linked indicator(s) in alert (%s)." % (add, len(ev["kris"]), ", ".join(k["code"] for k in ev["kris"][:3])))
    if ev["incidents"] >= 2:
        adj += 1.5; reasons.append("+1.5: %d incidents against this risk in the last 12 months." % ev["incidents"])
    if ev["loss"] >= 100000:
        adj += 1.0; reasons.append("+1.0: recorded losses of %s in the last 12 months." % money(ev["loss"]))
    if ev["overdue"]:
        add = min(1.5, 0.5 * len(ev["overdue"])); adj += add; reasons.append("+%.1f: %d treatment action(s) overdue." % (add, len(ev["overdue"])))
    weak = [w for w in ev["weak_domains"] if w[1] < 0.5]
    if weak:
        adj += 1.0; reasons.append("+1.0: weak controls in %s (below 50%% effectiveness)." % ", ".join(w[0] for w in weak))
    if not ev["kris"] and not ev["incidents"] and not ev["overdue"] and r["loa"] is not None and r["loa"] >= 0.8:
        adj -= 1.0; reasons.append("\u22121.0: level of assurance %s is at or above target, with no indicator in alert, incident or overdue action." % pct(r["loa"]))
    suggested = max(1.0, min(float(mx.rank(inh["inh_l"], inh["inh_c"])), cur + adj)); best = None
    for l in range(1, inh["inh_l"] + 1):
        for cc in range(1, inh["inh_c"] + 1):
            k = (abs(mx.rank(l, cc) - suggested), -cc, l)
            if best is None or k < best[0]:
                best = (k, l, cc)
    sl, sc = best[1], best[2]; srank = mx.rank(sl, sc); change = srank != cur and (abs(srank - cur) >= 3 or mx.level(srank) != mx.level(cur))
    return {"current": (r["res_l"], r["res_c"], cur), "suggested": (sl, sc, srank), "inherent": (inh["inh_l"], inh["inh_c"]), "change": change, "reasons": reasons, "evidence": ev, "adjustment": adj}


def h_rate(db, c, a, q, ctx, refs):
    if not ai_tools.can(c, "risk_register", "edit"):
        a.say("You need permission to edit ratings to ask for rating proposals. I can still explain a rating: ask *Tell me about <risk>*."); return
    rows, _ = scope_rows(db, c)
    if not refs:
        refs = [r["source_ref"] or r["ref"] for r in sorted([r for r in rows if r["rrr"] is not None and register.position(r) in ("Above appetite", "Above tolerance")], key=lambda z: -z["rrr"])[:3]]
        if refs:
            a.say("You did not name a risk, so I reviewed the %d highest risks above appetite." % len(refs))
    if not refs:
        a.say("Name the risk to review, for example *Review the rating of ISMS 06*."); return
    st = {"model": ENGINE_VERSION, "proposed": 0, "proposal_ids": []}; a.used("rating review", ", ".join(refs))
    for ref in refs[:6]:
        r = find_risk(rows, ref)
        if not r:
            a.say("**%s**: not found among the risks you may see." % ref); continue
        f = review_rating(db, c, r); a.src(rec(r)); rr = r["source_ref"] or r["ref"]
        head = "**[%s]** current residual %d\u00D7%d (rank %d, %s)" % (rr, f["current"][0], f["current"][1], f["current"][2], mx.level(f["current"][2]).lower())
        if f["change"]:
            res = ai_tools._store(db, c, "rating", {"risk_ref": rr, "risk_id": r["id"], "inh_l": f["inherent"][0], "inh_c": f["inherent"][1], "res_l": f["suggested"][0], "res_c": f["suggested"][1], "was": {"res_l": r["res_l"], "res_c": r["res_c"], "rank": f["current"][2]}},
                                  {"rationale": "The evidence around this risk points to a residual rank of %d rather than %d. %s Weighing: %s" % (f["suggested"][2], f["current"][2], " ".join(f["reasons"]), "each factor is added to the current rank and the nearest cell on the ranked matrix is chosen. A reviewer should check each factor."), "confidence": 0.6 if len(f["reasons"]) >= 2 else 0.45, "evidence": [x for x in f["reasons"]][:6]}, st, risk_ref=rr)
            if "proposal_id" in res:
                a.proposals.append(res["proposal_id"])
            a.say(head + " \u2192 **proposed %d\u00D7%d (rank %d, %s)**.\n" % (f["suggested"][0], f["suggested"][1], f["suggested"][2], mx.level(f["suggested"][2]).lower()) + "\n".join("  - " + x for x in f["reasons"]))
        else:
            a.say(head + ": **the evidence supports the current rating**." + ("\n" + "\n".join("  - " + x for x in f["reasons"]) if f["reasons"] else " Nothing in the indicators, incidents, actions or controls argues for a change."))
    st["proposal_ids"] = list(a.proposals)
    if a.proposals:
        a.say("I made **%d proposal(s)**. Nothing has been changed: open **Drafts for approval** to accept, edit or reject. An accepted rating sends the risk back through review and approval." % len(a.proposals))
        a.follow = ["Which risks are above appetite and why?"]


def h_draft(db, c, a, q, ctx, docs, text_hint):
    if not ai_tools.can(c, "risk_register", "create"):
        a.say("You need permission to create risks to ask for risk drafts."); return
    src_text = ""; title = None; did = None
    if docs:
        d = docs[0]; src_text, title, did = d["text"], d["title"], d["id"]
    else:
        src_text = text_hint
    made, notes = draft_risks(db, c, c.user, src_text, title, did, limit=want_n(q, 6) if re.search(r"\b\d+\b", q) else 6); a.used("risk drafter", title or "description")
    if made:
        a.proposals += made; a.say("I read %s and drafted **%d risk proposal(s)**. Nothing has been added to the register." % ("**%s**" % title if title else "your description", len(made)))
        for pid in made:
            p = db.execute("SELECT payload, confidence FROM ai_proposals WHERE id=?", (pid,)).fetchone(); pl = json.loads(p["payload"])
            a.say("- **%s** (%s): inherent %d\u00D7%d (rank %d), residual %d\u00D7%d (rank %d), confidence %d%%" % (pl["title"][:100], pl["category"], pl["inh_l"], pl["inh_c"], mx.rank(pl["inh_l"], pl["inh_c"]), pl["res_l"], pl["res_c"], mx.rank(pl["res_l"], pl["res_c"]), round(p["confidence"] * 100)))
        a.say("Each draft shows **how it was rated** (the similar risks in your register, the evidence and the rubric) so you can check it. Accept, edit or reject in **Drafts for approval**.")
        a.follow = ["Which risks are above appetite and why?"]
    else:
        a.say("I did not draft any risk. " + " ".join(notes[:3]))
    for n in notes[:4]:
        if made:
            a.say("*%s*" % n)
    if docs:
        a.src(doc_src(docs[0]))


# ------------------------------------------------------------------ developments: what could this mean for us?
TOPICS = {
    "monetary": {"label": "Monetary policy and exchange rate", "rx": r"monetary policy|policy rate|interest rate|mpc|money supply|exchange rate|forex|\bfx\b|\bzig\b|zimbabwe gold|inflation|devalu|liquidity|currency|reserve requirement|bank rate", "cats": ["Financial", "Strategic", "Operational"], "kri": r"liquid|float|forex|exchange|inflation|funding|transaction value|cash", "weight": 3,
                "effect": "Funding and liquidity costs, customer cash-out and balance behaviour, foreign-exchange exposure on costs, and agent float can all move. Fraud pressure often rises when conditions tighten.", "actions": [("Review liquidity and float buffers against the new conditions", "Head of Risk", "14 days"), ("Re-run the funding and foreign-exchange stress scenarios", "CFO", "30 days")]},
    "payments_reg": {"label": "Payments and mobile-money regulation", "rx": r"directive|circular|payment system|mobile money|national payment|licen[cs]e|agent banking|transaction limit|fintech|wallet|trust account|e-?money|settlement", "cats": ["Regulatory", "Operational", "Technology"], "kri": r"regulat|complian|obligation|limit|agent", "weight": 3,
                     "effect": "New or changed requirements can require system changes, new limits, reporting, capital or trust-account arrangements, and carry penalties for late compliance.", "actions": [("Assess the requirement against current processes and assign owners", "Head of Compliance and ML/CTF", "14 days"), ("Add the obligation and its deadline to the obligations register", "Head of Compliance and ML/CTF", "7 days")]},
    "aml": {"label": "Anti-money-laundering and sanctions", "rx": r"money laundering|terrorist financing|\bfatf\b|esaamlg|grey list|sanction|suspicious transaction|\bkyc\b|due diligence|financial intelligence|\baml\b|\bcft\b", "cats": ["Regulatory", "Fraud"], "kri": r"aml|kyc|suspicious|sanction|complian", "weight": 3,
            "effect": "Stricter AML/CFT expectations raise onboarding, monitoring and reporting duties, and a poor assessment can affect correspondent and banking relationships.", "actions": [("Review KYC, monitoring and reporting controls against the new expectation", "Head of Compliance and ML/CTF", "30 days")]},
    "data": {"label": "Data protection and cyber law", "rx": r"data protection|personal (?:data|information)|privacy|breach notification|potraz|cdpa|cross.border|data subject|cyber (?:law|security act|crime)", "cats": ["Cyber", "Regulatory"], "kri": r"breach|data|privacy|incident|vulnerab", "weight": 3,
             "effect": "Changes to data protection duties alter consent, retention, transfer outside Zimbabwe, breach reporting time and the use of external processors (including AI services).", "actions": [("Review breach-notification and data-transfer procedures with the DPO", "Head of Compliance and ML/CTF", "21 days")]},
    "tax": {"label": "Tax and levies", "rx": r"\btax\b|levy|levies|zimra|\bvat\b|duty|intermediated money transfer|imtt|excise|withholding", "cats": ["Financial", "Regulatory", "Strategic"], "kri": r"revenue|transaction|volume|cost", "weight": 2,
            "effect": "Taxes on transfers and services change customer behaviour and transaction volumes, revenue, pricing and compliance workload.", "actions": [("Model the effect on transaction volumes and revenue", "CFO", "30 days")]},
    "fraud_cyber": {"label": "Fraud and cyber threats", "rx": r"sim.?swap|fraud|scam|phishing|ransomware|cyber|hack|malware|social engineering|account takeover|data breach|ddos", "cats": ["Fraud", "Cyber", "Technology"], "kri": r"fraud|sim|incident|vulnerab|phish|suspicious", "weight": 3,
                   "effect": "A new method or a surge in fraud and cyber attacks raises losses, complaints and regulatory attention, and may require tighter limits, checks and monitoring.", "actions": [("Check detection rules and limits against the new method", "Head of Compliance and ML/CTF", "7 days"), ("Brief outlets and agents on the new scam", "Head of Commercial", "14 days")]},
    "infra": {"label": "Power, network and infrastructure", "rx": r"load.?shedding|electricity|power (?:cut|outage|supply)|fibre|network outage|data cent|undersea cable|fuel shortage|grid", "cats": ["Technology", "Operational"], "kri": r"avail|outage|uptime|fuel|power", "weight": 2,
              "effect": "Power and network failures interrupt platforms, agents and customers, and stretch backup power and fuel.", "actions": [("Confirm backup power, fuel and failover cover for critical sites", "CTO", "14 days")]},
    "ai": {"label": "AI regulation and standards", "rx": r"\bai act\b|artificial intelligence|iso/?iec 42001|nist ai|\bai (?:regulation|governance|risk)\b|generative ai", "cats": ["Model / AI", "Regulatory"], "kri": r"model|ai\b|drift", "weight": 1,
           "effect": "New AI rules and standards affect how EcoCash may use AI, and the evidence it must keep (inventory, impact assessment, logging).", "actions": [("Check the AI inventory and governance controls against the change", "Head of Risk", "60 days")]},
    "supply": {"label": "Suppliers and supply chain", "rx": r"supplier|supply chain|shortage|import|port|customs|procurement|vendor", "cats": ["Third party", "Operational"], "kri": r"supplier|vendor|stock|lead", "weight": 2,
               "effect": "Supply disruptions delay equipment and services and raise cost.", "actions": [("Review single-source suppliers and stock of critical items", "Head of Procurement", "30 days")]},
}
UP = re.compile(r"\b(rais\w+|increas\w+|tighten\w*|hike\w*|new requirement|introduc\w+|impos\w+|penalt\w+|ban\w*|suspend\w*|shortage|surge|spike|crisis|restrict\w*|mandatory|stricter|devalu\w+)\b", re.I)
DOWN = re.compile(r"\b(reduc\w+|eas\w+|relax\w+|remov\w+|lower\w*|cut\w*|waiv\w+|suspension lifted|scrap\w+|extend\w* deadline)\b", re.I)
INTENSE = re.compile(r"\b(immediate\w*|with immediate effect|effective (?:immediately|today|monday)|mandatory|penalt\w+|ban\w*|suspend\w*|revok\w+|sharp\w*|crisis|critical|emergency|\d+\s?(?:percentage )?points?|by \d+\s?%)\b", re.I)


def impact_of(db, c, title, text):
    """Impact analysis of a development on EcoCash, in the same shape the Claude engine produces, built from your register."""
    body = (title or "") + ". " + (text or ""); low = body.lower(); hits = []
    for k, t in TOPICS.items():
        n = len(re.findall(t["rx"], low))
        if n:
            hits.append((n * t["weight"], k))
    hits.sort(reverse=True); topics = [k for _, k in hits[:2]]
    rows, _ = scope_rows(db, c); a_ = [r for r in rows if r["rrr"] is not None]; vecs, idf = ai.vectors([(r["title"] or "") + " " + (r["category"] or "") + " " + (r["dept"] or "") for r in rows]) if rows else ([], {})
    q = ai.qvec(body, idf) if rows else {}; scored = {}
    for r, v in zip(rows, vecs):
        s = ai.cos(q, v) if q else 0
        if topics and r["category"] in sum((TOPICS[t]["cats"] for t in topics), []):
            s += 0.25
        if s >= 0.15:
            scored[r["id"]] = (s, r)
    ranked = sorted(scored.values(), key=lambda z: -(z[0] + (z[1]["rrr"] or 0) / 100))[:6]
    direction = "increase" if len(UP.findall(body)) >= len(DOWN.findall(body)) else "decrease"
    affected = [{"ref": r["source_ref"] or r["ref"], "direction": direction, "reason": "%s risk (%s), residual %s; %s." % (r["category"] or "n/a", r["dept"], "n/a" if r["rrr"] is None else "%.1f" % r["rrr"], "similar subject matter to the development" if s < 0.4 else "closely matches the development"), "suggested_review": "Review the %s rating and the controls against this development." % ("residual" if r["rrr"] is not None else "initial")} for s, r in ranked]
    kris = []
    for t in topics:
        for k in db.execute("SELECT code, name FROM kpis WHERE active=1 AND deleted_at IS NULL AND kind='kri'"):
            if re.search(TOPICS[t]["kri"], (k["name"] or "").lower()) and len(kris) < 5:
                kris.append({"code": k["code"], "effect": "Watch closely: %s may move because of this development." % k["name"]})
    sev = max([TOPICS[t]["weight"] for t in topics] or [1]) + (1 if INTENSE.search(body) else 0) + (1 if any(register.position(r) in ("Above appetite", "Above tolerance") for _, r in ranked) else 0) - (1 if direction == "decrease" else 0)
    sev = max(1, min(5, sev)); horizon = "immediate" if re.search(r"immediate|effective (?:today|monday)|within 30 days|with effect from", low) else "12 months" if topics and topics[0] in ("ai",) else "3 months"
    acts = []
    for t in topics:
        acts += [{"action": a_, "owner_role": o, "timing": tm} for a_, o, tm in TOPICS[t]["actions"]]
    if not topics:
        acts = [{"action": "Read the source and decide whether it touches any objective, risk or obligation", "owner_role": "Head of Risk", "timing": "7 days"}]
    effect = " ".join(TOPICS[t]["effect"] for t in topics) or "I could not match this development to a known theme, so I cannot say how it affects EcoCash."
    conf = round(min(0.65, 0.3 + 0.1 * len(ranked) + 0.1 * len(topics) + (0.05 if len(body) > 400 else 0)), 2)
    return {"headline": (title or "Development")[:140], "why_it_matters": ("Themes detected: %s. " % ", ".join(TOPICS[t]["label"] for t in topics) if topics else "") + effect, "severity": sev, "time_horizon": horizon, "affected_risks": affected, "kri_kpi_effects": kris,
            "financial_effect": "Qualitative only: the built-in engine does not estimate amounts. Ask the Treasury and Finance teams for a figure, then record it as an assumption.", "recommended_actions": acts[:4],
            "assumptions": ["The development is as reported by the source and takes effect as described.", "Direction is read from the wording (%s); a reviewer should confirm it." % direction], "unknowns": ["How customers, agents and counterparties will actually react.", "Whether further measures follow."], "confidence": conf,
            "what_would_change_this": ["A reversal or clarification by the authority.", "Evidence from EcoCash's own transaction and float data."], "engine": ENGINE_VERSION, "topics": topics}


def h_impact(db, c, a, q, ctx):
    r = impact_of(db, c, q[:120], q); a.used("impact analysis", ", ".join(r["topics"]) or "no theme")
    a.say("**Impact analysis** (severity **%d/5**, horizon %s, confidence %d%%). *Prepared by rule from your register: not verified.*" % (r["severity"], r["time_horizon"], round(r["confidence"] * 100)))
    a.say("**Why it matters.** " + r["why_it_matters"])
    if r["affected_risks"]:
        a.say("**Risks it may affect**\n" + "\n".join("- **[%s]** %s: %s" % (x["ref"], x["direction"], x["reason"]) for x in r["affected_risks"]))
    if r["kri_kpi_effects"]:
        a.say("**Indicators to watch**\n" + "\n".join("- **%s**: %s" % (x["code"], x["effect"]) for x in r["kri_kpi_effects"]))
    a.say("**Suggested actions**\n" + "\n".join("- %s (%s, %s)" % (x["action"], x["owner_role"], x["timing"]) for x in r["recommended_actions"]))
    a.say("**What we do not know.** " + " ".join(r["unknowns"]) + " For a recorded analysis, use **Horizon \u2192 Analyse a development**.")
    rows, _ = scope_rows(db, c)
    for x in r["affected_risks"][:4]:
        rr = find_risk(rows, x["ref"])
        if rr:
            a.src(rec(rr))
    a.follow = ["Search the web for the latest on this", "Which risks are above appetite and why?"]


# ------------------------------------------------------------------ the web
def h_web(db, c, a, q, ctx, allowed, auto=False):
    qq = re.sub(r"(?i)^(please\s+)?(can you\s+)?(search|google|look up|find|browse|research)(\s+(the\s+)?(web|internet|online|google))?(\s+for)?\s*", "", q).strip() or q
    links = ai_web.browser_links(qq)
    a.web = {"query": qq, "links": links, "results": [], "errors": {}}
    if not allowed:
        a.say("Web research is **off** (it needs Advanced mode and the web capability, switched on by a System Administrator). You can still search yourself:"); a.say("[Search Google](%s) \u00B7 [DuckDuckGo](%s) \u00B7 [Bing](%s)" % (links["google"], links["duckduckgo"], links["bing"])); return
    res = ai_web.search(db, qq, use_cache=True)
    toks = [w for w in re.findall(r"[a-z0-9]{4,}", qq.lower()) if w not in ("what", "when", "where", "which", "today", "latest", "current", "about", "tell", "please", "would", "could", "price", "with", "from", "this", "that", "have", "does")]
    if toks:  # keep only results that really are about the question (a search for "price of gold today" must not return a pop album)
        need_n = max(1, (len(toks) + 2) // 3)
        res["results"] = [x for x in res["results"] if x.get("trusted") or sum(1 for w in toks if w in (x["title"] + " " + x["snippet"]).lower()) >= need_n]
    a.web.update({"results": res["results"], "errors": res["errors"], "used": res["used"]}); a.used("web search", qq)
    if not res["results"]:
        a.say("I could not get results for **%s**. %s" % (qq, " ".join("%s: %s." % (k, v) for k, v in res["errors"].items())))
        a.say("Open the search in your own browser: [Google](%s) \u00B7 [DuckDuckGo](%s) \u00B7 [Bing](%s)" % (links["google"], links["duckduckgo"], links["bing"])); a.follow = ["What is monetary policy and why does it matter to EcoCash?"]; return
    a.say(("I looked this up on the web on my own, because it is outside what Sentinel holds. " if auto else "") + "I searched **%s** through %s%s. Results (approved sources first):" % (qq, " and ".join(res["used"]), " (answer kept from the last few hours)" if res.get("cached") else ""))
    a.say("\n".join("%d. **%s** \u2014 %s%s\n   %s" % (i + 1, x["title"][:110], x["domain"], " (approved source)" if x["trusted"] else " (not on the approved list)", x["snippet"][:220]) for i, x in enumerate(res["results"][:8])))
    for x in res["results"][:8]:
        a.src({"type": "web", "url": x["url"], "title": x["title"][:120], "trusted": x["trusted"], "cited_text": x["snippet"][:200], "retrieved": now()})
    read = [x for x in res["results"] if x["trusted"]][:2]; said = []
    for x in read:
        try:
            pg = ai_web.read_page(db, x["url"], False)
        except ai_web.WebError:
            continue
        if pg["flags"]:
            a.flags += pg["flags"]
        for sc, p, s in di.answer(pg["text"], qq, 2):
            said.append((s, pg))
    if said:
        a.say("**What the approved sources say**\n" + "\n".join("> %s\n> \u2014 %s (%s)" % (s[:380], pg["title"][:80], ai_web_domain(pg["url"])) for s, pg in said[:3])); a.used("web page read", read[0]["url"])
    for k, v in res["errors"].items():
        a.say("*%s could not be searched: %s.*" % (k, v))
    a.say("Open the same search in your own browser: [Google](%s) \u00B7 [DuckDuckGo](%s) \u00B7 [Bing](%s). Check any source yourself before relying on it." % (links["google"], links["duckduckgo"], links["bing"]))
    a.follow = ["What would this mean for our risks? Analyse the impact", "Which risks are above appetite and why?"]


def h_world(db, c, a, q, ctx, allowed):
    """What is happening now: top headlines, and which of them touch EcoCash's risk themes. Headlines name their publisher; approved publishers are marked."""
    links = ai_web.browser_links("news today"); a.web = {"query": "top stories", "links": links, "results": [], "errors": {}}
    if not allowed:
        a.say("Web research is **off** (it needs Advanced mode and the web capability, switched on by a System Administrator). You can read the news yourself: [Google News](https://news.google.com) \u00B7 [BBC News](https://www.bbc.com/news)."); return
    out = ai_web.headlines(db); items = out["items"]; a.used("headlines", "top stories")
    if not items:
        a.say("I could not get the headlines. %s" % " ".join("%s: %s." % kv for kv in out["errors"].items())); a.say("Open them in your own browser: [Google News](https://news.google.com) \u00B7 [BBC News](https://www.bbc.com/news)."); return
    a.auto_web = True; a.web["results"] = items[:10]
    a.say("I fetched the latest headlines on my own%s. **Top stories now:**" % (" (kept from the last hour)" if out.get("cached") else ""))
    a.say("\n".join("- %s \u2014 **%s**%s%s" % (x["title"][:130], x.get("source") or x["domain"], " (approved source)" if x["trusted"] else "", " \u00B7 " + x["published"][:16] if x.get("published") else "") for x in items[:10]))
    for x in items[:10]:
        a.src({"type": "web", "url": x["url"], "title": x["title"][:120], "trusted": x["trusted"], "cited_text": (x.get("snippet") or "")[:160], "retrieved": now()})
    rel = []
    for x in items:
        j = impact_of(db, c, x["title"], x.get("snippet") or "")
        if j["topics"]:
            rel.append((j["severity"], x, j))
    rel.sort(key=lambda z: -z[0])
    if rel:
        a.say("**Touching EcoCash's risk themes** (rule-based, not verified)\n" + "\n".join("- %s: *%s*, severity %d/5%s" % (x["title"][:110], ", ".join(TOPICS[t]["label"] for t in j["topics"]), s, "; may affect " + ", ".join("[%s]" % r["ref"] for r in j["affected_risks"][:2]) if j["affected_risks"] else "") for s, x, j in rel[:5]))
        a.follow = ["How could %s affect us?" % rel[0][1]["title"][:90], "Which risks are above appetite and why?"]
    a.say("Headlines are from the publishers named; open one to read it all. [Open Google News](https://news.google.com)")


PRICE_WORDS = [("gold", "GOLD"), ("platinum", "PLATINUM"), ("palladium", "PALLADIUM"), ("silver", "SILVER"), ("copper", "COPPER"), ("brent", "BRENT"), ("crude", "BRENT"), ("oil", "BRENT"), ("wti", "WTI"),
               ("wheat", "WHEAT"), ("corn", "CORN"), ("cocoa", "COCOA"), ("cotton", "COTTON"), ("tether", "PEG_USDT"), ("usdt", "PEG_USDT"), ("usdc", "PEG_USDC"), ("euro", "FX_EUR"), ("eur", "FX_EUR"),
               ("pound", "FXD_GBP"), ("gbp", "FXD_GBP"), ("rand", "FXD_ZAR"), ("zar", "FXD_ZAR"), ("pula", "FXD_BWP"), ("zig", "FX_INTERBANK"), ("zwg", "FX_INTERBANK"), ("interbank", "FX_INTERBANK"), ("exchange rate", "FX_INTERBANK")]


def h_price(db, c, a, text):
    """'What is the price of gold today?' and similar: answered from the live market feed, with the source and the time. True if answered."""
    t = text.lower()
    if not re.search(r"\b(price|prices|rate|rates|worth|cost|trading|how much|spot|quote)\b", t):
        return False
    code = next((cd for w, cd in PRICE_WORDS if re.search(r"\b" + re.escape(w) + r"\b", t)), None)
    if not code:
        return False
    from . import live_data
    out, errs = live_data.fetch_all([code])
    if code in out:
        a.used("live market data", code)
        v, ts, src = out[code]
        name = (live_data.COMMODITIES.get(code) or (None, None, None, None, code))[4]
        unit = (live_data.COMMODITIES.get(code) or (None, None, None, "", ""))[3]
        k = db.execute("SELECT name, unit FROM kpis WHERE code=?", (code,)).fetchone()
        if k:
            name, unit = k["name"], k["unit"] or unit
        a.say("**%s: %s %s** (as at %s, from %s)." % (name, ("{:,.4f}".format(v).rstrip("0").rstrip(".") if v < 100 else "{:,.2f}".format(v)), unit or "", (ts or core_now())[:16], src))
        a.say("Live market figure from a public data service, not an EcoCash or Bloomberg quote. It is also in the Weekly KPI report, where it updates by itself while the computer is online.")
        a.follow = ["How could this affect our risks?", "Which KPIs track commodity prices?"]
        return True
    return False  # the live feed is unreachable: carry on with the ordinary answer and the web search


def core_now():
    import datetime
    return datetime.datetime.now().isoformat(timespec="minutes")


def auto_web(db, c, a, text, ctx):
    """Outside the system, or about now: go to the web without being asked. True if it found something."""
    before = len(a.parts); h_web(db, c, a, text, ctx, True, auto=True)
    ok = bool(a.web and a.web.get("results"))
    if ok:
        a.auto_web = True
    else:
        errs = (a.web or {}).get("errors") or {}; links = (a.web or {}).get("links") or ai_web.browser_links(text); del a.parts[before:]
        a.web_note = "*I also tried to look this up on the web on my own, but could not get results%s. Open the search yourself: [Google](%s) \u00B7 [DuckDuckGo](%s) \u00B7 [Bing](%s).*" % (" (" + "; ".join("%s: %s" % kv for kv in list(errs.items())[:2]) + ")" if errs else "", links["google"], links["duckduckgo"], links["bing"]); a.web_failed = True
    return ok


WORLD = re.compile(r"\b(latest|today|tonight|this (?:week|month|year)|current(?:ly)?|news|headlines?|recent(?:ly)?|happening|breaking|update on|updates on|what'?s going on|who (?:is|was|won)|how much is|price of|rate of|exchange rate|inflation|election|president|governor|minister|war|announce\w*|2026|2027)\b", re.I)


def ai_web_domain(url):
    from . import ai_gov
    return ai_gov.domain_of(url)


# ------------------------------------------------------------------ the front door
def classify(q, ctx, has_docs, web_on, web_flag):
    ql = q.lower().strip(); refs = refs_in(q)
    if re.match(r"^(hi|hello|hey|good (morning|afternoon|evening))\b[\s!.,]*$", ql) or re.search(r"\b(what can you do|how can you help|who are you|help me|what do you do|capabilities)\b", ql):
        return "help", refs
    if re.search(r"\b(?:what'?s|what is) (?:happening|going on)(?: (?:in the world|around the world|globally|out there|in the news))?(?: (?:now|today|this week))?\s*[?.!]*$|\b(world news|headlines|top stories|news today|news this week|in the news|latest news)\s*[?.!]*$", ql):
        return "world", refs
    if re.search(r"\b(search (?:the )?(?:web|internet|online|google)|google|look (?:it )?up online|latest news|news (?:on|about)|find online|browse|on the internet|what is happening|what's happening|current (?:news|situation))\b", ql):
        return "web", refs
    if re.search(r"\bhow (?:could|would|will|might|does|do|can)\b.{0,90}?\b(?:affect|impact)\b|\b(?:affect|impact|implications?|effect)\b.{0,60}\b(?:on us|on ecocash|for us|our (?:risks?|business|operations)|to us)\b|\banalyse the impact\b|\bimpact analysis\b|\bwhat does this mean for (?:us|ecocash)\b", ql):
        return "impact", refs
    if re.search(r"\b(draft|create|propose|identify|generate|prepare|do|carry out|perform|conduct)\b.*\b(risk assessment|risks?|assessment)\b", ql) and (has_docs or re.search(r"\b(from|based on|using|for)\b", ql)) and not re.search(r"\b(above|which|how many|list|show)\b", ql):
        return "draft", refs
    if re.search(r"\b(rate|re-?rate|reassess|re-?assess|review the rating|review the ratings|check the rating|propose a rating|should (?:it|this|the risk) be rated|is the rating (?:right|correct))\b", ql) and (refs or re.search(r"\b(risks?|ratings?)\b", ql)) and not re.search(r"\b(what is|what's|define|explain|why)\b", ql):
        return "rate", refs
    if re.search(r"\b(summari[sz]e|summary|key points|main points|tl;?dr|overview of the)\b", ql) and (has_docs or re.search(r"\b(policy|document|brd|directive|regulation|standard|report|paper)\b", ql)):
        return "doc_summary", refs
    if re.search(r"\b(obligations?|duties|requirements|deadlines)\b", ql) and (has_docs or re.search(r"\b(policy|document|brd|directive|regulation|standard)\b", ql)):
        return "obligations", refs
    if re.search(r"\b(what changed|changes? (?:in|between)|compare|difference between versions|new version)\b", ql) and (has_docs or re.search(r"\b(policy|document|version|regulation|directive)\b", ql)):
        return "compare", refs
    if re.search(r"(?:above|over|outside|exceed\w*|beyond|breach\w*) (?:the )?(?:risk )?(?:appetite|tolerance|threshold|limit)", ql):
        return "above", refs
    if re.search(r"\b(top|highest|biggest|most (?:serious|critical|significant)|worst|greatest)\b.*\brisks?\b", ql):
        return "top", refs
    if re.search(r"(?:controls?)\s+(?:for|of|on|protecting|linked to)\b", ql) and (refs or ctx.get("ref")):
        return "controls_for", refs or [ctx["ref"]]
    if not refs and not ctx.get("ref") and re.search(r"\b(?:controls?\s+(?:for|of|on)|tell me (?:more )?about|explain|why is|rate|rating of)\b.{0,12}\b(?:it|this|that|this risk|that risk|the risk)\b\s*\??\s*$", ql):
        return "clarify", refs
    if refs and not re.search(r"\b(rate|rating)\b", ql):
        return "risk", refs
    if re.search(r"\b(this|that|it|the) (?:risk|one)\b", ql) and ctx.get("ref") and re.search(r"\b(tell me|explain|why|detail|more|about)\b", ql):
        return "risk", [ctx["ref"]]
    if re.search(r"\b(weak|failed|failing|ineffective|untested|no owner|without (?:an )?owner|unowned)\b.*\bcontrols?\b|\bcontrols?\b.*\b(fail\w*|weak|effectiveness|tests?|tested|owners?)\b", ql) and not re.search(r"\b(policy|grc|document)\b", ql):
        return "controls_status", refs
    if re.search(r"\b(actions?|issues?|tasks?|to.?dos?)\b", ql) and re.search(r"\b(overdue|late|open|status|owner|due|escalat\w*|list|which|how many|show|pending)\b", ql):
        return "actions", refs
    if re.search(r"\b(kri|kris|kpi|kpis|indicators?|alerts?|off.?target|amber|red)\b", ql):
        return "kpi", refs
    if re.search(r"\b(incidents?|loss events?|losses|near misses?)\b", ql):
        return "incidents", refs
    if re.search(r"\b(strategic objectives?|coverage|objectives? covered)\b", ql):
        return "coverage", refs
    if re.search(r"\b(what changed|changes? since|recently (?:changed|updated)|latest updates?|what'?s new|movement)\b", ql):
        return "changes", refs
    if re.search(r"\b(summary|summari[sz]e|overview|position|how are we|how is (?:the )?risk|status of (?:our )?risk|board|dashboard|state of)\b", ql) and re.search(r"\b(risk|position|board|portfolio|we|our)\b", ql):
        return "overview", refs
    if re.search(r"\b(policy|grc|procedure|regulation|directive|standard|document|brd|manual)\b", ql) and re.search(r"\b(say|says|state|states|require|requires|about|according|provide|provides|define|defines|rule|rules|what)\b", ql):
        return "doc_qa", refs
    if re.match(r"^(what|who|why|how|define|explain|difference|meaning|tell me about)\b", ql) or re.search(r"\b(what is|what are|define|meaning of|explain)\b", ql):
        return "define", refs
    return "fallback", refs


def context_of(history, risk_ref):
    ctx = {"ref": None}
    if risk_ref:
        ctx["ref"] = risk_ref
    for m in reversed(history or []):
        if m.get("role") == "assistant":
            for s in (m.get("sources") or []):
                if isinstance(s, dict) and s.get("type") == "record" and s.get("kind") == "risk":
                    ctx["ref"] = ctx["ref"] or s.get("ref")
            break
    for m in reversed(history or []):
        if m.get("role") == "user" and refs_in(m.get("content", "")):
            ctx["ref"] = ctx["ref"] or refs_in(m["content"])[0]; break
    return ctx


def respond(db, c, text, history=None, doc_ids=None, web=False, risk_ref=None, web_allowed=False, extra_docs=None, autonomous=False):
    """The answer to one question. Never raises for a question it cannot answer: it says so and suggests what to ask."""
    ctx = context_of(history, risk_ref); docs = pick_docs(db, c, text, doc_ids) if (doc_ids or re.search(r"\b(policy|grc|brd|document|regulation|directive|standard|version|summari[sz]e|obligations?)\b", text, re.I)) else []
    intent, refs = classify(text, ctx, bool(doc_ids), web_allowed, web)
    a = A(intent)
    try:
        if intent not in ("help",) and not doc_ids and h_price(db, c, a, text):
            pass
        elif intent == "help":
            h_help(db, c, a, text, ctx)
        elif intent == "web":
            h_web(db, c, a, text, ctx, web_allowed)
        elif intent == "world":
            h_world(db, c, a, text, ctx, web_allowed)
        elif intent == "clarify":
            a.say("Which risk do you mean? Give its reference as shown in the register, for example **ISMS 06** or **BCMS 15**, or ask *Which risks are above appetite?* first and I will remember the one we are talking about.")
            a.follow = ["Which risks are above appetite and why?", "Top 5 risks"]
        elif intent == "impact":
            h_impact(db, c, a, text, ctx)
        elif intent == "draft":
            h_draft(db, c, a, text, ctx, docs if doc_ids or docs else [], text)
        elif intent == "rate":
            h_rate(db, c, a, text, ctx, refs or ([ctx["ref"]] if ctx.get("ref") and re.search(r"\b(it|this|that)\b", text, re.I) else []))
        elif intent == "doc_summary":
            h_doc_summary(db, c, a, text, ctx, docs)
        elif intent == "obligations":
            h_obligations(db, c, a, text, ctx, docs)
        elif intent == "compare":
            h_compare(db, c, a, text, ctx, docs)
        elif intent == "above":
            h_above(db, c, a, text, ctx)
        elif intent == "top":
            h_top(db, c, a, text, ctx)
        elif intent == "controls_for":
            h_controls_for(db, c, a, text, ctx, refs[0])
        elif intent == "risk":
            h_risk(db, c, a, text, ctx, refs[0])
        elif intent == "controls_status":
            h_controls_status(db, c, a, text, ctx)
        elif intent == "actions":
            h_actions(db, c, a, text, ctx)
        elif intent == "kpi":
            h_kpi(db, c, a, text, ctx)
        elif intent == "incidents":
            h_incidents(db, c, a, text, ctx)
        elif intent == "coverage":
            h_coverage(db, c, a, text, ctx)
        elif intent == "changes":
            h_changes(db, c, a, text, ctx)
        elif intent == "overview":
            h_overview(db, c, a, text, ctx)
        elif intent == "doc_qa":
            if not h_doc_qa(db, c, a, text, ctx, docs):
                if not h_define(db, c, a, text, ctx):
                    a.say("I could not find that in the approved documents. Upload and approve the document in **Sentinel Copilot > Documents**, or rephrase with the words the document would use.")
        elif intent == "define":
            if not (h_define(db, c, a, text, ctx) or h_doc_qa(db, c, a, text, ctx, docs) or h_search(db, c, a, text, ctx)):
                if not (autonomous and web_allowed and auto_web(db, c, a, text, ctx)):
                    fallback(db, c, a, text)
            elif autonomous and web_allowed and not web and WORLD.search(text) and not refs:
                a.say("**Latest from the web** (looked up automatically)"); auto_web(db, c, a, text, ctx)
        else:
            if not (h_define(db, c, a, text, ctx) or h_search(db, c, a, text, ctx) or h_doc_qa(db, c, a, text, ctx, docs)):
                if not (autonomous and web_allowed and auto_web(db, c, a, text, ctx)):
                    fallback(db, c, a, text)
        if web and web_allowed and intent in ("define", "fallback") and not refs:  # the person ticked 'search the web too': add what the web says to the answer
            a.say("**From the web**"); h_web(db, c, a, text, ctx, True)
    except Exception as e:  # a bug in one handler must not lose the person's question
        a.say("I hit a problem while working on that (%s). Try rephrasing, or use the search and filters." % str(e)[:100]); a.flags.append("engine error")
    return a.out()


def fallback(db, c, a, text):
    a.say("I could not answer that from the register, the approved documents or my reference pack. I would rather say so than guess. Try asking about a **risk** (for example *Tell me about ISMS 06*), a **document** (*What does the GRC Policy say about control effectiveness?*), a **concept** (*What is residual risk?*), or ask me to **search the web**.")
    a.follow = ["Which risks are above appetite and why?", "What is residual risk?", "Summarise our risk position for the Board in five points."]


def analyse(db, c, d, task, question=""):
    """One document task (summary, obligations, risks, questions, compare) as a finished answer."""
    a = A("doc_" + task); docs = [d]
    if task == "summary":
        h_doc_summary(db, c, a, "summarise", {}, docs)
    elif task == "obligations":
        h_obligations(db, c, a, "obligations", {}, docs)
    elif task == "compare":
        h_compare(db, c, a, "compare", {}, docs)
    elif task == "questions":
        if not h_doc_qa(db, c, a, question or "summary", {}, docs):
            a.say("The document does not appear to answer that. Try the words the document would use.")
    else:  # risks: analysis only, no proposals
        cands = di.risk_candidates(d["text"], 8); a.used("document", "risk candidates"); a.src(doc_src(d))
        if not cands:
            a.say("I did not find sentences describing something that could go wrong in **%s**." % d["title"])
        else:
            a.say("**%d statement(s) in %s describe risks.** Each is shown with the category I would give it:" % (len(cands), d["title"]))
            a.say("\n".join("- **%s** *(p.%s)*: %s" % (x["category"], x["page"] or "\u2013", x["sentence"][:220]) for x in cands)); a.say("To turn them into rated drafts for review, use **Assess**.")
    return a.out()
