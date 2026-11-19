"""Document intelligence that runs on this computer with no model and no cost: it reads a document the way a careful analyst skims it, and every result points to a
page. It is extractive (it selects and organises the document's own sentences, it does not invent wording), which is why it can be trusted to quote: summaries
(TextRank over sentence similarity), obligations (who must do what, by when), key facts (dates, amounts, percentages, periods), answers to questions, a narrative of what
changed between two versions, and the sentences that describe risks."""
import re

from . import ai, ai_kb

SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(\[\u201c\"])")
MODAL = re.compile(r"\b(shall|must|is required to|are required to|is responsible for|are responsible for|should|needs? to|has to|have to|will be required to|obliged to|may not|shall not|must not)\b", re.I)
PERIOD = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|twenty[- ]four|thirty|sixty|ninety)\s*(?:\(\d+\)\s*)?(?:calendar\s+|working\s+|business\s+)?(?:hours?|days?|weeks?|months?|years?)"
DEADLINE = re.compile(r"\b(?:within|no later than|not later than|by|before|at least|every|each|once|after)\s+(?:the\s+)?(?:" + PERIOD + r"|annually|quarterly|monthly|weekly|daily|year|quarter|month|end of (?:the )?(?:year|quarter|month))\b|\b(?:annually|quarterly|monthly|weekly|daily|immediately|without delay|as soon as practicable)\b", re.I)
THEMES = [("Reporting and escalation", r"report|escalat|notify|inform|disclos|submit"), ("Governance and approval", r"board|committee|approv|oversight|mandate|accountab|delegat"), ("Risk assessment", r"risk assess|appetite|tolerance|rating|register|treatment|identify"), ("Controls and testing", r"control|test|assur|audit|monitor|review|attest"),
          ("Incidents and breaches", r"incident|breach|loss event|near miss|investigat"), ("Compliance and regulation", r"complian|regulat|licen|law|statut|aml|kyc|directive|obligation"), ("Information and data", r"data|information|privacy|personal|confidential|record|retention|access"),
          ("Continuity and resilience", r"continuity|recover|disaster|resilien|backup|failover|crisis"), ("People and training", r"train|competen|awareness|staff|employee|conduct|whistle")]
CATS = {"Fraud": r"fraud|scam|sim.?swap|impersonat|account takeover|collusion|theft|misappropriat|social engineering|forg", "Cyber": r"cyber|breach|unauthori[sz]ed|malware|phishing|ransomware|vulnerab|intrusion|hack|encrypt|access control|credential|data leak",
        "Technology": r"outage|downtime|availab|platform|system fail|latency|capacity|failover|single point|data cent|software|release|patch|integration|infrastructure|network", "Regulatory": r"regulat|complian|directive|licen[cs]|penalt|fine[sd]?\b|aml|kyc|circular|non.?complian|statutory|breach of (?:law|regulation)",
        "Third party": r"supplier|vendor|third.?part|outsourc|contractor|service level|sla\b|single.?source", "Financial": r"liquidity|funding|currency|exchange rate|inflation|interest rate|credit|settlement|float|revenue|budget|cash", "People": r"staff|skills|key.?person|attrition|succession|culture|conduct|vacan|training",
        "Reputational": r"reputation|brand|media|customer trust|complaint|public confidence", "Strategic": r"strateg|market share|competit|growth|launch|partnership|innovation", "Model / AI": r"\bmodel\b|algorithm|\bai\b|bias|drift|machine learning|automated decision", "Operational": r"process|manual|error|reconcil|delay|backlog|fulfil|capacity|workaround|handover"}
TRIGGER = re.compile(r"\b(risk|fail\w*|breach\w*|outage|downtime|fraud\w*|non.?complian\w*|penalt\w*|loss(?:es)?|shortage|delay\w*|dependen\w+|vulnerab\w*|unauthori[sz]ed|error\w*|incident\w*|threat\w*|exposure|disrupt\w*|unavailab\w*|exceed\w*|cannot|unable|may result|could result|might|inadequate|weak\w*|lack of|absence of|untested|single point|single.?source|no tested|not tested|short of|run short|runs short|takes? (?:\d+|three|four|five|six|twelve|seventy)[\w -]*(?:hours|days)|no (?:continuity|backup|failover|owner|control)s?)\b", re.I)
HEADERISH = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?[A-Z][A-Za-z /&-]{0,60}$")


