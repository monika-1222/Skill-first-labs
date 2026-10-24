#!/usr/bin/env python3
"""
css_dna.py  -  Milestone 1: a CSS parser that extracts a site's "design DNA".

Instead of returning raw text, it returns a structured, deterministic report:

    palette        every colour normalised to hex, with usage counts
    variables      custom properties (--x) resolved through var() chains,
                   plus dark-mode / scoped overrides ("themes")
    typography     font families, font-size scale (px), @font-face
    spacing        margin/padding/gap values, inferred base unit (4px/8px grid),
                   and off-grid "outliers"
    breakpoints    width breakpoints + user-preference media queries
    specificity    most specific selectors, !important usage
    conflicts      declarations that are overridden / duplicated
    contrast       WCAG contrast ratio for every colour / background pair
    issues         unresolved var(), var() cycles, malformed CSS

Pure standard library. No regex-only parsing of the whole file: a small
scanner understands strings, parentheses and comments, so `;` or `}` inside
url(data:...) or "content" strings never break the parse.

Usage:
    python css_dna.py sample/site.css                 # human summary
    python css_dna.py sample/site.css -o report.json  # JSON report
"""
from __future__ import annotations

import argparse
import colorsys
import json
import re
import sys
from collections import Counter, defaultdict

ROOT_FONT_PX = 16  # assumption used to convert rem/em to px (reported in meta)

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def strip_comments(css: str) -> str:
    """Blank out /* ... */ comments but keep newlines (line numbers stay valid).
    Comment markers inside strings are left alone."""
    out, i, n, quote = [], 0, len(css), None
    while i < n:
        c = css[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(css[i + 1]); i += 2; continue
            if c == quote or c == "\n":      # unterminated strings end at newline
                quote = None
            i += 1; continue
        if c in "\"'":
            quote = c; out.append(c); i += 1; continue
        if c == "/" and css[i + 1:i + 2] == "*":
            j = css.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in css[i:j]))
            i = j; continue
        out.append(c); i += 1
    return "".join(out)


def split_top(s: str, sep: str = ",") -> list[str]:
    """Split on `sep` ignoring separators inside (), [] or quotes.
    sep=' ' means 'any whitespace'."""
    parts, cur, depth, quote, i = [], [], 0, None, 0
    while i < len(s):
        c = s[i]
        if quote:
            cur.append(c)
            if c == "\\" and i + 1 < len(s):
                cur.append(s[i + 1]); i += 2; continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c; cur.append(c)
        elif c in "([":
            depth += 1; cur.append(c)
        elif c in ")]":
            depth = max(0, depth - 1); cur.append(c)
        elif depth == 0 and (c.isspace() if sep == " " else c == sep):
            parts.append("".join(cur)); cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def num(x: float):
    """Tidy number for JSON: 8.0 -> 8, 3.4567 -> 3.46"""
    return int(x) if float(x).is_integer() else round(float(x), 2)


def to_px(tok: str):
    m = re.fullmatch(r"(-?\d*\.?\d+)(px|rem|em|pt)?", tok.strip().lower())
    if not m:
        return None
    v, unit = float(m.group(1)), m.group(2)
    if unit is None:
        return 0.0 if v == 0 else None          # unitless non-zero is not a length
    return v * {"px": 1, "rem": ROOT_FONT_PX, "em": ROOT_FONT_PX, "pt": 96 / 72}[unit]


# --------------------------------------------------------------------------
# Colours
# --------------------------------------------------------------------------

