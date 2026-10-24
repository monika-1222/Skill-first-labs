#!/usr/bin/env python3
"""
agent.py - Milestone 2: a small tool-using agent that answers questions about a CSS file.

    python agent.py --css ../milestone1_css_parser/sample/site.css "Which colours fail contrast?"
    python agent.py --css site.css                      # interactive chat
    python agent.py --css site.css --live "..."         # real Claude via the Anthropic API
    python agent.py --css site.css --twice "..."        # same-answer-twice consistency check

Safety design (see NOTES.md):
  1. Tool results carry an explicit status; "not_found" is data, not silence.
  2. If no tool produced data, the answer is written by CODE (abstain()), never by the model.
  3. Any draft that does produce data is verified fact-by-fact against the evidence;
     one unsupported hex / --variable / number => rejected, retried once, then replaced
     by a deterministic answer built from the tool data.
  4. check_consistency() re-asks from a clean state and compares tool trace, evidence
     hash and the set of facts in the answer.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import asdict, dataclass, field

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backends import SYSTEM_PROMPT, ClaudeBackend, OfflineBackend  # noqa: E402
from grounding import abstain, canonical, compose, evidence_hash, facts, verify  # noqa: E402
from tools import TOOL_SPECS, CssToolkit  # noqa: E402


@dataclass
class AgentResult:
    question: str
    answer: str
    status: str                     # answered | answered_after_retry | fallback_ungrounded | abstained | out_of_scope
    trace: list = field(default_factory=list)       # [{"tool","args","status"}]
    evidence_hash: str = ""
    unsupported: list = field(default_factory=list)  # facts the model invented (if any)
    backend: str = ""


class StyleAgent:
    def __init__(self, css_text: str, backend=None, source: str = "<css>", max_steps: int = 4):
        self.tools = CssToolkit(css_text, source)
        self.backend = backend or OfflineBackend()
        self.max_steps = max_steps

    def ask(self, question: str) -> AgentResult:
        """Stateless by design: each question starts from a clean slate, so a repeated
        question cannot be influenced by an earlier answer."""
        messages = [{"role": "user", "content": question}]
        results, trace, draft = [], [], None

        for _ in range(self.max_steps):
            out = self.backend.step(SYSTEM_PROMPT, messages, TOOL_SPECS)
            if out["type"] == "final":
                draft = out["text"]
                break
            messages.append({"role": "assistant", "calls": out["calls"]})
            for c in out["calls"]:
                res = self.tools.call(c["name"], c["args"])
                results.append(res)
                trace.append({"tool": c["name"], "args": c["args"], "status": res["status"]})
                messages.append({"role": "tool", "id": c["id"], "name": c["name"], "result": res})

        base = dict(question=question, trace=trace, evidence_hash=evidence_hash(results), backend=self.backend.name)
        ok_results = [r for r in results if r["status"] == "ok"]

        # Guard 1: no data -> code writes the answer, the model's draft is ignored.
        if not results:
            return AgentResult(answer=abstain([]), status="out_of_scope", **base)
        if not ok_results:
            return AgentResult(answer=abstain(results), status="abstained", **base)

        # Guard 2: data exists -> verify the draft against it.
        if draft:
            good, bad = verify(draft, results)
            if good:
                return AgentResult(answer=draft, status="answered", **base)
            messages.append({"role": "assistant", "text": draft})
            messages.append({"role": "user", "content": f"Your answer contains values that no tool returned: {', '.join(bad)}. "
                                                         "Rewrite it using only values from the tool results."})
            retry = self.backend.step(SYSTEM_PROMPT, messages, TOOL_SPECS)
            if retry["type"] == "final":
                good2, bad2 = verify(retry["text"], results)
                if good2 and retry["text"]:
                    return AgentResult(answer=retry["text"], status="answered_after_retry", unsupported=bad, **base)
                bad = sorted(set(bad) | set(bad2))
            return AgentResult(answer=compose(results), status="fallback_ungrounded", unsupported=bad, **base)

        return AgentResult(answer=compose(results), status="answered", **base)


# --------------------------------------------------------------------------
# "Same answer twice in a row"
# --------------------------------------------------------------------------

def check_consistency(agent: StyleAgent, question: str, runs: int = 2) -> dict:
    """Ask the same question `runs` times (clean state each time) and compare:
       - tool trace            (same tools, same arguments, same order)
       - evidence hash         (tools returned byte-identical data)
       - answer text           (exact)
       - answer facts          (same colours / numbers / names, wording may differ)"""
    rs = [agent.ask(question) for _ in range(runs)]
    first = rs[0]
    same_trace = all(canonical(r.trace) == canonical(first.trace) for r in rs)
    same_ev = all(r.evidence_hash == first.evidence_hash for r in rs)
    same_text = all(r.answer == first.answer for r in rs)
    same_facts = all(facts(r.answer) == facts(first.answer) for r in rs)
    verdict = ("IDENTICAL" if same_text and same_trace and same_ev else
               "SAME_FACTS_DIFFERENT_WORDING" if same_facts and same_trace and same_ev else "INCONSISTENT")
    return {"question": question, "runs": runs, "same_tool_trace": same_trace, "same_evidence": same_ev,
            "same_answer_text": same_text, "same_answer_facts": same_facts, "verdict": verdict,
            "answers": [r.answer for r in rs]}


# --------------------------------------------------------------------------

def _print(res: AgentResult):
    calls = ", ".join(f"{t['tool']}({json.dumps(t['args']) if t['args'] else ''})->{t['status']}" for t in res.trace) or "no tool used"
    print(f"\n  tools   : {calls}")
    print(f"  status  : {res.status}" + (f"   (rejected invented facts: {res.unsupported})" if res.unsupported else ""))
    print("  answer  :\n    " + res.answer.replace("\n", "\n    "))


def main(argv=None):
    ap = argparse.ArgumentParser(description="CSS design-audit agent")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--css", required=True)
    ap.add_argument("--live", action="store_true", help="use the real Claude API instead of the offline planner")
    ap.add_argument("--twice", action="store_true", help="run the same-answer-twice consistency check")
    a = ap.parse_args(argv)
    css = pathlib.Path(a.css).read_text(encoding="utf-8", errors="replace")
    agent = StyleAgent(css, ClaudeBackend() if a.live else OfflineBackend(), source=a.css)
    qs = [a.question] if a.question else None
    if qs is None:
        print("Ask about the stylesheet (empty line to quit).")
    while True:
        q = qs.pop(0) if qs else (input("\nyou> ").strip() if a.question is None else None)
        if not q:
            break
        if a.twice:
            print(json.dumps(check_consistency(agent, q), indent=2))
        else:
            _print(agent.ask(q))
    return 0


if __name__ == "__main__":
    sys.exit(main())
