# AI tools used

| Tool | What it was used for |
|---|---|
| **Claude Code** (Anthropic CLI, model Claude Opus 5.5) | I gave it the brief and a detailed prompt of my own (requirements and constraints). It inspected the workspace, proposed the design, and wrote the code, tests, generator, evaluator and docs. It ran the test suite and the end-to-end checks, and verified the research citations with web search. It also found and fixed two bugs during testing: a missed shock phrasing, and a 500 error on `NaN` input. At my request it ran a 14-case challenge in unseen styles, then fixed the 3 misses (a misspelling, a Hinglish shock phrase, and the `OOW` abbreviation) using offline word and phrase lists, adding regression and near-miss tests. |
| **UI UX Pro Max** (Claude Code skill, local search over UI/UX guidance) | Ran its design-system search ("enterprise internal tool service agent form") and a UX search on inline validation. The page uses its Swiss-minimal style, navy/blue palette, visible focus states, per-field errors linked by `aria-describedby`, a focusable error summary and the reduced-motion rule. Two suggestions were not used: Google Fonts and GSAP, because the page must load nothing from the network. |
| **VibeWise** (Claude Code plugin) | Not used to build the project. It was installed during the session but could not be loaded until Claude Code restarted, and its `learn` command can only be started by the user. I plan to use it afterwards to study the code; if I do, I will add that here. |

No AI service is called by the running application. Decisions come from the rules in `app/policy.py`.

I have reviewed the code and can explain it; [EXPLANATION.md](EXPLANATION.md) is my study guide. The choices listed in NOTES.md (null travel, the missing-data rule, threshold inclusivity, the confidence heuristic) were made deliberately, and each one is covered by tests.
