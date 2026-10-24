"""Builds Report.pdf (figures + text). Run:  python build_report.py"""
import json, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

HERE = pathlib.Path(__file__).resolve().parent
R = json.loads((HERE.parent / "milestone1_css_parser/output/site_report.json").read_text())

# ---------------- figures ----------------
def box(ax, x, y, w, h, text, fc, ec="#333", fs=8.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs)

def arrow(ax, a, b):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12, lw=1.3, color="#444"))

fig, ax = plt.subplots(figsize=(10, 4.6)); ax.set_xlim(0, 10); ax.set_ylim(0, 4.6); ax.axis("off")
ax.text(0.1, 4.35, "MILESTONE 1  -  css_dna.py", fontsize=9.5, weight="bold", color="#1e66f5")
box(ax, 0.1, 3.2, 1.3, 0.8, "site.css", "#eef3ff")
box(ax, 1.8, 3.2, 1.7, 0.8, "Scanner\n(strings, parens,\ncomments)", "#dfe9ff")
box(ax, 3.9, 3.2, 1.5, 0.8, "Rules +\nat-rules tree", "#dfe9ff")
box(ax, 5.8, 3.2, 2.0, 0.8, "Analysis: var() resolve,\npalette, scales, WCAG,\nspecificity, conflicts", "#dfe9ff")
box(ax, 8.2, 3.2, 1.6, 0.8, "Design-DNA\nJSON report", "#c9dcff")
for a, b in [((1.4, 3.6), (1.8, 3.6)), ((3.5, 3.6), (3.9, 3.6)), ((5.4, 3.6), (5.8, 3.6)), ((7.8, 3.6), (8.2, 3.6))]: arrow(ax, a, b)
ax.text(0.1, 2.55, "MILESTONE 2  -  style auditor agent", fontsize=9.5, weight="bold", color="#b4237a")
box(ax, 0.1, 1.5, 1.3, 0.8, "Question", "#fff0f8")
box(ax, 1.8, 1.5, 1.7, 0.8, "Brain (backend)\nOffline rules  or\nClaude tool-use", "#ffdff0")
box(ax, 3.9, 1.5, 1.7, 0.8, "8 tools\nok / not_found /\nerror envelope", "#ffdff0")
box(ax, 6.0, 1.5, 1.8, 0.8, "Grounding guard\nfact-check every\nhex / --var / number", "#ffc6e3")
box(ax, 8.2, 1.5, 1.6, 0.8, "Answer", "#fff0f8")
for a, b in [((1.4, 1.9), (1.8, 1.9)), ((3.5, 1.9), (3.9, 1.9)), ((5.6, 1.9), (6.0, 1.9)), ((7.8, 1.9), (8.2, 1.9))]: arrow(ax, a, b)
arrow(ax, (9.0, 3.2), (4.75, 2.3))
ax.text(7.3, 2.92, "tools are built on the parser", fontsize=8, style="italic", color="#444")
box(ax, 3.9, 0.15, 1.9, 0.75, "no data  ->  code writes\nthe abstention", "#f4f4f4", fs=8)
box(ax, 6.1, 0.15, 3.7, 0.75, "bad draft -> retry once -> deterministic answer\nbuilt from tool data only", "#f4f4f4", fs=8)
arrow(ax, (4.75, 1.5), (4.75, 0.9)); arrow(ax, (6.9, 1.5), (7.6, 0.9))
fig.savefig(HERE / "fig_architecture.png", dpi=170, bbox_inches="tight"); plt.close(fig)

fig, (a1, a2) = plt.subplots(2, 1, figsize=(8.6, 5.2), gridspec_kw={"height_ratios": [1, 1.5]})
pal = [c for c in R["palette"] if len(c["hex"]) == 7]
for i, c in enumerate(pal):
    a1.add_patch(plt.Rectangle((i, 0), 0.92, 1, fc=c["hex"], ec="#999", lw=0.8))
    a1.text(i + 0.46, -0.18, c["hex"], ha="center", va="top", fontsize=6.3, rotation=40)