NAMED = {  # common CSS named colours (a documented subset, not all 148)
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
    "pink": "#ffc0cb", "gray": "#808080", "grey": "#808080", "silver": "#c0c0c0",
    "maroon": "#800000", "navy": "#000080", "teal": "#008080", "olive": "#808000",
    "lime": "#00ff00", "aqua": "#00ffff", "cyan": "#00ffff", "magenta": "#ff00ff",
    "fuchsia": "#ff00ff", "brown": "#a52a2a", "gold": "#ffd700", "indigo": "#4b0082",
    "violet": "#ee82ee", "coral": "#ff7f50", "tomato": "#ff6347", "salmon": "#fa8072",
    "crimson": "#dc143c", "khaki": "#f0e68c", "beige": "#f5f5dc", "ivory": "#fffff0",
    "lavender": "#e6e6fa", "plum": "#dda0dd", "orchid": "#da70d6", "turquoise": "#40e0d0",
    "tan": "#d2b48c", "wheat": "#f5deb3", "darkgray": "#a9a9a9", "lightgray": "#d3d3d3",
    "darkblue": "#00008b", "lightblue": "#add8e6", "darkgreen": "#006400",
    "lightgreen": "#90ee90",
}
COLOR_PROP = re.compile(
    r"^(color|background(-color)?|border.*|outline.*|fill|stroke|box-shadow|"
    r"text-shadow|text-decoration.*|caret-color|accent-color)$")


def _scaled(tok: str, scale: float) -> float:
    return float(tok[:-1]) / 100 * scale if tok.endswith("%") else float(tok)


def parse_color(tok: str):
    """Return (r, g, b, a) with r,g,b in 0..255 and a in 0..1, or None."""
    t = tok.strip().lower()
    if t == "transparent":
        return (0, 0, 0, 0.0)
    if t in NAMED:
        t = NAMED[t]
    m = re.fullmatch(r"#([0-9a-f]{3,8})", t)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8):
            return None
        r, g, b = (int(h[k:k + 2], 16) for k in (0, 2, 4))
        return (r, g, b, int(h[6:8], 16) / 255 if len(h) == 8 else 1.0)
    m = re.fullmatch(r"(rgba?|hsla?)\((.*)\)", t, re.S)
    if not m:
        return None
    args = [a for a in re.split(r"[\s,/]+", m.group(2).strip()) if a]
    if len(args) < 3:
        return None
    try:
        a = min(1.0, max(0.0, _scaled(args[3], 1))) if len(args) > 3 else 1.0
        if m.group(1).startswith("rgb"):
            r, g, b = (min(255, max(0, _scaled(x, 255))) for x in args[:3])
        else:
            h = float(args[0].replace("deg", "")) % 360 / 360
            s, l = _scaled(args[1], 1), _scaled(args[2], 1)
            r, g, b = (v * 255 for v in colorsys.hls_to_rgb(h, l, s))
    except ValueError:
        return None
    return (r, g, b, a)


def to_hex(c) -> str:
    r, g, b, a = c
    h = "#%02x%02x%02x" % (round(r), round(g), round(b))
    return h if a >= 1 else h + "%02x" % round(a * 255)


