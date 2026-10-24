"""
grounding.py - "evidence or silence".

The model's draft answer is never trusted. We extract every checkable fact from it
(hex colours, --custom-property names, numbers) and require each one to appear in
the data the tools actually returned. Anything else is an unsupported claim.

It also holds the deterministic formatters: they turn tool results into prose
using ONLY the tool data, so they are (a) the offline "model", (b) the safe
fallback when a real LLM's draft fails verification, and (c) the abstention text.
"""
from __future__ import annotations

import hashlib
import json
import re

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
VAR = re.compile(r"--[A-Za-z_][\w-]*")
NUM = re.compile(r"(?<![\w#.-])\d+(?:\.\d+)?")


def _norm_num(s: str) -> str:
    f = float(s)
    return str(int(f)) if f.is_integer() else str(f)


def facts(text: str) -> set[str]:
    """Checkable atoms in a piece of text: hex colours, --vars, numbers."""
    out = {h.lower() for h in HEX.findall(text)}
    out |= set(VAR.findall(text))
    rest = VAR.sub(" ", HEX.sub(" ", text))
    rest = re.sub(r"(?<=\d):1\b", "", rest)          # "4.5:1" is one ratio, not the number 1
    out |= {_norm_num(n) for n in NUM.findall(rest)}
    return out


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def evidence_facts(results: list[dict]) -> set[str]:
    return facts(canonical(results))


def evidence_hash(results: list[dict]) -> str:
    return hashlib.sha256(canonical(results).encode()).hexdigest()[:12]


def verify(answer: str, results: list[dict]) -> tuple[bool, list[str]]:
    """True if every checkable fact in `answer` is present in the tool evidence."""
    unsupported = sorted(facts(answer) - evidence_facts(results))
    return (not unsupported, unsupported)


# --------------------------------------------------------------------------
# Deterministic formatters (use tool data only)
# --------------------------------------------------------------------------

def _pal(d):
    lines = [f"The stylesheet uses {d['count']} distinct colours:"]
    for c in d["colors"]:
        extra = f", defined as {', '.join(c['defined_as'])}" if c["defined_as"] else ""
        lines.append(f"- {c['hex']}: used {c['uses']}x{extra}")
    return "\n".join(lines)


def _var(d):
    if d["status"] in ("cycle", "missing") or d["resolved"] is None:
        return f"{d['name']} is defined as {d['raw']}, but it cannot be resolved ({d['status']}): it is part of a circular or broken var() chain."
    s = f"{d['name']} resolves to {d['resolved']}"
    if d["raw"] != d["resolved"]:
        s += f" (defined as {d['raw']})"
    for t in d["theme_overrides"]:
        s += f". Under {t['context']} it is overridden to {t['value']}"
    return s + "."


def _contrast(d):
    t = d["thresholds"]
    if "pairs" in d:
        lines = []
        for p in d["pairs"]:
            verdict = "passes" if p["passes_AA_normal"] else ("fails WCAG AA for normal text" if p["passes_AA_large"] else "fails WCAG AA even for large text")
            note = f" (page background assumed, line {p['line']})" if p["background_source"] == "assumed" else f" (line {p['line']})"
            lines.append(f"{p['selector']}: {p['foreground']} on {p['background']} = {p['ratio']}:1, {verdict}{note}")
        lines.append(f"Thresholds: {t['aa_normal_text']}:1 for normal text, {t['aa_large_text']}:1 for large text.")
        return "\n".join(lines)
    lines = [f"{d['failing_count']} of {d['total_pairs']} text/background pairs fail WCAG AA for normal text (needs {t['aa_normal_text']}:1):"]
    for p in d["failing"]:
        lines.append(f"- {p['selector']}: {p['foreground']} on {p['background']} = {p['ratio']}:1 (line {p['line']})")
    return "\n".join(lines)


def _bp(d):
    s = []
    if d["width"]:
        s.append("Width breakpoints: " + ", ".join(f"{b['type']} {b['px']}px" for b in d["width"]) + ".")
    if d["preferences"]:
        s.append("User-preference queries: " + ", ".join(d["preferences"]) + ".")
    return " ".join(s)


def _typo(d):
    s = ["Font families: " + ", ".join(f"{f['family']} (used {f['uses']}x)" for f in d["families"]) + "."]
    if d["font_sizes_px"]:
        s.append("Font sizes: " + ", ".join(f"{x['px']}px" for x in d["font_sizes_px"]) + ".")
    if d["font_weights"]:
        s.append("Font weights: " + ", ".join(str(w) for w in d["font_weights"]) + ".")
    return " ".join(s)


def _space(d):
    s = f"Spacing values: {', '.join(str(v) + 'px' for v in d['values_px'])}. "
    if d["base_unit_px"]:
        s += f"They mostly follow a {d['base_unit_px']}px grid"
        s += f"; off-grid values: {', '.join(str(v) + 'px' for v in d['off_grid_px'])}." if d["off_grid_px"] else "."
    else:
        s += "No consistent spacing grid was detected."
    return s


def _conf(d):
    lines = [f"Conflicts found: {d['count']}"]
    for c in d["conflicts"]:
        vals = "; ".join(f"{x['value']} (line {x['line']})" for x in c["declarations"])
        lines.append(f"- {c['selector']} {c['property']}: {vals} -> winning value {c['winning_value']} [{c['kind'].replace('_', ' ')}]")
    return "\n".join(lines)


def _rule(d):
    lines = []
    for m in d["matches"]:
        ctx = f" inside {' > '.join(m['context'])}" if m["context"] else ""
        lines.append(f"{d['selector']}{ctx} (line {m['line']}):")
        for x in m["declarations"]:
            r = f" -> {x['resolved']}" if x.get("resolved") and x["resolved"] != x["value"] else ""
            lines.append(f"- {x['property']}: {x['value']}{r}")
    return "\n".join(lines)


_FMT = {"get_palette": _pal, "get_css_variable": _var, "check_contrast": _contrast, "get_breakpoints": _bp,
        "get_typography": _typo, "get_spacing": _space, "find_conflicts": _conf, "get_rule": _rule}


def compose(results: list[dict]) -> str:
    """Prose built only from the `ok` tool results."""
    return "\n\n".join(_FMT[r["tool"]](r["data"]) for r in results if r["status"] == "ok" and r["tool"] in _FMT)


def abstain(results: list[dict]) -> str:
    """Answer used when no tool produced data. Written by code, not by the model."""
    if not results:
        return ("I can only answer questions about the CSS file I was given, using my tools, and none of them "
                "apply to that question. I won't answer from general knowledge.")
    lines = ["I don't have that data in this stylesheet, so I can't give you a value:"]
    for r in results:
        if r["status"] != "ok":
            lines.append(f"- {r['message']}")
            close = r["data"].get("did_you_mean")
            if close:
                lines.append(f"  Closest names that do exist: {', '.join(close)}")
    lines.append("I won't guess a value that isn't in the file.")
    return "\n".join(lines)