a1.set_xlim(0, len(pal)); a1.set_ylim(-0.1, 1); a1.axis("off"); a1.set_title("Extracted palette (normalised hex)", fontsize=10, loc="left")
pairs = sorted(R["contrast"], key=lambda p: p["ratio"])
labels = [p["selector"][:26] for p in pairs]; vals = [p["ratio"] for p in pairs]
a2.barh(labels, vals, color=["#d64545" if v < 4.5 else "#3aa76d" for v in vals])
a2.axvline(4.5, color="#222", ls="--", lw=1); a2.text(4.55, -0.45, "WCAG AA 4.5", fontsize=7)
a2.set_xlabel("contrast ratio (:1)", fontsize=8); a2.tick_params(labelsize=7); a2.set_title("WCAG contrast of every text/background pair", fontsize=10, loc="left")
fig.tight_layout(); fig.savefig(HERE / "fig_palette_contrast.png", dpi=170); plt.close(fig)

# ---------------- document ----------------
ss = getSampleStyleSheet()
B = ParagraphStyle("B", parent=ss["BodyText"], fontSize=10, leading=14.2, alignment=TA_JUSTIFY, spaceAfter=6)
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=16, textColor=colors.HexColor("#1b2a4a"), spaceBefore=10, spaceAfter=6)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12, textColor=colors.HexColor("#1e66f5"), spaceBefore=8, spaceAfter=4)
SM = ParagraphStyle("SM", parent=B, fontSize=8.6, leading=11.5, alignment=0)
CODE = ParagraphStyle("CODE", fontName="Courier", fontSize=7.8, leading=10, backColor=colors.HexColor("#f4f6fa"), borderPadding=5, leftIndent=4, spaceAfter=8)
TITLE = ParagraphStyle("T", parent=ss["Title"], fontSize=24, textColor=colors.HexColor("#1b2a4a"), leading=28)
CELL = ParagraphStyle("C", parent=SM, fontSize=8.4, leading=10.6)

