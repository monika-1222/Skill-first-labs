"""
backends.py - the "brain" that decides which tool to call. Two interchangeable backends:

OfflineBackend    a deterministic intent router. No API key, no network, fully
                  reproducible - used for tests and for running the demo anywhere.
ClaudeBackend     real LLM tool-use via the Anthropic API (needs ANTHROPIC_API_KEY).

Both speak the same tiny protocol, so the agent loop, tools and grounding guard are
identical either way:

    step(system, messages, tool_specs) ->
        {"type": "tool_calls", "calls": [{"id", "name", "args"}]}
      | {"type": "final", "text": "..."}

Neutral message format used by the agent:
    {"role": "user", "content": str}
    {"role": "assistant", "calls": [...]}            # tool requests
    {"role": "tool", "id", "name", "result": dict}   # tool output
"""
from __future__ import annotations

import json
import os
import re

from grounding import compose

SYSTEM_PROMPT = """You are a CSS design-audit assistant. You answer questions about ONE stylesheet.

Rules:
1. Never answer from your own knowledge. Every colour, number, variable name or selector in your
   answer must come from a tool result in this conversation.
2. If a tool returns status "not_found" or "error", say plainly that the stylesheet does not
   contain that data. Do not guess, estimate, or suggest what the value "probably" is.
3. Do not do arithmetic or counting yourself; use the counts the tools return.
4. If no tool is relevant to the question, say you can only answer questions about the stylesheet.
5. Be concise. Quote values exactly as the tools return them."""


# --------------------------------------------------------------------------
class OfflineBackend:
    """Rule-based planner: question text -> tool calls -> answer built from tool data."""
    name = "offline-rules"

    INTENTS = [  # (tool, keywords) - order = order of calls
        ("check_contrast", ("contrast", "readab", "accessib", "wcag", "legib")),
        ("get_breakpoints", ("breakpoint", "responsive", "media quer", "@media", "mobile", "tablet", "dark mode", "reduced motion")),
        ("get_typography", ("font", "typograph", "typeface")),
        ("get_spacing", ("spacing", "margin", "padding", "gap", " grid", "8px grid", "4px grid")),
        ("find_conflicts", ("conflict", "override", "duplicate", "dead css", "redundant", "cascade")),
        ("get_palette", ("palette", "colours", "colors", "hex")),
    ]
    SELECTOR = re.compile(r"(?<![\w-])((?:[.#][\w-]+)(?:[.#:][\w-]+)*|h[1-9]|body|button)(?![\w-])", re.I)
    STOP = {"css", "custom", "the", "a", "an", "this", "that", "what", "which", "is", "of", "value", "called", "named", "color", "colour"}

    def _plan(self, q: str):
        ql = q.lower()
        calls = []
        names = re.findall(r"--[\w-]+", q)
        if not names:
            for pat in (r"(?:variable|token|property)\s+(?:called|named)?\s*[`'\"]?([\w-]+)", r"[`'\"]?([\w-]+)[`'\"]?\s+(?:variable|token)\b"):
                m = re.search(pat, ql)
                if m and m.group(1) not in self.STOP:
                    names = [m.group(1)]; break
        for n in names:
            calls.append(("get_css_variable", {"name": n}))
        sel = self.SELECTOR.search(q)
        sel = sel.group(1) if sel else None
        matched = [t for t, kws in self.INTENTS if any(k in ql for k in kws)]
        if "get_palette" in matched and (len(matched) > 1 or names) and "palette" not in ql:
            matched.remove("get_palette")                       # "colours" was just part of another question
        if "find_conflicts" in matched and "get_spacing" in matched and not any(k in ql for k in ("spacing", "grid")):
            matched.remove("get_spacing")                       # "conflicting padding" is not a spacing-grid question
        for tool in matched:
            if tool == "check_contrast":
                calls.append((tool, {"selector": sel} if sel else {}))
            elif tool == "find_conflicts":
                m = re.search(r"\b(padding|margin|color|font-size|background-color)\b", ql)
                calls.append((tool, {"property": m.group(1)} if m else {}))
            elif tool in ("get_typography", "get_spacing") and sel:
                calls.append(("get_rule", {"selector": sel}))   # "what font does h7 use?" -> look at that rule
            else:
                calls.append((tool, {}))
        if sel and not any(c[0] in ("get_rule", "check_contrast") for c in calls):
            calls.append(("get_rule", {"selector": sel}))
        seen, uniq = set(), []
        for name, args in calls:
            key = (name, json.dumps(args, sort_keys=True))
            if key not in seen:
                seen.add(key); uniq.append({"id": f"call_{len(uniq) + 1}", "name": name, "args": args})
        return uniq

    def step(self, system, messages, tool_specs):
        if any(m["role"] == "tool" for m in messages):
            return {"type": "final", "text": compose([m["result"] for m in messages if m["role"] == "tool"])}
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        calls = self._plan(question)
        if not calls:
            return {"type": "final", "text": ""}
        return {"type": "tool_calls", "calls": calls}


# --------------------------------------------------------------------------
class ClaudeBackend:
    """Real LLM backend. Not exercised by the offline test-suite (needs an API key)."""

    def __init__(self, model: str | None = None):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise SystemExit("pip install anthropic   (and set ANTHROPIC_API_KEY)") from e
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
        self.name = f"claude:{self.model}"

    @staticmethod
    def _to_api(messages):
        out, pending = [], []
        for m in messages:
            if m["role"] != "tool" and pending:
                out.append({"role": "user", "content": pending}); pending = []
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant" and "calls" in m:
                out.append({"role": "assistant", "content": [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m["calls"]]})
            elif m["role"] == "assistant":
                out.append({"role": "assistant", "content": m["text"]})
            elif m["role"] == "tool":
                pending.append({"type": "tool_result", "tool_use_id": m["id"], "content": json.dumps(m["result"], sort_keys=True)})
        if pending:
            out.append({"role": "user", "content": pending})
        return out

    def step(self, system, messages, tool_specs):  # pragma: no cover
        kw = dict(model=self.model, max_tokens=1000, system=system, tools=tool_specs, messages=self._to_api(messages))
        try:
            resp = self.client.messages.create(temperature=0, **kw)     # temperature 0 -> repeatable answers
        except Exception:
            resp = self.client.messages.create(**kw)                    # some models fix their own sampling
        calls = [{"id": b.id, "name": b.name, "args": dict(b.input)} for b in resp.content if b.type == "tool_use"]
        if calls:
            return {"type": "tool_calls", "calls": calls}
        return {"type": "final", "text": "".join(b.text for b in resp.content if b.type == "text")}
