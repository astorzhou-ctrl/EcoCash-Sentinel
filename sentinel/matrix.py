"""The auditor's ranked 5 x 5 risk matrix (BRD section 3). A lookup table, never a formula: ranks are ordinal."""
MATRIX = {(5, 1): 11, (5, 2): 16, (5, 3): 20, (5, 4): 23, (5, 5): 25, (4, 1): 7, (4, 2): 12, (4, 3): 17, (4, 4): 21, (4, 5): 24, (3, 1): 4, (3, 2): 8, (3, 3): 13, (3, 4): 18, (3, 5): 22,
          (2, 1): 2, (2, 2): 5, (2, 3): 9, (2, 4): 14, (2, 5): 19, (1, 1): 1, (1, 2): 3, (1, 3): 6, (1, 4): 10, (1, 5): 15}
CONSEQUENCE = ["Insignificant", "Minor", "Moderate", "High", "Major"]
LIKELIHOOD = ["Rare", "Unlikely", "Moderate", "Likely", "Almost certain"]
LEVELS = ["Low", "Medium", "Significant", "High"]
BANDS = [("Low", 1, 5), ("Medium", 6, 12), ("Significant", 13, 20), ("High", 21, 25)]
RESPONSE = {"High": "Board Risk Committee approves retention; treatment plan within 30 days; monthly review",
            "Significant": "MD's meeting oversight; owned, dated and costed treatment plan; monthly review",
            "Medium": "Risk owner manages within normal controls; quarterly review", "Low": "Accept and monitor; annual review"}
# Appetite (GRC Policy 2.4: a net score above the limit is outside tolerable limits and needs Board approval). The thresholds are
# configuration, set in Risk Appetite. Defaults follow the risk assessment workbook (target 6, appetite 12, tolerance 15) on the ranked matrix.
THRESH = {"target": 6, "appetite": 12, "tolerance": 15}


def set_thresholds(t):
    THRESH.update({k: int(t[k]) for k in ("target", "appetite", "tolerance")})


def rank(l, c):
    return MATRIX[(int(l), int(c))]


def level(r):
    return "High" if r >= 21 else "Significant" if r >= 13 else "Medium" if r >= 6 else "Low"


def level_index(r):
    return LEVELS.index(level(r))


def rating(l, c):
    r = rank(l, c)
    return {"l": int(l), "c": int(c), "rank": r, "level": level(r)}


def outside_appetite(category, residual_rank):
    """Above appetite: the Board must approve retaining the risk (policy 2.4). The category is kept for compatibility."""
    return residual_rank > THRESH["appetite"]


def band(r):
    return "outside_tolerance" if r > THRESH["tolerance"] else "outside_appetite" if r > THRESH["appetite"] else "within_target" if r <= THRESH["target"] else "within_appetite"


def describe():
    return {"cells": {"%d,%d" % k: v for k, v in MATRIX.items()}, "consequence": CONSEQUENCE, "likelihood": LIKELIHOOD, "bands": [{"level": n, "from": a, "to": b, "response": RESPONSE[n]} for n, a, b in BANDS],
            "appetite": dict(THRESH)}
