"""Run with:  python -m unittest discover -s tests -v   (from milestone2_agent/)

Includes *adversarial* backends that deliberately lie or behave non-deterministically,
to prove the guards (not the model's good behaviour) are what keeps answers honest."""
import itertools
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from agent import StyleAgent, check_consistency  # noqa: E402
from grounding import facts, verify  # noqa: E402
from tools import CssToolkit  # noqa: E402

CSS = (HERE.parent / "milestone1_css_parser" / "sample" / "site.css").read_text(encoding="utf-8")


class ScriptedBackend:
    """Calls the given tool, then returns whatever 'draft' answers it is given."""
    name = "scripted"

    def __init__(self, calls, drafts):
        self.calls, self.drafts = calls, itertools.cycle(drafts)

    def step(self, system, messages, specs):
        if not any(m["role"] == "tool" for m in messages):
            return {"type": "tool_calls", "calls": [{"id": f"c{i}", "name": n, "args": a} for i, (n, a) in enumerate(self.calls)]} if self.calls else {"type": "final", "text": next(self.drafts)}
        return {"type": "final", "text": next(self.drafts)}


class TestTools(unittest.TestCase):
    def setUp(self):
        self.t = CssToolkit(CSS)

    def test_not_found_is_explicit(self):
        r = self.t.call("get_css_variable", {"name": "--brand-pink"})
        self.assertEqual(r["status"], "not_found")
        self.assertIn("--brand-pink", r["message"])

    def test_variable_name_without_dashes(self):
        self.assertEqual(self.t.call("get_css_variable", {"name": "brand"})["data"]["resolved"], "#1e66f5")

    def test_unknown_tool_and_bad_args(self):
        self.assertEqual(self.t.call("delete_everything")["status"], "error")
        self.assertEqual(self.t.call("get_rule", {"wrong": 1})["status"], "error")

    def test_tools_are_deterministic(self):
        for name in ("get_palette", "check_contrast", "find_conflicts", "get_typography", "get_spacing"):
            self.assertEqual(CssToolkit(CSS).call(name), CssToolkit(CSS).call(name))


class TestGrounding(unittest.TestCase):
    def test_verify(self):
        ev = [{"data": {"hex": "#1e66f5", "px": 16, "ratio": 3.45}}]
        self.assertTrue(verify("brand is #1E66F5 at 16px, 3.45:1", ev)[0])
        ok, bad = verify("brand is #ff00ff", ev)
        self.assertFalse(ok); self.assertEqual(bad, ["#ff00ff"])
        self.assertFalse(verify("it is 17px", ev)[0])

    def test_facts_ignores_ratio_suffix_and_hex_digits(self):
        self.assertEqual(facts("4.5:1 on #1e66f5"), {"4.5", "#1e66f5"})


class TestAnswers(unittest.TestCase):
    def setUp(self):
        self.agent = StyleAgent(CSS)

    def test_answers_from_data(self):
        r = self.agent.ask("What is the --brand variable?")
        self.assertEqual(r.status, "answered")
        self.assertIn("#1e66f5", r.answer)

    def test_missing_variable_abstains(self):
        r = self.agent.ask("What is the value of --brand-pink?")
        self.assertEqual(r.status, "abstained")
        self.assertNotRegex(r.answer, r"#[0-9a-fA-F]{6}\b")      # no colour was invented

    def test_missing_selector_abstains(self):
        self.assertEqual(self.agent.ask("What font does h7 use?").status, "abstained")

    def test_out_of_scope_uses_no_tool(self):
        r = self.agent.ask("What is the capital of France?")
        self.assertEqual((r.status, r.trace), ("out_of_scope", []))

    def test_contrast_numbers_match_parser(self):
        r = self.agent.ask("Does .muted pass accessibility?")
        self.assertIn("3.45:1", r.answer)
        self.assertIn("fails", r.answer)


class TestAdversarialModels(unittest.TestCase):
    def test_model_invents_value_for_missing_variable(self):
        """Tool says not_found; the 'model' confidently makes up a colour anyway."""
        b = ScriptedBackend([("get_css_variable", {"name": "--brand-pink"})], ["--brand-pink is #ff69b4, a nice pink."])
        r = StyleAgent(CSS, b).ask("whatever")
        self.assertEqual(r.status, "abstained")
        self.assertNotIn("#ff69b4", r.answer)

    def test_model_answers_without_calling_any_tool(self):
        b = ScriptedBackend([], ["The brand colour is #ff00ff."])
        r = StyleAgent(CSS, b).ask("what is the brand colour?")
        self.assertEqual(r.status, "out_of_scope")
        self.assertNotIn("#ff00ff", r.answer)

    def test_model_misreports_real_data(self):
        """Tool returns #1e66f5; the 'model' says #ff00ff. Guard replaces it with the true value."""
        b = ScriptedBackend([("get_css_variable", {"name": "--brand"})], ["--brand is #ff00ff"])
        r = StyleAgent(CSS, b).ask("brand?")
        self.assertEqual(r.status, "fallback_ungrounded")
        self.assertIn("#ff00ff", r.unsupported)
        self.assertIn("#1e66f5", r.answer)
        self.assertNotIn("#ff00ff", r.answer)

    def test_model_corrects_itself_on_retry(self):
        b = ScriptedBackend([("get_css_variable", {"name": "--brand"})], ["--brand is #ff00ff", "--brand is #1e66f5"])
        self.assertEqual(StyleAgent(CSS, b).ask("brand?").status, "answered_after_retry")

    def test_model_miscounts(self):
        b = ScriptedBackend([("get_breakpoints", {})], ["There are 5 breakpoints: 480px and 768px."])
        r = StyleAgent(CSS, b).ask("breakpoints?")
        self.assertEqual(r.status, "fallback_ungrounded")
        self.assertIn("5", r.unsupported)


class TestConsistency(unittest.TestCase):
    def test_offline_agent_is_identical_twice(self):
        agent = StyleAgent(CSS)
        for q in ("Which colours fail contrast?", "What are the breakpoints?", "What is --accent?", "What is --nope?", "Hello?"):
            self.assertEqual(check_consistency(agent, q)["verdict"], "IDENTICAL", q)

    def test_same_question_twice_in_one_session(self):
        agent = StyleAgent(CSS)
        self.assertEqual(agent.ask("What is --brand?").answer, agent.ask("What is --brand?").answer)

    def test_detects_a_flaky_model(self):
        """A model that alternates between two different (both grounded) answers is flagged."""
        b = ScriptedBackend([("get_palette", {})], ["Colours: #1e66f5, #ffffff", "Colours: #8a8a8a, #ffffff"])
        v = check_consistency(StyleAgent(CSS, b), "palette?")
        self.assertEqual(v["verdict"], "INCONSISTENT")

    def test_reworded_but_same_facts_is_recognised(self):
        b = ScriptedBackend([("get_css_variable", {"name": "--brand"})], ["--brand resolves to #1e66f5.", "The value of --brand is #1e66f5."])
        self.assertEqual(check_consistency(StyleAgent(CSS, b), "brand?")["verdict"], "SAME_FACTS_DIFFERENT_WORDING")


if __name__ == "__main__":
    unittest.main()
