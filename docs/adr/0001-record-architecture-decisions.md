# ADR-0001: Record architecture decisions

- Status: Accepted
- Date: 2026-05-10

In the context of a benchmark whose conclusions hinge on evaluation methodology
(prompt strategies, judge model, scope definition),
facing the need to keep design rationale legible to future contributors and reviewers without duplicating it into tests or code,
we decided for keeping Architecture Decision Records under `docs/adr/` in Y-Statement form, one decision per file, sequentially numbered, immutable after acceptance, and superseded by writing a new ADR,
to achieve a traceable history of why decisions were made and what alternatives were rejected,
accepting the small overhead of creating a new file for each non-trivial decision.