def luminance(c) -> float:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(x) for x in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(c1, c2) -> float:
    l1, l2 = sorted((luminance(c1), luminance(c2)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def extract_colors(prop: str, value: str) -> list:
    """All colours inside one declaration value (hex, rgb(), hsl(), named)."""
    v = re.sub(r"url\([^)]*\)|\"[^\"]*\"|'[^']*'", " ", value)   # no false hits in urls/strings
    found = []
    for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?)\([^()]*\)", v):
        c = parse_color(m.group(0))
        if c:
            found.append(c)
    rest = re.sub(r"#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?)\([^()]*\)", " ", v)
    if COLOR_PROP.match(prop) or (prop.startswith("--") and rest.strip().lower() in NAMED):
        for tok in re.split(r"[\s,]+", rest):
            if tok.lower() in NAMED or tok.lower() == "transparent":
                found.append(parse_color(tok))
    return found


# --------------------------------------------------------------------------
# var() resolution
# --------------------------------------------------------------------------

def resolve_vars(value: str, env: dict, stack: tuple = ()):
    """Resolve var(--x, fallback) recursively.
    Returns (resolved_or_None, status) with status in
    ok | fallback | missing | cycle."""
    out, i, status = [], 0, "ok"
    while i < len(value):
        is_var = value.startswith("var(", i) and (i == 0 or not (value[i - 1].isalnum() or value[i - 1] in "-_"))
        if not is_var:
            out.append(value[i]); i += 1; continue
        depth, j = 1, i + 4
        while j < len(value) and depth:
            depth += (value[j] == "(") - (value[j] == ")")
            j += 1
        parts = split_top(value[i + 4:j - 1])
        name = parts[0] if parts else ""
        fallback = ",".join(parts[1:]) if len(parts) > 1 else None
        if name in stack:
            return None, "cycle"
        if name in env:
            sub, st = resolve_vars(env[name], env, stack + (name,))
            if sub is None:
                return None, st
        elif fallback is not None:
            sub, st = resolve_vars(fallback, env, stack)
            status = "fallback"
            if sub is None:
                return None, st
        else:
            return None, "missing"
        out.append(sub); i = j
    return "".join(out), status


# --------------------------------------------------------------------------
# Selector specificity
# --------------------------------------------------------------------------

def _strip_functional(s: str):
    out, funcs, i = [], [], 0
    pat = re.compile(r"::?([\w-]+)\(")
    while i < len(s):
        m = pat.match(s, i) if s[i] == ":" else None
        if not m:
            out.append(s[i]); i += 1; continue
        depth, j = 1, m.end()
        while j < len(s) and depth:
            depth += (s[j] == "(") - (s[j] == ")")
            j += 1
        funcs.append((m.group(1).lower(), s[m.end():j - 1], m.group(0).startswith("::")))
        i = j
    return "".join(out), funcs


def specificity(selector: str) -> tuple:
    """(ids, classes/attrs/pseudo-classes, elements/pseudo-elements).
    Handles :not/:is/:has (max of args) and :where (zero)."""
    s = re.sub(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", '""', selector)
    s, funcs = _strip_functional(s)
    a = b = c = 0
    for name, arg, is_el in funcs:
        if is_el:
            c += 1
        elif name == "where":
            pass
        elif name in ("is", "not", "has", "matches"):
            sp = max((specificity(p) for p in split_top(arg)), default=(0, 0, 0))
            a, b, c = a + sp[0], b + sp[1], c + sp[2]
        else:
            b += 1
    a += len(re.findall(r"#[\w-]+", s))
    b += len(re.findall(r"\.[\w-]+", s)) + len(re.findall(r"\[[^\]]*\]", s))
    b += len(re.findall(r"(?<!:):[\w-]+", s))
    c += len(re.findall(r"::[\w-]+", s))
    t = re.sub(r"\[[^\]]*\]|#[\w-]+|\.[\w-]+|::?[\w-]+", " ", s)
    t = re.sub(r"[>+~*|&]", " ", t)
    c += sum(1 for x in t.split() if re.fullmatch(r"[a-zA-Z][\w-]*", x))
    return (a, b, c)


# --------------------------------------------------------------------------
# The parser: text -> rules / at-rules / warnings
# --------------------------------------------------------------------------

class Parser:
    def __init__(self, css: str):
        self.text = strip_comments(css)
        self.n = len(self.text)
        self.i = 0
        self.rules: list[dict] = []
        self.at_rules: list[dict] = []
        self.font_faces: list[dict] = []
        self.keyframes: list[str] = []
        self.imports: list[str] = []
        self.warnings: list[dict] = []

    def line(self, pos: int) -> int:
        return self.text.count("\n", 0, pos) + 1

    def warn(self, msg: str, pos: int):
        self.warnings.append({"line": self.line(pos), "message": msg})

    # -- scanning ----------------------------------------------------------
    def read_until(self):
        """Read to the next top-level ';', '{' or '}'. Returns (chunk, terminator).
        '}' is not consumed so the enclosing block can see it."""
        t, start, depth, quote = self.text, self.i, 0, None
        while self.i < self.n:
            c = t[self.i]
            if quote:
                if c == "\\":
                    self.i += 2; continue
                if c == quote or c == "\n":
                    quote = None
            elif c in "\"'":
                quote = c
            elif c in "([":
                depth += 1
            elif c in ")]":
                depth = max(0, depth - 1)
            elif depth == 0 and c in ";{}":
                chunk = t[start:self.i]
                if c != "}":
                    self.i += 1
                return chunk, c
            self.i += 1
        return t[start:self.n], None

    def skip_block(self):
        depth, quote, t = 1, None, self.text
        while self.i < self.n and depth:
            c = t[self.i]
            if quote:
                if c == "\\":
                    self.i += 2; continue
                if c == quote or c == "\n":
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            self.i += 1

    def parse(self):
        self.parse_block([], None, top=True)
        return self

    def parse_block(self, ctx, parent_sel, top=False):
        decls = []
        while True:
            while self.i < self.n and self.text[self.i].isspace():
                self.i += 1
            if self.i >= self.n:
                if not top:
                    self.warn("unterminated block at end of file", self.n - 1)
                return decls
            if self.text[self.i] == "}":
                self.i += 1
                if top:
                    self.warn("stray '}' ignored", self.i - 1)
                    continue
                return decls
            start = self.i
            chunk, term = self.read_until()
            chunk = chunk.strip()
            line = self.line(start)
            if term == "{":
                self.handle_block(chunk, ctx, parent_sel, line)
            elif not chunk:
                continue
            elif chunk.startswith("@"):
                self.handle_statement(chunk, line)
            else:
                d = self.make_decl(chunk, line)
                if d and top:
                    self.warnings.append({"line": line, "message": f"declaration outside a rule ignored: {chunk[:40]}"})
                elif d:
                    decls.append(d)

    def make_decl(self, chunk: str, line: int):
        prop, sep, val = chunk.partition(":")
        prop = prop.strip()
        if not sep or not re.fullmatch(r"-{0,2}[A-Za-z_][\w-]*", prop):
            self.warnings.append({"line": line, "message": f"malformed declaration skipped: {chunk[:40]}"})
            return None
        if not prop.startswith("--"):
            prop = prop.lower()
        val = val.strip()
        imp = bool(re.search(r"!\s*important\s*$", val, re.I))
        if imp:
            val = re.sub(r"\s*!\s*important\s*$", "", val, flags=re.I)
        return {"prop": prop, "value": val, "important": imp, "line": line}

    def handle_statement(self, chunk: str, line: int):
        m = re.match(r"@([\w-]+)\s*(.*)", chunk, re.S)
        name, arg = m.group(1).lower(), m.group(2).strip()
        if name == "import":
            self.imports.append(arg)

    def handle_block(self, prelude: str, ctx, parent_sel, line: int):
        if not prelude:
            self.skip_block(); return
        if prelude.startswith("@"):
            m = re.match(r"@([\w-]+)\s*(.*)", prelude, re.S)
            name, arg = m.group(1).lower(), m.group(2).strip()
            if name in ("media", "supports", "layer", "container", "scope"):
                self.at_rules.append({"name": name, "prelude": arg, "line": line})
                new_ctx = ctx + [f"@{name} {arg}".strip()]
                decls = self.parse_block(new_ctx, parent_sel)
                if decls and parent_sel:                       # nested @media inside a rule
                    self.add_rule(parent_sel, decls, new_ctx, line)
            elif name == "font-face":
                d = {x["prop"]: x["value"] for x in self.parse_block(ctx, None)}
                self.font_faces.append({
                    "family": d.get("font-family", "").strip("\"' "),
                    "weight": d.get("font-weight", "normal"),
                    "formats": re.findall(r"format\(\s*[\"']?([\w-]+)", d.get("src", "")),
                    "line": line})
            elif name.endswith("keyframes"):
                self.keyframes.append(arg); self.skip_block()
            else:
                self.skip_block()
            return
        selector = self.nest(prelude, parent_sel)
        decls = self.parse_block(ctx, selector)
        self.add_rule(selector, decls, ctx, line)

    @staticmethod
    def nest(child: str, parent):
        """Resolve CSS-nesting: '&:hover' / '.x' inside '.card'."""
        if not parent:
            return " ".join(child.split())
        p = parent if "," not in parent else f":is({parent})"
        parts = [(c.replace("&", p) if "&" in c else f"{p} {c}") for c in split_top(child)]
        return ", ".join(" ".join(x.split()) for x in parts)

    def add_rule(self, selector, decls, ctx, line):
        sels = split_top(selector)
        self.rules.append({
            "selector": selector, "context": list(ctx), "line": line, "declarations": decls,
            "specificity": max((specificity(s) for s in sels), default=(0, 0, 0)),
            "index": len(self.rules)})


# --------------------------------------------------------------------------
# Analysis: rules -> design DNA report
# --------------------------------------------------------------------------

ROOT_SELECTORS = {":root", "html", "*"}
SPACING_PROP = re.compile(r"^(margin|padding)(-(top|right|bottom|left|inline|block)(-(start|end))?)?$|^(row-|column-|grid-)?gap$")


def analyze(css: str, source: str = "<string>") -> dict:
    p = Parser(css).parse()

    # 1. custom properties: base env (:root, no media) vs scoped / themed
    env, themes, scoped = {}, [], []
    for r in p.rules:
        cp = {d["prop"]: d["value"] for d in r["declarations"] if d["prop"].startswith("--")}
        if not cp:
            continue
        is_root = all(s in ROOT_SELECTORS for s in split_top(r["selector"]))
        if is_root and not r["context"]:
            env.update(cp)
        elif r["context"]:
            themes.append({"context": " > ".join(r["context"]), "selector": r["selector"], "variables": dict(sorted(cp.items())), "line": r["line"]})
        else:
            scoped.append({"selector": r["selector"], "variables": dict(sorted(cp.items())), "line": r["line"]})

    issues = [{"line": w["line"], "type": "parse_warning", "detail": w["message"]} for w in p.warnings]
    variables = {}
    for name in sorted(env):
        res, st = resolve_vars(env[name], env, (name,))
        variables[name] = {"raw": env[name], "resolved": res, "status": st}

    palette = defaultdict(lambda: {"uses": 0, "defined_as": set(), "properties": Counter()})
    families, sizes, weights = {}, {}, Counter()
    spacing = Counter()
    unparsed_spacing = 0
    groups = defaultdict(list)
    important = []
    contrast, doc_bg = [], None

    for r in p.rules:
        resolved = {}
        for d in r["declarations"]:
            val = d["value"]
            if "var(" in val:
                res, st = resolve_vars(val, env)
                if res is None and d["prop"].startswith("--"):
                    continue                      # already visible in `variables[...].status`
                if res is None:
                    issues.append({"line": d["line"], "type": "var_cycle" if st == "cycle" else "unresolved_var",
                                   "selector": r["selector"], "property": d["prop"], "detail": f"{val} -> {st}"})
                    continue
                if st == "fallback" and not d["prop"].startswith("--"):
                    issues.append({"line": d["line"], "type": "var_fallback_used", "selector": r["selector"], "property": d["prop"], "detail": f"{val} -> {res}"})
                val = res
            resolved[d["prop"]] = val if d["prop"] not in resolved or d["important"] else resolved[d["prop"]]
            groups[(r["selector"], tuple(r["context"]), d["prop"])].append(
                {"value": d["value"], "line": d["line"], "important": d["important"], "rule": r["index"]})
            if d["important"]:
                important.append({"selector": r["selector"], "property": d["prop"], "line": d["line"]})

            prop = d["prop"]
            for c in extract_colors(prop, val):
                e = palette[to_hex(c)]
                if prop.startswith("--"):
                    e["defined_as"].add(prop)
                else:
                    e["uses"] += 1; e["properties"][prop] += 1
            if prop == "font-family":
                stack = split_top(val)
                fam = stack[0].strip("\"' ") if stack else ""
                f = families.setdefault(fam, {"family": fam, "stack": val, "uses": 0})
                f["uses"] += 1
            elif prop == "font-size":
                px = to_px(val)
                if px:
                    sizes.setdefault(num(px), {"px": num(px), "raw": set(), "uses": 0})
                    sizes[num(px)]["raw"].add(val); sizes[num(px)]["uses"] += 1
            elif prop == "font-weight" and val.isdigit():
                weights[int(val)] += 1
            elif SPACING_PROP.match(prop):
                for tok in split_top(val, " "):
                    px = to_px(tok)
                    if px is None:
                        unparsed_spacing += 1
                    elif px != 0:
                        spacing[num(abs(px))] += 1

        if not r["context"]:
            if r["selector"] in ("body", "html", ":root") and doc_bg is None:
                cols = extract_colors("background-color", resolved.get("background-color", resolved.get("background", "")))
                if len(cols) == 1:
                    doc_bg = cols[0]
            fg_cols = extract_colors("color", resolved.get("color", "")) if "color" in resolved else []
            if len(fg_cols) == 1:
                bg_raw = resolved.get("background-color", resolved.get("background"))
                bg_cols = extract_colors("background-color", bg_raw) if bg_raw else []
                if len(bg_cols) == 1 and bg_cols[0][3] == 1 and fg_cols[0][3] == 1:
                    contrast.append((r, fg_cols[0], bg_cols[0], "declared"))
                elif not bg_raw and fg_cols[0][3] == 1:
                    contrast.append((r, fg_cols[0], None, "assumed"))

    # contrast pairs (assumed background = body background, else white)
    base_bg = doc_bg if doc_bg and doc_bg[3] == 1 else (255, 255, 255, 1.0)
    pairs = []
    for r, fg, bg, src in contrast:
        bg = bg or base_bg
        ratio = contrast_ratio(fg, bg)
        pairs.append({"selector": r["selector"], "line": r["line"], "foreground": to_hex(fg), "background": to_hex(bg),
                      "background_source": src, "ratio": round(ratio, 2), "passes_AA_normal": ratio >= 4.5, "passes_AA_large": ratio >= 3.0})
    pairs.sort(key=lambda x: (x["ratio"], x["selector"]))

    # conflicts
    conflicts = []
    for (sel, ctx, prop), items in groups.items():
        if len(items) < 2 or prop.startswith("--"):
            continue
        imp = [i for i in items if i["important"]]
        winner = (imp or items)[-1]
        same_rule = len({i["rule"] for i in items}) == 1
        distinct = len({i["value"] for i in items}) > 1
        kind = ("same_rule_duplicate_possible_fallback" if same_rule else "overridden_by_later_rule") if distinct else "redundant_duplicate"
        conflicts.append({"selector": sel, "context": list(ctx), "property": prop, "kind": kind, "winning_value": winner["value"],
                          "declarations": [{"value": i["value"], "line": i["line"], "important": i["important"]} for i in items]})
    conflicts.sort(key=lambda c: (c["declarations"][0]["line"], c["property"]))

    # breakpoints
    bps, prefs = {}, set()
    for a in p.at_rules:
        if a["name"] != "media":
            continue
        for m in re.finditer(r"\(\s*(min|max)-width\s*:\s*([\d.]+)(px|em|rem)\s*\)", a["prelude"]):
            px = float(m.group(2)) * (1 if m.group(3) == "px" else ROOT_FONT_PX)
            bps[(num(px), m.group(1) + "-width")] = a["prelude"]
        for m in re.finditer(r"\(\s*width\s*(>=|<=|>|<)\s*([\d.]+)(px|em|rem)\s*\)", a["prelude"]):
            px = float(m.group(2)) * (1 if m.group(3) == "px" else ROOT_FONT_PX)
            bps[(num(px), "min-width" if m.group(1).startswith(">") else "max-width")] = a["prelude"]
        for m in re.finditer(r"\(\s*(prefers-[\w-]+)\s*:\s*([\w-]+)\s*\)", a["prelude"]):
            prefs.add(f"{m.group(1)}: {m.group(2)}")

    # spacing scale
    total = sum(spacing.values())
    base = None
    for cand in (8, 4, 5, 2):
        if total and sum(c for v, c in spacing.items() if v % cand == 0) / total >= 0.7:
            base = cand; break
    spacing_vals = sorted(spacing)

    # specificity
    spec_rows = sorted(({"selector": r["selector"], "specificity": list(r["specificity"]), "line": r["line"]} for r in p.rules),
                       key=lambda x: (tuple(-v for v in x["specificity"]), x["line"]))

    n_decl = sum(len(r["declarations"]) for r in p.rules)
    report = {
        "meta": {"source": source, "assumed_root_font_px": ROOT_FONT_PX,
                 "rules": len(p.rules), "declarations": n_decl, "at_rules": len(p.at_rules),
                 "imports": p.imports, "keyframes": sorted(p.keyframes)},
        "palette": [{"hex": h, "uses": e["uses"], "defined_as": sorted(e["defined_as"]), "properties": dict(sorted(e["properties"].items()))}
                    for h, e in sorted(palette.items(), key=lambda kv: (-kv[1]["uses"], kv[0]))],
        "variables": variables,
        "themes": themes,
        "scoped_variables": scoped,
        "typography": {
            "families": sorted(families.values(), key=lambda f: (-f["uses"], f["family"])),
            "font_sizes_px": [{"px": s["px"], "raw": sorted(s["raw"]), "uses": s["uses"]} for _, s in sorted(sizes.items())],
            "font_weights": dict(sorted(weights.items())),
            "font_faces": p.font_faces},
        "spacing": {"values_px": spacing_vals, "usage": {str(k): spacing[k] for k in spacing_vals},
                    "base_unit_px": base,
                    "off_grid_px": [v for v in spacing_vals if base and v % base != 0],
                    "unparsed_tokens": unparsed_spacing},
        "breakpoints": {"width": [{"px": px, "type": t, "query": q} for (px, t), q in sorted(bps.items())],
                        "preferences": sorted(prefs)},
        "specificity": {"highest": spec_rows[:5], "id_selectors": sum(1 for r in p.rules if r["specificity"][0] > 0),
                        "important_declarations": important},
        "conflicts": conflicts,
        "contrast": pairs,
        "issues": sorted(issues, key=lambda i: (i.get("line", 0), i["type"])),
    }
    return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def summarize(r: dict) -> str:
    L = [f"CSS design DNA  -  {r['meta']['source']}",
         f"  {r['meta']['rules']} rules, {r['meta']['declarations']} declarations, {r['meta']['at_rules']} at-rules", ""]
    L.append(f"PALETTE ({len(r['palette'])} colours)")
    for c in r["palette"]:
        L.append(f"  {c['hex']:<10} used {c['uses']}x  {('token ' + ', '.join(c['defined_as'])) if c['defined_as'] else ''}")
    L.append(f"\nVARIABLES ({len(r['variables'])}), themes: {len(r['themes'])}")
    t = r["typography"]
    L.append("\nTYPOGRAPHY")
    L.append("  families : " + ", ".join(f"{f['family']} ({f['uses']}x)" for f in t["families"]))
    L.append("  sizes px : " + ", ".join(str(s["px"]) for s in t["font_sizes_px"]))
    s = r["spacing"]
    L.append(f"\nSPACING  base unit: {s['base_unit_px']}px   values: {s['values_px']}   off-grid: {s['off_grid_px']}")
    b = r["breakpoints"]
    L.append("\nBREAKPOINTS  " + ", ".join(f"{x['type']} {x['px']}px" for x in b["width"]) + "   prefs: " + ", ".join(b["preferences"]))
    L.append(f"\nCONTRAST  ({sum(1 for c in r['contrast'] if not c['passes_AA_normal'])} of {len(r['contrast'])} pairs fail WCAG AA)")
    for c in r["contrast"]:
        if not c["passes_AA_normal"]:
            L.append(f"  {c['selector']:<12} {c['foreground']} on {c['background']} = {c['ratio']}:1 ({c['background_source']} bg)")
    L.append(f"\nCONFLICTS {len(r['conflicts'])}   ISSUES {len(r['issues'])}")
    for i in r["issues"]:
        L.append(f"  line {i.get('line', '?'):>3}  {i['type']}: {i['detail']}")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract structured design information from a CSS file.")
    ap.add_argument("css_file")
    ap.add_argument("-o", "--output", help="write JSON report to this path")
    a = ap.parse_args(argv)
    try:
        with open(a.css_file, encoding="utf-8", errors="replace") as f:
            css = f.read()
    except OSError as e:
        print(f"error: {e}", file=sys.stderr); return 2
    report = analyze(css, a.css_file)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=False)
        print(f"wrote {a.output}")
    print(summarize(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
