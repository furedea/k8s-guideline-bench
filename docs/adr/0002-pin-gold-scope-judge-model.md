# ADR-0002: Pin gold-scope judge model to the strategy judge model

- Status: Accepted
- Date: 2026-05-10

In the context of comparing context-injection strategies (`no_constraints`, `api_conventions_md`, `atomic_constraints_73_json`) on the same dataset where the strategy-side judge currently varies the `effective_total` (denominator) per strategy because applicability is decided from the predicted patch,
facing the need to give all strategies a strategy-independent, comparable denominator without doubling judge inference cost or amplifying judge-model disagreement noise,
we decided for defining the per-PR gold improvement scope as constraints the human gold patch newly satisfies (`verdict=compliant` and `patch_effect=applied_by_patch`) by judging the human gold patch once in `JudgeMode.PATCH_ONLY` with the **same judge model used for strategy judgments** (`sonnet`, claude-sonnet-4-6 via `claude_cli_client`), persisting the judgments under `<results_root>/gold_scope/<instance>/judgments.json`, and using that improvement scope as the common denominator in a separate fair-summary post-processor — and against alternative gold-scope judges (Opus 4.7, Haiku 4.5, multi-judge majority vote),
to achieve a fair, strategy-independent denominator of human-demonstrated improvement opportunities whose verdicts share the same evaluator mental model as the numerator at minimal extra cost,
accepting that scope still depends on a single LLM judgment, that swapping the strategy judge model requires re-running the gold-scope pass to stay consistent, and that strategy improvements outside the gold improvement scope are reported only as a side metric rather than counted in the primary newly-satisfied rate.
