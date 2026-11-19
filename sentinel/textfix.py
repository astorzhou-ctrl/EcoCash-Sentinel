"""Repairs text damaged by a global find-and-replace in the risk workbook. Replacing 'HR' with 'People & Culture' and 'CRO' with 'Head Risk' also hit the
middle of ordinary words: 'through' became 'tPeople & Cultureough', 'threatens' 'tPeople & Cultureeatens', 'across' 'aHead Riskss'.
A replacement that is glued to letters is certainly damage; the same words standing alone (an owner called 'People & Culture Head') are left alone."""
import re

_HR = re.compile(r"([A-Za-z]*)People & Culture([A-Za-z]*)")
_CRO = re.compile(r"([A-Za-z]*)Head Risk([A-Za-z]*)")


def _fix(rep_lower, rep_upper):
    def f(m):
        left, right = m.group(1), m.group(2)
        if not left and not right:
            return m.group(0)  # the words stand alone: a real department or owner
        glued = left + right
        return left + (rep_upper if glued.isupper() else rep_lower) + right
    return f


def repair(s):
    if not isinstance(s, str) or ("People & Culture" not in s and "Head Risk" not in s):
        return s
    return _CRO.sub(_fix("cro", "CRO"), _HR.sub(_fix("hr", "HR"), s))


def damaged(s):
    return isinstance(s, str) and repair(s) != s


def repair_grid(grid):
    return [[repair(c) for c in row] for row in grid]
