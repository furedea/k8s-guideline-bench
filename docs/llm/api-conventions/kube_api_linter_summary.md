# kube-api-linter reference for Beyond-Syntax review

This note summarizes the Kubernetes repository's enabled kube-api-linter rules for human review of API convention constraints.

Use this as supporting material, not as an automatic decision procedure.

## Scope

The Kubernetes repository enables kube-api-linter through `hack/golangci.yaml`. The plugin settings are included from:

```text
hack/kube-api-linter/kube-api-linter.yaml
```

The current Kubernetes configuration first disables all kube-api-linter rules and then explicitly enables 15 rules. Therefore, this reference focuses on the 15 enabled rules in `kube_api_linter_rules.csv`.

## How to use during review

- If a draft constraint directly corresponds to an enabled kube-api-linter rule, `Beyond-Syntax` is likely `false`.
- Do not mark `Beyond-Syntax=false` from keyword overlap alone.
- If a constraint requires semantic API design judgment, keep it as a human judgment even when related words appear in a linter rule.
- General Go linters and formatters are secondary baselines. Consider them only when the draft constraint is explicitly about formatting or generic Go style.

## Enabled rules

The enabled rule reference is in:

```text
docs/llm/api-conventions/kube_api_linter_rules.csv
```

The CSV is optimized for spreadsheet search. In particular, use the `Keywords` column to search from a draft constraint term such as `optional`, `condition`, `int32`, `json tag`, `listType`, `timestamp`, or `map`.

## Disabled visible rules

The Kubernetes config also shows several commented-out kube-api-linter rules:

```text
maxlength
nobools
nofloats
nophase
requiredfields
uniquemarkers
```

These are not enforcement rules in the current Kubernetes configuration. They can indicate that a convention is potentially tool-detectable, but they should not be used as direct evidence for `Beyond-Syntax=false`.

## Exceptions

Kubernetes also maintains:

```text
hack/kube-api-linter/exceptions.yaml
```

Exceptions do not mean the enabled rule is weak or disabled. They are an allowlist for existing API issues that cannot be fixed without compatibility risk. For review purposes, exceptions are useful evidence that a rule is tool-detectable, but compatibility may prevent applying the fix to old APIs.
