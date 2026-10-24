"""
tools.py - the functions the agent is allowed to use to learn about a stylesheet.

Every tool returns the same envelope:
    {"tool": name, "status": "ok" | "not_found" | "error", "data": {...}, "message": "..."}

`not_found` is a first-class result (not an exception, not an empty string) so the
agent can never confuse "there is no data" with "the model should fill the gap".
Tools are pure and deterministic: same CSS + same arguments -> byte-identical output.
"""
from __future__ import annotations

import difflib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "milestone1_css_parser"))
from css_dna import Parser, analyze, resolve_vars, split_top  # noqa: E402

THRESHOLDS = {"aa_normal_text": 4.5, "aa_large_text": 3.0}

TOOL_SPECS = [
    {"name": "get_palette",
     "description": "List every colour used in the stylesheet (normalised hex) with usage counts and the CSS variables that define it.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_css_variable",
     "description": "Look up one CSS custom property (e.g. --brand): raw value and fully resolved value. Returns not_found with close matches if it does not exist.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "Variable name, e.g. --brand"}}, "required": ["name"]}},
    {"name": "check_contrast",
     "description": "WCAG contrast ratio of text/background colour pairs. Give a selector for one rule, or omit it for an overall accessibility summary.",
     "input_schema": {"type": "object", "properties": {"selector": {"type": "string", "description": "Exact selector, e.g. .muted"}}, "required": []}},
    {"name": "get_breakpoints",
     "description": "Responsive width breakpoints and user-preference media queries (dark mode, reduced motion).",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_typography",
     "description": "Font families, font-size scale in px, font weights and @font-face declarations.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_spacing",
     "description": "Margin/padding/gap values in px, the inferred spacing base unit (grid) and off-grid outliers.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "find_conflicts",
     "description": "Declarations that are overridden or duplicated (dead CSS), with the winning value.",
     "input_schema": {"type": "object", "properties": {"property": {"type": "string", "description": "Optional CSS property filter, e.g. padding"}}, "required": []}},
    {"name": "get_rule",
     "description": "Return the declarations of the rule(s) with exactly this selector (e.g. h1, .btn). not_found if the selector is not in the file.",
     "input_schema": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}},
]
TOOL_NAMES = {t["name"] for t in TOOL_SPECS}


def _ok(tool, data, message=""):
    return {"tool": tool, "status": "ok", "data": data, "message": message}


def _nf(tool, message, **data):
    return {"tool": tool, "status": "not_found", "data": data, "message": message}


class CssToolkit:
    def __init__(self, css_text: str, source: str = "<css>"):
        self.report = analyze(css_text, source)
        self.rules = Parser(css_text).parse().rules
        self.env = {n: v["raw"] for n, v in self.report["variables"].items()}
        self.selectors = sorted({" ".join(s.split()) for r in self.rules for s in split_top(r["selector"])})

    # public entry point ---------------------------------------------------
    def call(self, name: str, args: dict | None = None) -> dict:
        if name not in TOOL_NAMES:
            return {"tool": name, "status": "error", "data": {}, "message": f"unknown tool '{name}'"}
        try:
            return getattr(self, "tool_" + name)(**(args or {}))
        except TypeError as e:
            return {"tool": name, "status": "error", "data": {}, "message": f"bad arguments: {e}"}

    # tools ----------------------------------------------------------------
    def tool_get_palette(self):
        pal = self.report["palette"]
        if not pal:
            return _nf("get_palette", "No colours were found in this stylesheet.")
        return _ok("get_palette", {"count": len(pal), "colors": pal})

    def tool_get_css_variable(self, name: str):
        n = name.strip()
        n = n if n.startswith("--") else "--" + n
        v = self.report["variables"].get(n)
        if v is None:
            close = difflib.get_close_matches(n, list(self.report["variables"]), n=3, cutoff=0.7)
            return _nf("get_css_variable", f"No custom property named '{n}' exists in this stylesheet.", requested=n, did_you_mean=close,
                       all_variables=sorted(self.report["variables"]))
        themed = [{"context": t["context"], "value": t["variables"][n]} for t in self.report["themes"] if n in t["variables"]]
        return _ok("get_css_variable", {"name": n, "raw": v["raw"], "resolved": v["resolved"], "status": v["status"], "theme_overrides": themed})

    def tool_check_contrast(self, selector: str | None = None):
        pairs = self.report["contrast"]
        if selector:
            sel = " ".join(selector.split())
            m = [p for p in pairs if p["selector"] == sel]
            if m:
                return _ok("check_contrast", {"pair_count": len(m), "pairs": m, "thresholds": THRESHOLDS})
            if sel in self.selectors:
                return _nf("check_contrast", f"'{sel}' exists but declares no text colour, so no contrast pair can be computed.", selector=sel)
            return _nf("check_contrast", f"The selector '{sel}' does not exist in this stylesheet.", selector=sel,
                       did_you_mean=difflib.get_close_matches(sel, self.selectors, n=3, cutoff=0.7))
        failing = [p for p in pairs if not p["passes_AA_normal"]]
        return _ok("check_contrast", {"total_pairs": len(pairs), "failing_count": len(failing), "failing": failing, "thresholds": THRESHOLDS})

    def tool_get_breakpoints(self):
        b = self.report["breakpoints"]
        if not b["width"] and not b["preferences"]:
            return _nf("get_breakpoints", "This stylesheet has no media queries.")
        return _ok("get_breakpoints", {"count": len(b["width"]), **b})

    def tool_get_typography(self):
        t = self.report["typography"]
        if not t["families"] and not t["font_sizes_px"]:
            return _nf("get_typography", "No typography declarations were found.")
        return _ok("get_typography", t)

    def tool_get_spacing(self):
        s = self.report["spacing"]
        if not s["values_px"]:
            return _nf("get_spacing", "No margin, padding or gap values were found.")
        return _ok("get_spacing", s)

    def tool_find_conflicts(self, property: str | None = None):
        c = self.report["conflicts"]
        if property:
            c = [x for x in c if x["property"] == property.strip().lower()]
        if not c:
            return _nf("find_conflicts", "No overridden or duplicated declarations were found" + (f" for '{property}'." if property else "."))
        return _ok("find_conflicts", {"count": len(c), "conflicts": c})

    def tool_get_rule(self, selector: str):
        sel = " ".join(selector.split())
        matches = []
        for r in self.rules:
            if sel in [" ".join(s.split()) for s in split_top(r["selector"])]:
                decls = []
                for d in r["declarations"]:
                    item = {"property": d["prop"], "value": d["value"], "important": d["important"], "line": d["line"]}
                    if "var(" in d["value"]:
                        res, st = resolve_vars(d["value"], self.env)
                        item["resolved"] = res
                        item["var_status"] = st
                    decls.append(item)
                matches.append({"line": r["line"], "context": r["context"], "declarations": decls})
        if not matches:
            return _nf("get_rule", f"The selector '{sel}' does not exist in this stylesheet.", selector=sel,
                       did_you_mean=difflib.get_close_matches(sel, self.selectors, n=3, cutoff=0.7))
        return _ok("get_rule", {"selector": sel, "match_count": len(matches), "matches": matches})