def clean_text(text):
    """Removes what repeats on every page of a PDF: the running header (for example 'EcoCash Private Limited Governance, Risk and Compliance Policy Version 2.0') and 'Page 5 of 44'."""
    t = re.sub(r"\bPage\s+[\divxlc]+\s+of\s+\d+\b", " ", text or "", flags=re.I)
    parts = re.split(r"(\[Page \d+\])", t)
    if len(parts) < 7:
        return t
    pages = [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    from collections import Counter
    pref = Counter(" ".join(b.split()[:6]) for _, b in pages if len(b.split()) > 8)
    if not pref:
        return t
    common, n = pref.most_common(1)[0]
    if n < 3 or n < 0.3 * len(pages):
        return t
    rx = re.compile(r"^\s*" + r"\s+".join(re.escape(w) for w in common.split()) + r"(?:\s+[A-Za-z]+)?(?:\s+Version\s*\d+\s*\.?\s*\d*)?", re.I)
    return parts[0] + "".join(m + rx.sub(" ", b, count=1) for m, b in pages)


def doc_sentences(text):
    """[(page or None, sentence)] with page furniture removed and repeats dropped."""
    out, seen = [], set()
    for page, para in ai_kb.paged_passages(clean_text(text), size=200000):
        for s in SENT.split(para):
            s = s.strip(" \u2022-\u2013")
            key = re.sub(r"\W+", " ", s.lower())[:90]
            if 28 <= len(s) <= 430 and not re.match(r"^[\d.\s,%$-]+$", s) and not HEADERISH.match(s) and key not in seen and not re.search(r"\.{4,}|(?:\. ){4,}|\u2026{2,}", s):  # not a contents line with dotted leaders
                seen.add(key); out.append((page, s))
    return out


def textrank(sents, k, bias=None):
    """Indexes of the k most central sentences, in document order. bias: optional list of extra weights."""
    n = len(sents)
    if n <= k:
        return list(range(n))
    keep = list(range(n))
    if n > 320:  # on a long document only the most term-rich sentences compete, to keep it fast
        vecs0, idf0 = ai.vectors([s for _, s in sents]); weight = [sum(v.values()) / (len(v) ** 0.5 + 1) for v in vecs0]
        keep = sorted(sorted(range(n), key=lambda i: -weight[i])[:320])
    sub = [sents[i] for i in keep]; m = len(sub); vecs, _ = ai.vectors([s for _, s in sub]); adj = [[] for _ in range(m)]
    for i in range(m):
        for j in range(i + 1, m):
            w = ai.cos(vecs[i], vecs[j])
            if w > 0.08:
                adj[i].append((j, w)); adj[j].append((i, w))
    deg = [sum(w for _, w in a) or 1.0 for a in adj]; sc = [1.0 / m] * m
    for _ in range(25):
        new = [0.15 / m] * m
        for i in range(m):
            for j, w in adj[i]:
                new[i] += 0.85 * sc[j] * w / deg[j]
        sc = new
    for i in range(m):  # a sentence that states purpose, scope or a requirement is worth a little more; the opening of a document too
        s = sub[i][1].lower()
        sc[i] *= 1 + (0.35 if re.search(r"\b(purpose|scope|objective|this (policy|document|standard)|applies to)\b", s) else 0) + (0.2 if MODAL.search(s) else 0) + (0.15 if i < max(3, m // 12) else 0) + (bias[keep[i]] if bias else 0)
    pick = sorted(sorted(range(m), key=lambda i: -sc[i])[:k])
    return [keep[i] for i in pick]


def facts(text):
    t = text or ""
    dates = sorted(set(re.findall(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b", t)))[:12]
    money = sorted(set(m.group(0).strip() for m in re.finditer(r"(?:US\$|USD\s?|ZiG\s?|ZWG\s?|\$)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|billion|thousand|[mMkK]|bn))?", t)))[:12]
    pct = sorted(set(re.findall(r"\b\d{1,3}(?:\.\d+)?\s?%", t)))[:12]
    periods = sorted(set(m.group(0) for m in re.finditer(r"\b" + PERIOD + r"\b", t, re.I)))[:12]
    return {"dates": dates, "amounts": money, "percentages": pct, "periods": periods}


def summarise(text, k=7):
    sents = doc_sentences(text)
    if not sents:
        return {"points": [], "stats": {"sentences": 0}, "facts": facts(text), "purpose": None}
    idx = textrank(sents, k); pts = [sents[i] for i in idx]
    purpose = next((s for s in sents[:80] if re.search(r"\b(the (?:main )?purpose|purpose of|aims? (?:of|to)|objective of|scope of)\b", s[1], re.I) and len(s[1]) > 50), None) or next((s for s in sents[:60] if re.search(r"\b(purpose|objective|scope)\b", s[1], re.I) and len(s[1]) > 50), None)
    return {"points": pts, "purpose": purpose, "stats": {"sentences": len(sents), "words": len(re.findall(r"\w+", text or ""))}, "facts": facts(text)}


def theme_of(s):
    for name, rx in THEMES:
        if re.search(rx, s, re.I):
            return name
    return "General"


def obligations(text, limit=40):
    """[{who, what, when, page, theme, text, strength}] for every sentence that imposes a duty."""
    out = []
    for page, s in doc_sentences(text):
        m = MODAL.search(s)
        if not m:
            continue
        before = re.sub(r"^(?:\d+(?:\.\d+)*\.?\s+|[a-z]\)\s+|[ivx]+\.\s+)", "", s[:m.start()].strip(" ,;:"))
        words = before.split(); who = " ".join(words[-9:]) if words else "Not stated"
        who = re.sub(r"^(?:that|and|which|where|when|if|all|any)\s+", "", who, flags=re.I) or "Not stated"
        what = s[m.end():].strip(" ,;:.")[:240]
        d = DEADLINE.search(s)
        strong = m.group(1).lower() in ("shall", "must", "is required to", "are required to", "shall not", "must not", "may not", "has to", "have to")
        if len(what) < 8:
            continue
        out.append({"who": who[:90], "what": what, "when": d.group(0) if d else None, "page": page, "theme": theme_of(s), "text": s, "strength": "must" if strong else "should"})
    out.sort(key=lambda o: (o["strength"] != "must", o["when"] is None))
    return out[:limit]


def answer(text, question, k=3):
    """[(score, page, sentence)] best matches for a question inside one document."""
    sents = doc_sentences(text)
    if not sents or not (question or "").strip():
        return []
    vecs, idf = ai.vectors([s for _, s in sents]); q = ai.qvec(question, idf); toks = set(ai.tokens(question))
    scored = []
    for (p, s), v in zip(sents, vecs):
        words = s.split(); caps = sum(1 for w in words if w[:1].isupper()) / max(1, len(words))
        sc = (ai.cos(q, v) + 0.03 * len(toks & set(ai.tokens(s)))) * (0.55 if caps > 0.4 and len(words) > 8 else 1.0)  # a table header or a run of capitalised labels is rarely the sentence that answers
        scored.append((sc, p, s))
    scored.sort(key=lambda z: -z[0]); out = []
    for sc, p, s in scored:
        if sc < 0.09 or len(out) >= k:
            break
        if all(ai.cos(ai.qvec(s, idf), ai.qvec(o[2], idf)) < 0.7 for o in out):
            out.append((round(sc, 3), p, s))
    return out


def numbers_in(s):
    return re.findall(r"\d+(?:\.\d+)?\s*(?:hours?|days?|weeks?|months?|years?|%)?", s)


def compare(old, new):
    """What changed between two versions, in words: new and dropped duties, and changed numbers or periods."""
    so, sn = doc_sentences(old), doc_sentences(new); to, tn = {s for _, s in so}, {s for _, s in sn}
    removed = [(p, s) for p, s in so if s not in tn]; added = [(p, s) for p, s in sn if s not in to]
    vecs, idf = ai.vectors([s for _, s in removed + added]); rv, av = vecs[:len(removed)], vecs[len(removed):]
    changed, used = [], set()
    for i, (p, s) in enumerate(removed):
        best, bj = 0.0, None
        for j, v in enumerate(av):
            if j in used:
                continue
            w = ai.cos(rv[i], v)
            if w > best:
                best, bj = w, j
        if bj is not None and best >= 0.55:
            used.add(bj); a = added[bj]; no, nn = numbers_in(s), numbers_in(a[1])
            changed.append({"old": s, "new": a[1], "old_page": p, "new_page": a[0], "numbers_changed": no != nn, "from": [x for x in no if x not in nn][:4], "to": [x for x in nn if x not in no][:4], "similarity": round(best, 2)})
    pure_added = [(p, s) for j, (p, s) in enumerate(added) if j not in used]; matched_old = {c["old"] for c in changed}; pure_removed = [(p, s) for p, s in removed if s not in matched_old]
    return {"changed": changed, "added": pure_added, "removed": pure_removed, "new_duties": [x for x in pure_added if MODAL.search(x[1])], "dropped_duties": [x for x in pure_removed if MODAL.search(x[1])]}


def categorise(s):
    best, bn = None, 0
    for name, rx in CATS.items():
        n = len(re.findall(rx, s, re.I)) * {"Regulatory": 1.6, "Third party": 1.2}.get(name, 1)
        if n > bn:
            best, bn = name, n
    return best or "Operational", bn


def risk_candidates(text, limit=8):
    """The sentences that describe something that could go wrong, with a category: [{page, sentence, category, score}], one per distinct idea."""
    sents = doc_sentences(text); cand = []
    clause = re.compile(r"\b(is|are|was|were|may|could|would|will|can|has|have|does|did|must|shall|should|might|being|been)\b", re.I)
    for p, s in sents:
        t = len(TRIGGER.findall(s))
        words = s.split(); caps = sum(1 for w in words if w[:1].isupper())
        if not t or len(words) < 7 or caps > 0.45 * len(words) or re.search(r"(?i)\bappendix\b|sample risk register|^\d+(\.\d+)*\s|\|", s):  # not a table row, a heading or a template
            continue
        cat, cn = categorise(s)
        score = t + 0.7 * cn + (0.5 if MODAL.search(s) else 0) + (0.3 if re.search(r"\b(customer|agent|platform|regulator|all transactions|critical)\b", s, re.I) else 0) - (0.5 if len(s) < 55 else 0)
        cand.append({"page": p, "sentence": s, "category": cat, "score": round(score, 2)})
    cand.sort(key=lambda z: -z["score"]); out, vecs = [], []
    allv, idf = ai.vectors([c["sentence"] for c in cand[:80]]) if cand else ([], {})
    for c, v in zip(cand[:80], allv):
        if len(out) >= limit:
            break
        if all(ai.cos(v, ov) < 0.55 for ov in vecs):
            out.append(c); vecs.append(v)
    return out
