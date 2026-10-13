# A deterministic, explainable policy engine for appliance repair-vs-replace decisions

*Research notes for the Bruviti Campus Drive 2026 take-home (use case 2). Written 13 October 2026.*

## Abstract

Service agents decide whether a faulty appliance should be repaired or replaced, and the brief reports that they apply the written policy inconsistently. This prototype encodes the supplied policy (rules D0–D6) as a deterministic engine. It computes the repair cost exactly, applies the rules in the stated precedence, and escalates the cases the policy cannot settle, giving a one-sentence reason each time. Free-text symptoms are read with offline regular expressions and NegEx-style negation scoping, used only for the two text-based escalation triggers (safety hazards and contradictions). The literature below informed *engineering* choices: rules over learned models, input validation, negation handling, boundary testing and metric choice. **It does not validate the policy thresholds themselves.** Those come from Bruviti's confidential brief, and no published source here says anything about them.

## 1. Problem and intended user

- **User:** a service agent, or a downstream system, holding one confirmed-fault case.
- **Task:** return `repair` / `replace` / `escalate`, the D0 repair cost, a confidence and a reason.
- **Grading:** macro-F1 over the three decisions, plus the share of cost estimates within 10% of Bruviti's, on hidden cases that "will not look like yours". The brief says judgement about data and testing "counts as much as the metric", but it gives **no numeric weighting**, and I do not assume one.

## 2. Three kinds of claim in this document

| Kind | Examples |
|---|---|
| **Facts from the brief** (authoritative; not reproduced here because the brief is confidential) | The thresholds 60/50/40/70%, 21 days, 120 minutes, 24 months; the precedence; the cost formula; the expected-life table; the three examples |
| **Findings from external sources** | Cited inline, listed in §6 |
| **My engineering hypotheses** | Marked *Hypothesis*. Untested against real data |

## 3. Method and design decisions

**3.1 Rules, not a learned model.** The brief provides the decision policy, and the graders' labels presumably follow it. Rudin (2019) argues that for high-stakes decisions an inherently interpretable model is preferable to explaining a black box after the fact, and that interpretable models often lose little or no accuracy. Here the "model" *is* the policy, so a learned approximation of it can only add error. *Hypothesis:* a classifier trained on rule-generated labels would score at best equal to the rules on the hidden set, and worse near thresholds.

**3.2 Trustworthiness properties as acceptance criteria.** The NIST AI RMF 1.0 (NIST, 2023) treats validity and reliability, safety, accountability and transparency, and explainability and interpretability as characteristics of trustworthy AI systems. I turned those into checks the code must pass:
- every response names its deciding rule;
- `?explain=true` exposes every check the engine ran;
- identical input gives identical output (tested);
- uncertain cases escalate instead of guessing;
- an unexpected internal error returns `escalate` for human review rather than a 500.

**3.3 Input validation.** The OWASP Input Validation Cheat Sheet recommends allowlist validation of categorical values, type and range checks, and semantic validation, applied as early as possible. Accordingly:
- enums are matched against Appendix F after normalising case and spacing, plus a small explicit synonym table, and anything else is rejected;
- numeric fields must be finite and non-negative;
- nested `parts` items are validated individually.

Pydantic (v2) does this declaratively. FastAPI turns failures into HTTP 422 responses.

*Finding from my tests:* the default 422 handler echoes the offending value, which crashes JSON serialisation when that value is `NaN`. A custom handler returns only the location and message.

**3.4 Exact arithmetic at thresholds.** Binary floating point cannot represent most decimal fractions exactly (Python documentation, "Floating-Point Arithmetic: Issues and Limitations"). A strict test such as "cost exceeds 60% of the replacement price" could therefore flip on rounding error. The engine converts each input to an exact `Fraction` via its decimal text, and rounds only for output.

**3.5 Negation in symptom text.** "No sparks or smoke" must not trigger the safety escalation. NegEx (Chapman et al., 2001) showed that a simple rule — a negation trigger followed, within a short window, by the term — identifies negated findings in clinical text with high specificity. I adapted the idea:
- the negation scope extends only across filler words and coordinated lists ("no A, B or C");
- any other word ends the scope, so "not cooling, sparks at plug" still reports sparks.

*Hypothesis:* hazard recall on real tickets will be lower than on my corpus, because of unseen vocabulary. That is the most important limitation (DATA.md).

