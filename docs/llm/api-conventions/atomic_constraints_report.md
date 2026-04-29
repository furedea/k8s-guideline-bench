# API Conventions Atomic Constraints Report

## 概要

- 元文書: `docs/source/api-conventions.md`
- reviewed normative: `223`
- atomic constraints: `73`
- unique normative sources used: `70`

この `73` 件は，reviewed normative をそのまま 1:1 で写したものではありません．
`223` 件の normative を見て，

- 1 diff / 1 type 定義 / 1 field 定義で観測しやすいか
- benchmark の判定単位として十分に局所的か
- 規約として再利用しやすいか
- atomic に分解したときに意味が保てるか

を基準に，人手で atomic 化した結果です．

## 223 から 73 にした理由

`normative` には，規約そのものだけでなく，次のような文も多く含まれています．

- 背景説明
- 設計上の動機
- 例示
- 反例
- 将来の可能性
- 許容される設計の幅を説明する `may` 文
- semantic には重要だが，そのままでは 1 diff で裁きにくい哲学的ガイド

こうした文を全部 atomic にすると，constraint set が膨らみすぎるだけでなく，

- judge が不安定になる
- overlapping constraints が増える
- 同じ変更を複数 constraint が重複して裁く
- benchmark の failure reason が読みにくくなる

ので，atomic set ではかなり絞っています．

## 選定基準

atomic に残したのは，主に次の条件を満たすものです．

1. 観測可能
   - 1 PR / 1 diff / 1 API type の変更で確認しやすい

2. 局所的
   - 1 constraint が 1 つの要求だけを表す

3. 判定しやすい
   - machine か LLM で比較的一貫して判定できる

4. 再利用可能
   - 特定の example や歴史的事情ではなく，複数タスクに適用できる

5. 規約として独立
   - 背景説明や補足ではなく，constraint として独立に読める

## atomic に残した規約の型

### 1. 構造・shape

最も残しやすい類型です．

- `kind`
- `apiVersion`
- `metadata.namespace`
- `metadata.name`
- `metadata.uid`
- `/status` subresource
- `spec` / `status`
- `conditions` を `status` top-level に置く

これらは local で，judgeability が高いです．

代表例:

- `atom_001` Include kind field
- `atom_002` Include apiVersion field
- `atom_009` Provide status subresource
- `atom_015` Put conditions at top level of status

### 2. naming

field 名，kind 名，reference field 名などの naming rule も残しやすいです．

- PascalCase / camelCase
- `_` や `-` を使わない
- declarative naming
- `{field}Ref`
- `somethingTime`
- lowercase dashed keys

代表例:

- `atom_041` Use PascalCase for Go field names
- `atom_042` Use camelCase for JSON field names
- `atom_046` Use declarative field and resource names
- `atom_048` Use somethingTime suffix
- `atom_049` Use lowercase dashed map keys

### 3. requiredness / optionality / serialization

Kubernetes API では field requiredness と serialization の規約が重要なので，ここも多く残しています．

- field は optional / required のどちらか
- 新規 field は `+optional` / `+required` を明示
- required field unset を reject
- `bool` field は pointer
- `bool` field は `omitempty`
- date は RFC3339
- duration は integer + unit suffix

代表例:

- `atom_023` Mark every field optional or required
- `atom_024` Tag new fields explicitly
- `atom_025` Reject unset required fields
- `atom_026` Use pointers for bool fields
- `atom_027` Use omitempty for bool fields
- `atom_034` Serialize dates as RFC3339 strings
- `atom_035` Represent durations as integer+unit fields

### 4. validation

validation 系は benchmark として価値が高いので，かなり残しています．

- declarative validation を prefer
- requiredness を validation でも確認
- string format / max length
- numeric bounds
- list max size
- listType
- uniqueness
- map max size
- map key validation

代表例:

- `atom_053` Prefer declarative validation
- `atom_054` Validate requiredness explicitly
- `atom_055` Validate string formats
- `atom_057` Bounds-check numeric fields
- `atom_059` Set listType tags
- `atom_060` Validate uniqueness for set/map lists
- `atom_062` Validate map keys

### 5. error message wording

この文書では error message wording も明確に規約化されているので，ここは atomic にしやすいです．

- positive requirement は `must`
- negative formatting requirement は `must not`
- negative behavioral requirement は `may not`
- literal string は single quotes
- field 名は back-quotes
- inequality は記号でなく words

代表例:

- `atom_063` Use must for positive requirements
- `atom_064` Use must not for negative formatting requirements
- `atom_065` Use may not for negative behavioral requirements
- `atom_066` Quote literal strings with single quotes
- `atom_067` Quote field names with back-quotes
- `atom_068` Use words for inequalities

### 6. controller / status behavior

semantic judgmentは少し入りますが，project-specific で重要なので残しています．

- `status` を premature に見せない ordering
- interrupted control loop で idempotent / consistent
- allocated object の lifecycle / linkage を考慮

代表例:

- `atom_071` Actuate before status when necessary
- `atom_072` Handle interrupted control loops idempotently
- `atom_073` Account for allocated object lifecycle and linkage

## atomic にしなかったもの

### 1. 例示だけの文

example としては useful でも，それ自体は規約でないものは落としました．

例:

- 特定 flag 値の例
- historical example
- unsafe example

### 2. 背景説明

理由や設計哲学を説明しているだけで，constraint として独立しない文は落としました．

例:

- ある設計がなぜ危険か
- なぜその規約が必要か
- UX や implementation hazard の説明

### 3. 許容範囲の説明

`may` を含んでいても，benchmark の constraint としては弱い permission 文は落としました．

例:

- alternative representation がありうる
- future version で別 encoding を認めるかもしれない
- optional な convenience の説明

### 4. 1 atomic にするには広すぎるもの

重要ではあっても，そのままだと設計原則レベルで広すぎるものは，今回は落とすか，もっと局所的な部分だけ残しました．

例:

- broad philosophy としての API design guidance
- 章全体の設計思想

## 1 normative から複数 atomic に割った例

典型例は naming rule です．

元の normative:

- Go field names must be PascalCase.
- JSON field names must be camelCase.
- names should almost always match.
- no underscores or dashes.

これは 1 本の normative から次の atomic に割っています．

- `atom_041` Use PascalCase for Go field names
- `atom_042` Use camelCase for JSON field names
- `atom_043` Avoid underscores and dashes in field names
- `atom_044` Match Go and JSON field names

## 複数 normative を 1 atomic にまとめた例

`phase` まわりは 2 本の normative を 1 atomic にまとめました．

- `norm_057` `phase` is deprecated
- `norm_058` newer APIs should use conditions instead

これを atomic では

- `atom_018` Prefer conditions over phase

に統合しています．

## judgeability

- `machine_checkable`: `32`
- `hybrid`: `21`
- `llm_checkable`: `20`

`machine_checkable` が多いのは，

- field shape
- naming
- tag
- serialization
- error message wording

のように明示的な surface form を持つ rule が多いからです．

`llm_checkable` は，

- declarative naming
- semantic API design
- controller ordering
- context-rich prefixes

のように，semantic judgment を含む rule に集中しています．

## 出力

- atomic JSON: `docs/llm/api-conventions/atomic_constraints.json`
- adopted はこの report の対象外
