"""Run with:  python -m unittest discover -s tests -v   (from milestone1_css_parser/)"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from css_dna import analyze, contrast_ratio, parse_color, resolve_vars, specificity, strip_comments  # noqa: E402

SAMPLE = pathlib.Path(__file__).resolve().parents[1] / "sample" / "site.css"


class TestEdgeCases(unittest.TestCase):
    def test_braces_and_semicolons_inside_strings_and_urls(self):
        css = 'a { content: "x;y}z"; background: url(data:image/png;base64,AA;BB}CC) no-repeat; color: #fff; }'
        r = analyze(css)
        self.assertEqual(r["meta"]["rules"], 1)
        self.assertEqual(r["meta"]["declarations"], 3)   # nothing was split in the middle
        self.assertEqual(r["issues"], [])

    def test_braces_inside_comments_are_ignored(self):
        css = "/* } { fake rule { color: red } */ p { color: blue }"
        r = analyze(css)
        self.assertEqual([c["hex"] for c in r["palette"]], ["#0000ff"])
        self.assertEqual(r["meta"]["rules"], 1)

    def test_last_declaration_without_semicolon(self):
        r = analyze("p { margin: 8px; padding: 16px }")
        self.assertEqual(r["spacing"]["values_px"], [8, 16])

    def test_unterminated_block_is_reported_not_crashed(self):
        r = analyze("p { color: red; ")
        self.assertTrue(any("unterminated" in i["detail"] for i in r["issues"]))
        self.assertEqual(r["palette"][0]["hex"], "#ff0000")

    def test_stray_closing_brace(self):
        r = analyze("} p { color: red }")
        self.assertTrue(any("stray" in i["detail"] for i in r["issues"]))
        self.assertEqual(r["meta"]["rules"], 1)

    def test_empty_file(self):
        r = analyze("")
        self.assertEqual(r["meta"]["rules"], 0)

    def test_css_nesting(self):
        r = analyze(".card { color: #000; &:hover { color: #111; } .title { color: #222; } }")
        sels = [x["selector"] for x in r["specificity"]["highest"]]
        self.assertIn(".card:hover", sels)
        self.assertIn(".card .title", sels)


class TestVariables(unittest.TestCase):
    def test_chain_fallback_missing_cycle(self):
        env = {"--a": "var(--b)", "--b": "#fff", "--x": "var(--y)", "--y": "var(--x)"}
        self.assertEqual(resolve_vars("var(--a)", env), ("#fff", "ok"))
        self.assertEqual(resolve_vars("var(--nope, 4px)", env), ("4px", "fallback"))
        self.assertEqual(resolve_vars("var(--nope)", env), (None, "missing"))
        self.assertEqual(resolve_vars("var(--x)", env, ()), (None, "cycle"))
        self.assertEqual(resolve_vars("calc(var(--a) + 1px)", {"--a": "2px"}), ("calc(2px + 1px)", "ok"))

    def test_dark_theme_is_separate_from_base(self):
        r = analyze(":root{--bg:#fff} @media (prefers-color-scheme: dark){:root{--bg:#000}}")
        self.assertEqual(r["variables"]["--bg"]["resolved"], "#fff")
        self.assertEqual(r["themes"][0]["variables"], {"--bg": "#000"})


class TestColoursAndContrast(unittest.TestCase):
    def test_formats_normalise_to_same_hex(self):
        for tok in ("#f00", "#ff0000", "rgb(255,0,0)", "rgb(255 0 0)", "hsl(0, 100%, 50%)", "red"):
            self.assertEqual(parse_color(tok)[:3], (255, 0, 0), tok)

    def test_alpha(self):
        self.assertAlmostEqual(parse_color("rgba(0,0,0,.5)")[3], 0.5)
        self.assertAlmostEqual(parse_color("rgb(0 0 0 / 50%)")[3], 0.5)

    def test_wcag_reference_values(self):
        self.assertAlmostEqual(contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, places=1)
        self.assertAlmostEqual(contrast_ratio((119, 119, 119), (255, 255, 255)), 4.48, places=2)

    def test_hex_in_url_fragment_is_not_a_colour(self):
        r = analyze("a { background: url(icon.svg#abc) }")
        self.assertEqual(r["palette"], [])

    def test_named_colour_in_font_family_is_not_a_colour(self):
        r = analyze('a { font-family: "Tomato Grotesk", sans-serif }')
        self.assertEqual(r["palette"], [])


class TestSpecificity(unittest.TestCase):
    def test_values(self):
        self.assertEqual(specificity("a"), (0, 0, 1))
        self.assertEqual(specificity(".a .b"), (0, 2, 0))
        self.assertEqual(specificity("#a .b a:hover::before"), (1, 2, 2))
        self.assertEqual(specificity(":where(#id) p"), (0, 0, 1))
        self.assertEqual(specificity(":not(#id, .x)"), (1, 0, 0))
        self.assertEqual(specificity('a[href="x.y#z"]'), (0, 1, 1))


class TestSampleFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = analyze(SAMPLE.read_text(encoding="utf-8"), str(SAMPLE))

    def test_deterministic(self):
        again = analyze(SAMPLE.read_text(encoding="utf-8"), str(SAMPLE))
        self.assertEqual(json.dumps(self.r, sort_keys=True), json.dumps(again, sort_keys=True))

    def test_expected_findings(self):
        r = self.r
        self.assertEqual(r["meta"]["rules"], 20)
        self.assertEqual([b["px"] for b in r["breakpoints"]["width"]], [480, 768])
        self.assertEqual(r["spacing"]["base_unit_px"], 4)
        self.assertEqual(r["spacing"]["off_grid_px"], [10, 15, 18])
        self.assertEqual(r["variables"]["--alias"]["resolved"], "#1e66f5")
        self.assertEqual(r["variables"]["--loop-a"]["status"], "cycle")
        failing = {c["selector"] for c in r["contrast"] if not c["passes_AA_normal"]}
        self.assertIn(".muted", failing)
        kinds = {(c["selector"], c["property"]): c["kind"] for c in r["conflicts"]}
        self.assertEqual(kinds[(".btn", "padding")], "overridden_by_later_rule")
        self.assertEqual(kinds[(".legacy", "color")], "same_rule_duplicate_possible_fallback")
        self.assertEqual(len(r["specificity"]["important_declarations"]), 1)


if __name__ == "__main__":
    unittest.main()