def P(t, s=B): return Paragraph(t, s)
def tbl(rows, widths, head=True):
    data = [[P(str(c), CELL) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c2d6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if head: st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe9ff"))]
    t.setStyle(TableStyle(st)); return t

def footer(c, d):
    c.saveState(); c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#777"))
    c.drawString(2 * cm, 1.2 * cm, "CSS Design-DNA Parser and Style Auditor Agent  -  Skill First Labs shortlisting tasks")
    c.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {d.page}"); c.restoreState()

S = []
S += [Spacer(1, 2.2 * cm), P("CSS Design-DNA Parser<br/>and Style Auditor Agent", TITLE), Spacer(1, 6),
      P("Report for the Skill First Labs <i>Tasks for Shortlisting</i> - Milestone 1 (Parser) and Milestone 2 (Agent)", ParagraphStyle("st", parent=B, fontSize=12, alignment=0)),
      Spacer(1, 10)]
S += [P("<b>Summary.</b> Both milestones are built around one idea: <b>a stylesheet is a design system in disguise, and an AI agent should "
        "answer questions about it from facts, never from imagination.</b> Milestone 1 is a dependency-free CSS parser that extracts a site's "
        "<i>design DNA</i> (palette, variables, type and spacing scales, breakpoints, specificity, dead CSS and WCAG contrast) as structured JSON. "
        "Milestone 2 is a tool-using agent whose tools are built on that parser. It refuses to invent values when data is missing and it is "
        "tested to give the same answer twice. Everything runs offline with the Python standard library; a real Claude backend is included as an option.")]
S += [P("1. What the assignment asks, and where each requirement is met", H1)]
S += [tbl([
    ["Requirement (from the task slide)", "Where it is satisfied"],
    ["M1: parser that reads a CSS file and pulls out meaningful, structured information, not just raw text", "<font face='Courier'>css_dna.py</font> returns a 10-section structured report (Section 2)"],
    ["M1: keep it simple", "One file, standard library only, one function: <font face='Courier'>analyze(css) -> dict</font>"],
    ["M1: 3-4 lines on what was extracted and why, and one edge case", "<font face='Courier'>milestone1_css_parser/NOTES.md</font>, summarised in 2.4 and 2.5"],
    ["M2: small AI agent using a couple of tools instead of answering from model knowledge", "8 tools in <font face='Courier'>tools.py</font>; the agent loop in <font face='Courier'>agent.py</font> (Section 3)"],
    ["M2: 3-4 lines on not making up an answer when it has no data", "<font face='Courier'>milestone2_agent/NOTES.md</font>, expanded in 3.3"],
    ["M2: how you would check it gives the same answer twice in a row", "<font face='Courier'>check_consistency()</font> plus tests (3.4)"],
    ["Submission: demo video by email, source code via GitHub URL, before 24 Oct 2026, 8:00 PM", "Source tree is ready to push; video storyboard in Section 6"],
], [8.2 * cm, 8.8 * cm])]
S += [PageBreak(), P("2. Milestone 1 - the CSS design-DNA parser", H1)]
S += [P("2.1 Idea", H2),
      P("A plain parser would list selectors and properties. That is just the raw text in a different shape. The useful questions are higher level: "
        "<i>which colours does this site really use, is its spacing on a grid, which rules are dead, does the text meet accessibility contrast?</i> "
        "So the parser extracts <b>meaning</b>, and it resolves things a human would resolve: <font face='Courier'>var(--alias)</font> becomes "
        "<font face='Courier'>#1e66f5</font>, <font face='Courier'>2.5rem</font> becomes 40px, <font face='Courier'>hsl()</font> and named colours become hex.")]
S += [Image(str(HERE / "fig_architecture.png"), width=17 * cm, height=17 * cm * 4.6 / 10 * 0.98), P("<i>Figure 1. Architecture of both milestones.</i>", SM)]
S += [P("2.2 What is extracted", H2), tbl([
    ["Section", "Content", "Why it is useful"],
    ["palette", "All colours normalised to hex with usage counts and the variables that define them", "Spot palette drift (near-duplicate colours)"],
    ["variables / themes", "Custom properties resolved through var() chains and fallbacks; dark-mode overrides kept separate", "The real value of a token, not its alias"],
    ["typography", "Font families, size scale in px, weights, @font-face", "Type system at a glance"],
    ["spacing", "margin/padding/gap values, inferred base unit (8/4/5/2px), off-grid outliers", "Detect broken rhythm"],
    ["breakpoints", "min/max-width and range syntax, plus prefers-color-scheme / reduced-motion", "Responsive and accessibility coverage"],
    ["specificity", "(ids, classes, elements) per rule, highest 5, !important list", "Maintainability hot spots"],
    ["conflicts", "Overridden or duplicated declarations, winner chosen with !important rules", "Dead CSS"],
    ["contrast", "WCAG ratio for every colour/background pair (page background assumed when none declared, and labelled so)", "Accessibility audit"],
    ["issues", "Unresolved var(), var() cycles, malformed or unterminated CSS with line numbers", "Honest error reporting"],
], [2.8 * cm, 8.2 * cm, 6 * cm])]
S += [Spacer(1, 6), Image(str(HERE / "fig_palette_contrast.png"), width=14.5 * cm, height=14.5 * cm * 5.2 / 8.6),
      P("<i>Figure 2. Real output of the parser on sample/site.css: palette and WCAG contrast. Red bars fail AA (4.5:1).</i>", SM)]
fails = [c for c in R["contrast"] if not c["passes_AA_normal"]]
S += [P("2.3 Results on the sample file", H2),
      P(f"The 60-line sample stylesheet contains {R['meta']['rules']} rules and {R['meta']['declarations']} declarations. The parser finds {len(R['palette'])} distinct colours, "
        f"a {R['spacing']['base_unit_px']}px spacing grid with off-grid values {R['spacing']['off_grid_px']}, breakpoints at "
        f"{', '.join(str(b['px']) + 'px' for b in R['breakpoints']['width'])}, {len(fails)} of {len(R['contrast'])} contrast pairs failing WCAG AA "
        f"(worst: <font face='Courier'>{fails[0]['selector']}</font> at {fails[0]['ratio']}:1), {len(R['conflicts'])} conflicting declarations, "
        f"and {len(R['issues'])} issues (one var() cycle, one missing variable, one fallback used).")]
S += [P("2.4 Why these choices (the '3-4 lines')", H2),
      P("I extracted the information a designer, reviewer or accessibility audit actually needs, and returned it as structured JSON so another program can "
        "query it. That last point is deliberate: it is what makes the Milestone 2 agent possible. Resolving <font face='Courier'>var()</font> matters because "
        "modern CSS hides most values behind tokens, so a parser that does not resolve them reports <font face='Courier'>var(--brand)</font> instead of a colour.")]
S += [P("2.5 Edge cases considered", H2),
      P("<b>The main one:</b> <font face='Courier'>;</font> and <font face='Courier'>}</font> can appear inside strings and "
        "<font face='Courier'>url(data:...)</font> values, and braces can appear in comments. Splitting on those characters (the common shortcut) corrupts the parse. "
        "A small scanner tracks quotes, parentheses and comments instead. The sample file contains exactly these traps "
        "(<font face='Courier'>content: \"a;b{c}\"</font>, a base64 font URL with <font face='Courier'>;</font> and <font face='Courier'>}</font>, a comment containing a brace) and "
        "the output is still correct. Others handled and tested: var() cycles and missing variables (reported, not crashed), last declaration without a semicolon, "
        "unterminated block, stray <font face='Courier'>}</font>, empty file, CSS nesting with <font face='Courier'>&amp;</font>, "
        "<font face='Courier'>:where/:not/:is</font> specificity, a hex-like fragment in <font face='Courier'>url(icon.svg#abc)</font>, a colour word inside "
        "<font face='Courier'>font-family: \"Tomato Grotesk\"</font>, and an intentional fallback (<font face='Courier'>color: #f00; color: rgb(255 0 0 / .5)</font>) "
        "which is labelled a possible fallback instead of a bug.")]
S += [P("3. Milestone 2 - the style auditor agent", H1)]
S += [P("3.1 Idea", H2),
      P("The agent answers questions such as <i>'Which colours fail contrast?'</i> or <i>'What is --brand?'</i> about a stylesheet. It never answers from model knowledge: "
        "its eight tools are thin wrappers over the Milestone 1 parser, so the same trustworthy facts feed both parts. This makes the project one coherent system and "
        "makes the anti-hallucination goal testable, because every fact in an answer can be traced to a tool result.")]
S += [tbl([
    ["Tool", "Returns"],
    ["get_palette", "All colours, usage counts, defining variables"],
    ["get_css_variable(name)", "Raw and resolved value, dark-mode overrides; not_found with did-you-mean"],
    ["check_contrast(selector?)", "WCAG ratio for one rule or a failing-pairs summary, with the 4.5 / 3.0 thresholds"],
    ["get_breakpoints, get_typography, get_spacing", "Responsive queries, type scale, spacing grid"],
    ["find_conflicts(property?)", "Overridden / duplicated declarations and the winner"],
    ["get_rule(selector)", "Declarations of an exact selector with var() resolved; not_found if absent"],
], [5.6 * cm, 11.4 * cm])]
S += [P("3.2 Two interchangeable brains", H2),
      P("<b>OfflineBackend</b> is a deterministic intent router: it picks tools from the question, then builds the answer from tool data. It needs no API key, so the project, tests and demo "
        "run anywhere. <b>ClaudeBackend</b> uses the Anthropic tool-use API (temperature 0, strict system prompt). Both implement one method, so the loop, tools and guards are identical. "
        "<b>Honest limitation:</b> the offline backend is rule-based, not an LLM, and the live backend is not covered by automated tests because it needs a key.")]
S += [P("3.3 How it avoids making up an answer (the '3-4 lines')", H2),
      P("Four layers, ordered from strongest to weakest, and the first two do not depend on the model behaving well:")]
S += [tbl([
    ["Layer", "Mechanism", "Effect"],
    ["1. Explicit absence", "Every tool returns status ok / not_found / error. Missing data is a value, not an empty string.", "The model can tell 'no data' from 'data'"],
    ["2. Code writes the refusal", "If no tool returned ok data, <font face='Courier'>abstain()</font> produces the reply. The model's draft is not even read.", "--brand-pink and h7 cannot be invented. Questions needing no tool (capital of France) also get a fixed refusal"],
    ["3. Fact-check the draft", "Extract every hex colour, --variable and number from the draft; each must appear in the tool outputs. One miss rejects the draft, one retry is allowed, then a deterministic answer built from tool data replaces it.", "A model that misreports #1e66f5 as #ff00ff, or says '9 breakpoints', is overridden"],
    ["4. Prompt rules", "System prompt: no outside knowledge, quote tool values, do not count or compute.", "Reduces how often layer 3 fires"],
], [3.2 * cm, 8.3 * cm, 5.5 * cm])]
S += [P("The guard fails closed: it may reject a correct answer that contains an unlisted number (for example 'WCAG 2.1'), in which case the user still receives a correct, if plainer, "
        "deterministic answer. I accepted that trade-off because a false rejection costs style, while a false acceptance costs trust. A limitation worth stating: the guard verifies "
        "<i>values</i>, not <i>meaning</i>, so a model could in principle attach a real value to the wrong claim. Tool outputs keep each value next to its label to make that harder.")]
S += [P("3.4 How it is checked that it gives the same answer twice", H2),
      P("Two sources of variation exist: the tools and the model. Tools are pure and deterministic (sorted output, no clocks or randomness). The agent keeps <b>no memory between questions</b>, "
        "so an earlier answer cannot influence a later one, and the Claude backend uses temperature 0. On top of that, <font face='Courier'>check_consistency(agent, question)</font> "
        "re-asks from a clean state and compares four things:")]
S += [tbl([
    ["Compared", "How", "Catches"],
    ["Tool-call trace", "Canonical JSON of (tool, arguments, status)", "Different plan for the same question"],
    ["Evidence hash", "SHA-256 of canonical tool outputs", "Non-deterministic tools / changed data"],
    ["Answer text", "Exact string equality", "Any change at all"],
    ["Answer facts", "Set of hex / --vars / numbers in the answer", "Reworded (fine) vs changed facts (bad)"],
], [3.4 * cm, 6.8 * cm, 6.8 * cm]),
    Spacer(1, 4),
    P("Verdicts: <b>IDENTICAL</b>; <b>SAME_FACTS_DIFFERENT_WORDING</b> (acceptable for an LLM); <b>INCONSISTENT</b>. Separating exact text from facts matters because a real LLM may rephrase "
      "while staying correct, and the check should not cry wolf. In production I would also run it on a schedule against a fixed question set and alert on any INCONSISTENT verdict.")]
S += [PageBreak(), P("4. Testing and results", H1),
      P("37 automated tests pass (17 for Milestone 1, 20 for Milestone 2). The most informative ones use <b>adversarial models</b> that lie on purpose, which tests the guards rather than the model's good behaviour:")]
S += [tbl([
    ["Scenario", "What the (fake) model does", "Observed behaviour"],
    ["Missing variable", "Tool says not_found; model confidently says '--brand-pink is #ff69b4'", "status = abstained; #ff69b4 never appears"],
    ["No tool called", "Model answers 'brand colour is #ff00ff' directly", "status = out_of_scope; refusal text"],
    ["Misreported data", "Tool returns #1e66f5; model says #ff00ff", "status = fallback_ungrounded; answer shows #1e66f5; #ff00ff listed as rejected"],
    ["Miscounting", "Model says '5 breakpoints'", "'5' rejected; deterministic answer returned"],
    ["Self-correction", "Wrong first draft, right second draft", "status = answered_after_retry"],
    ["Flaky model", "Alternates between two different grounded answers", "check_consistency = INCONSISTENT"],
    ["Rewording model", "Two different sentences, same facts", "SAME_FACTS_DIFFERENT_WORDING"],
    ["Normal operation", "Offline agent, 5 questions asked twice", "IDENTICAL every time"],
], [3.2 * cm, 7 * cm, 6.8 * cm])]
S += [Spacer(1, 6), P("Excerpt of the demo transcript (full file: milestone2_agent/transcripts/demo_transcript.txt):", SM),
      Preformatted(
"Q: What is the value of --brand-pink?\n"
"  tools  : get_css_variable({\"name\": \"--brand-pink\"})->not_found\n"
"  status : abstained\n"
"  answer : I don't have that data in this stylesheet, so I can't give you a value:\n"
"           - No custom property named '--brand-pink' exists in this stylesheet.\n"
"             Closest names that do exist: --brand-dark, --brand\n"
"           I won't guess a value that isn't in the file.\n\n"
"Q: What is --brand?   (model forced to lie: '#ff00ff, and 9 breakpoints')\n"
"  status : fallback_ungrounded  (rejected invented facts: ['#ff00ff', '9'])\n"
"  answer : --brand resolves to #1e66f5.", CODE)]
S += [P("5. Limitations and next steps", H1),
      P("The parser covers the common CSS surface but is not a full CSS3 grammar: only a subset of named colours is recognised, rem/em use an assumed 16px root (stated in the report metadata), "
        "<font face='Courier'>calc()</font> and viewport units are not converted, and contrast ignores inherited colours and large-text detection. The contrast check labels the page background as "
        "<i>assumed</i> when a rule does not declare one, instead of silently guessing. For the agent, next steps would be running the live-model path against a larger question set, "
        "adding a semantic check that each value is attached to the right label, and exposing the tools through an MCP server so other assistants can reuse them.")]
S += [P("6. Deliverables and demo-video plan", H1),
      P("<b>Source code</b> (for the GitHub URL): the project folder, with README, tests and requirements. <b>Report:</b> this PDF. <b>Demo video</b> (about 3 minutes, to be emailed): "
        "(1) 30 s - run the parser on the sample and show the summary; (2) 20 s - open the sample file and point at the trap lines (the base64 URL, the comment with a brace); "
        "(3) 60 s - run <font face='Courier'>python demo.py</font> and narrate sections A to D: normal answers, then --brand-pink and h7 refused, then the lying model being overridden; "
        "(4) 30 s - the same-answer-twice verdicts; (5) 20 s - run both test suites showing 37 passing.")]
S += [Spacer(1, 4), P("<b>Run it:</b>", SM), Preformatted(
"cd milestone1_css_parser && python css_dna.py sample/site.css && python -m unittest discover -s tests\n"
"cd ../milestone2_agent   && python demo.py && python -m unittest discover -s tests", CODE)]

doc = SimpleDocTemplate(str(HERE / "Report.pdf"), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
                        title="CSS Design-DNA Parser and Style Auditor Agent", author="Skill First Labs shortlisting submission")
doc.build(S, onFirstPage=footer, onLaterPages=footer)
print("built", HERE / "Report.pdf")