**3.6 Conservative contradiction detection.** The brief's example (`not_cooling` with text about a door that will not close) defines a contradiction as text describing a different fault from the structured field. To avoid escalating everything, which the brief warns "scores badly", a contradiction requires the text to describe only fault families incompatible with the declared one. Text with no recognised vocabulary is never a contradiction. *Hypothesis:* precision is high and recall moderate. This is untested on real tickets.

**3.7 Boundary-value testing.** Errors cluster at the edges of input classes (Myers, Badgett & Sandler, 2011). Every threshold is tested at, just inside and just outside its value: 60.0% vs 60.01%, 21 vs 22 days, 120 vs 121 minutes, 24 vs 25 months, and 70% of expected life for each of the seven categories.

**3.8 Offline, in-process API tests.** FastAPI's `TestClient` calls the application directly without a running server (FastAPI documentation, "Testing"). The test session also patches socket and DNS calls to raise an error, so any network access fails the suite.

**3.9 Metric.** Macro-F1 averages per-class F1, so each class weighs the same regardless of frequency (Sokolova & Lapalme, 2009). Two consequences:
- escalating everything gives zero F1 on repair and replace, which explains the brief's warning;
- the synthetic corpus is balanced roughly evenly across the three decisions, and `scripts/evaluate.py` implements macro-F1 directly (checked against a hand-computed example) instead of depending on scikit-learn.

## 4. Risks and limitations

- **Data:** the corpus is synthetic and written by me, so a 100% self-check score shows consistency with my reading of the policy, not predictive validity.
- **Text:** the keyword detectors are English-only and miss unseen phrasing.
- **Ambiguity:** several points are ambiguous (null travel, null lead time, null age, the "2 percentage points" wording), and the hidden labels may follow a different reading. Each choice is documented in NOTES.md and isolated in one function.
- **Confidence:** a documented heuristic, not a calibrated probability.
- **Validation:** none against real repair outcomes, costs or customer data. No user research was done.

## 5. Conclusion

For a supplied, explicit policy, a deterministic engine with exact arithmetic, allowlist validation, conservative text heuristics and boundary-focused tests gives reproducible, auditable decisions in well under one second, with no network dependency. The open risk is natural-language variation in symptom text. The next step that matters is evaluation on real anonymised tickets.

## 6. References

1. Bruviti. *Campus Drive 2026 — Use case 2: Repair vs replace classification* (confidential assignment brief), 2026. The source of all business rules; not reproduced.
2. National Institute of Standards and Technology. *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, NIST AI 100-1, January 2023. https://doi.org/10.6028/NIST.AI.100-1 · https://www.nist.gov/itl/ai-risk-management-framework
3. OWASP Cheat Sheet Series. *Input Validation Cheat Sheet.* https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html
4. FastAPI documentation. *Testing.* https://fastapi.tiangolo.com/tutorial/testing/
5. Pydantic documentation. *Validators.* https://docs.pydantic.dev/latest/concepts/validators/
6. Python documentation. *Floating-Point Arithmetic: Issues and Limitations.* https://docs.python.org/3/tutorial/floatingpoint.html
7. Chapman, W. W., Bridewell, W., Hanbury, P., Cooper, G. F., & Buchanan, B. G. (2001). A simple algorithm for identifying negated findings and diseases in discharge summaries. *Journal of Biomedical Informatics*, 34(5), 301–310. https://doi.org/10.1006/jbin.2001.1029
8. Rudin, C. (2019). Stop explaining black box machine learning models for high stakes decisions and use interpretable models instead. *Nature Machine Intelligence*, 1, 206–215. https://doi.org/10.1038/s42256-019-0048-x (preprint: https://arxiv.org/abs/1811.10154)
9. Sokolova, M., & Lapalme, G. (2009). A systematic analysis of performance measures for classification tasks. *Information Processing & Management*, 45(4), 427–437. https://doi.org/10.1016/j.ipm.2009.03.002
10. Myers, G. J., Badgett, T., & Sandler, C. (2011). *The Art of Software Testing* (3rd ed.). Wiley. (Boundary-value analysis.)
11. scikit-learn documentation. *Metrics and scoring: quantifying the quality of predictions* (definition of macro-averaged F1). https://scikit-learn.org/stable/modules/model_evaluation.html — consulted for the definition; the library is not a dependency.
