# CSS Design-DNA Parser + Tool-Using Style Auditor Agent
Skill First Labs - Tasks for Shortlisting (Milestone 1 + Milestone 2)

One idea ties both milestones together: **Milestone 1** turns a CSS file into structured *design DNA*;
**Milestone 2** is an AI agent whose tools are built on that parser, so it answers questions about a
stylesheet from real data instead of from the model's memory.

```
milestone1_css_parser/   css_dna.py  sample/site.css  tests/  output/site_report.json  NOTES.md
milestone2_agent/        agent.py tools.py grounding.py backends.py demo.py  tests/  transcripts/  NOTES.md
docs/Report.pdf          full report
```

## Run (Python 3.9+, no installs needed)
```bash
# Milestone 1
cd milestone1_css_parser
python css_dna.py sample/site.css -o output/site_report.json
python -m unittest discover -s tests -v          # 17 tests

# Milestone 2 (offline, deterministic, no API key)
cd ../milestone2_agent
python demo.py                                   # the demo-video walkthrough
python agent.py --css ../milestone1_css_parser/sample/site.css "Which colours fail contrast?"
python agent.py --css ../milestone1_css_parser/sample/site.css          # interactive chat
python agent.py --css ../milestone1_css_parser/sample/site.css --twice "What is --accent?"
python -m unittest discover -s tests -v          # 20 tests

# Optional: real Claude as the agent's brain
pip install anthropic && export ANTHROPIC_API_KEY=...
python demo.py --live          # model name overridable with CLAUDE_MODEL
```
Honest note: the offline backend is a rule-based planner standing in for an LLM so everything is
reproducible anywhere. The live Claude backend uses the same tools and the same guards, but it is
not covered by the automated tests because that requires an API key.

## Use on your own CSS
`python css_dna.py path/to/your.css` or `python agent.py --css path/to/your.css`
