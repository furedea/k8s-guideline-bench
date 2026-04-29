# API Conventions Atomic Selection Guide

このファイルは，`atomic_constraints.json` を人手で選別しやすくするためのガイドです．

- `おすすめ`: `高` / `中` / `低`
- `参照数`: まだ未集計
- `judgeability`: atomic JSON の値をそのまま転記

## Resources / Metadata

### atom_001 Include kind field

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_014`
- 参照数: 未集計
- 規約: All JSON objects returned by an API include a `kind` field.
- 解説: API object の基本 shape を定める規約です．局所的で判定しやすいです．

### atom_002 Include apiVersion field

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_015`
- 参照数: 未集計
- 規約: All JSON objects returned by an API include an `apiVersion` field.
- 解説: API versioning の基本 shape を定める規約です．局所的で判定しやすいです．

### atom_003 Include metadata.namespace

- おすすめ: `中`
- judgeability: `machine_checkable`
- 元 normative: `norm_016`
- 参照数: 未集計
- 規約: Every object kind includes `metadata.namespace`.
- 解説: namespaced object の shape 規約です．object 種別によっては適用範囲の確認が要ります．

### atom_004 Include metadata.name

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_017`
- 参照数: 未集計
- 規約: Every object kind includes `metadata.name`.
- 解説: 個体識別の基本規約です．多くの API object で重要です．

### atom_005 Include metadata.uid

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_018`
- 参照数: 未集計
- 規約: Every object kind includes `metadata.uid`.
- 解説: 再作成後の識別に関わる metadata 規約です．重要ですが metadata 全体の文脈が少し要ります．

### atom_006 Treat resourceVersion as opaque

- おすすめ: `中`
- judgeability: `hybrid`
- 元 normative: `norm_019`
- 参照数: 未集計
- 規約: Clients treat `metadata.resourceVersion` as opaque and pass it back unmodified.
- 解説: `resourceVersion` を意味解釈しないための互換性規約です．semantic な判断が少し入ります．

## Spec / Status

### atom_007 Use declarative spec fields

- おすすめ: `高`
- judgeability: `llm_checkable`
- 元 normative: `norm_028`
- 参照数: 未集計
- 規約: Fields in `spec` use declarative rather than imperative names and semantics.
- 解説: imperative でなく declarative にする API 設計規約です．重要ですが semantic です．

### atom_008 Ignore status on PUT and POST

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_029`
- 参照数: 未集計
- 規約: PUT and POST on objects ignore `status` values.
- 解説: status を read-modify-write で壊さないための更新規約です．かなり重要です．

### atom_009 Provide status subresource

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_030`
- 参照数: 未集計
- 規約: Resources managed through status updates provide a `/status` subresource.
- 解説: status 管理の中心になる subresource 規約です．benchmark 向きです．

### atom_010 Use spec and status for varying state

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_033`
- 参照数: 未集計
- 規約: Objects whose actual state may vary from user intent have both `spec` and `status`.
- 解説: spec/status を使い分ける大枠の設計規約です．やや broad です．

### atom_011 No extra top-level fields beside spec/status and metadata

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_035`
- 参照数: 未集計
- 規約: Objects that contain both `spec` and `status` do not add other top-level fields beyond standard metadata.
- 解説: top-level field を増やしすぎない shape 規約です．局所的です．

## Conditions

### atom_012 Conditions complement detailed status

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_038`
- 参照数: 未集計
- 規約: Conditions complement more detailed status information rather than replacing it.
- 解説: conditions を詳細 status の代替にしないという役割分担の規約です．

### atom_013 Treat conditions as keyed map

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_040`
- 参照数: 未集計
- 規約: Condition collections are treated as maps keyed by `type`.
- 解説: conditions の collection semantics を定める規約です．かなり扱いやすいです．

### atom_014 Follow standard conditions schema

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_048`
- 参照数: 未集計
- 規約: Conditions follow the standard `metav1.Condition` schema.
- 解説: 標準 `metav1.Condition` schema に寄せる規約です．

### atom_015 Put conditions at top level of status

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_049`
- 参照数: 未集計
- 規約: Conditions are included as a top-level element in `status`.
- 解説: conditions の置き場所を定める shape 規約です．

### atom_016 Require Reason field

- おすすめ: `中`
- judgeability: `machine_checkable`
- 元 normative: `norm_050`
- 参照数: 未集計
- 規約: Condition entries include the `Reason` field.
- 解説: condition entry の必須 field 規約です．

### atom_017 Use PascalCase condition types

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_051`
- 参照数: 未集計
- 規約: Condition type names use PascalCase.
- 解説: condition type の naming 規約です．

### atom_018 Prefer conditions over phase

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_057, norm_058`
- 参照数: 未集計
- 規約: Newer API types use conditions instead of `phase`.
- 解説: `phase` から conditions へ移る方針をまとめた規約です．

## Primitive Types / Constants

### atom_019 Use int32 or int64 for public integers

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_063`
- 参照数: 未集計
- 規約: Public integer fields use Go `int32` or `int64`, not `int`.
- 解説: primitive integer type の選択規約です．非常に明確です．

### atom_020 Serialize oversized integers as strings

- おすすめ: `中`
- judgeability: `hybrid`
- 元 normative: `norm_064`
- 参照数: 未集計
- 規約: Numeric fields that can exceed JSON-safe integer precision are serialized and accepted as strings.
- 解説: JSON-safe precision を超える数の扱いを定める規約です．field 意味の判断が要ります．

### atom_021 Use Kubernetes constant style

- おすすめ: `低`
- judgeability: `llm_checkable`
- 元 normative: `norm_068`
- 参照数: 未集計
- 規約: APIs within Kubernetes use the documented constant naming style.
- 解説: constant style 全般を指すため少し広いです．

### atom_022 Use CamelCase for new flag values

- おすすめ: `中`
- judgeability: `machine_checkable`
- 元 normative: `norm_069`
- 参照数: 未集計
- 規約: New flag values use CamelCase only.
- 解説: new flag value の naming 規約です．対象は限定的です．

## Optional / Required / Defaulting / Serialization

### atom_023 Mark every field optional or required

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_099`
- 参照数: 未集計
- 規約: Every field is marked as either optional or required.
- 解説: requiredness を空欄にしないための基本規約です．

### atom_024 Tag new fields explicitly

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_105`
- 参照数: 未集計
- 規約: New fields explicitly set either `+optional` or `+required`.
- 解説: 新規 field で tag を必ず明示する規約です．かなり強いです．

### atom_025 Reject unset required fields

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_106`
- 参照数: 未集計
- 規約: The API server does not allow POST or PUT requests with required fields unset.
- 解説: required field 未設定を reject する validation 規約です．

### atom_026 Use pointers for bool fields

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_108`
- 参照数: 未集計
- 規約: `bool` fields use pointer types.
- 解説: `bool` field の shape 規約です．

### atom_027 Use omitempty for bool fields

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_108`
- 参照数: 未集計
- 規約: `bool` fields use the `omitempty` tag.
- 解説: `bool` field の serialization 規約です．

### atom_028 Static defaults depend only on the object

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_115`
- 参照数: 未集計
- 規約: Static defaulting considers only the object being operated upon.
- 解説: static defaulting が external state を見ないための決定性規約です．

### atom_029 Admission-defaulted fields are optional

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_117`
- 参照数: 未集計
- 規約: Fields initialized by admission-controlled defaults are strictly optional.
- 解説: admission default の結果として field を required にしない規約です．

### atom_030 Controller-defaulted fields are optional

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_119`
- 参照数: 未集計
- 規約: Fields initialized by controllers are strictly optional.
- 解説: controller default の結果として field を required にしない規約です．

### atom_031 Defaulting only sets previously unset fields

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_122`
- 参照数: 未集計
- 規約: Defaulting only sets previously unset fields.
- 解説: defaulting を additive に限定する規約の 1 つ目です．

### atom_032 Defaulting only adds map keys

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_123`
- 参照数: 未集計
- 規約: Defaulting only adds keys to maps.
- 解説: defaulting を additive に限定する規約の 2 つ目です．

### atom_033 Defaulting only adds mergeable array values

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_124`
- 参照数: 未集計
- 規約: Defaulting only adds values to arrays with mergeable semantics.
- 解説: defaulting を additive に限定する規約の 3 つ目です．

### atom_034 Serialize dates as RFC3339 strings

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_133`
- 参照数: 未集計
- 規約: Dates are serialized as RFC3339 strings.
- 解説: date serialization の明確な規約です．

### atom_035 Represent durations as integer+unit fields

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_136`
- 参照数: 未集計
- 規約: Duration fields are represented as integer fields with units in the field name.
- 解説: duration field の表現規約です．

## References / Response / Events

### atom_036 Keep namespaced references in-namespace

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_138`
- 参照数: 未集計
- 規約: Object references on a namespaced type usually refer only to objects in the same namespace.
- 解説: cross-namespace reference を避ける設計規約です．semantic です．

### atom_037 Name reference fields with Ref suffix

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_140`
- 参照数: 未集計
- 規約: Reference field names use the `{field}Ref` format.
- 解説: reference field naming の明確な規約です．

### atom_038 Use single-value fieldPath

- おすすめ: `中`
- judgeability: `hybrid`
- 元 normative: `norm_151`
- 参照数: 未集計
- 規約: `fieldPath` points to a single value and uses field selector notation.
- 解説: `fieldPath` の shape 規約です．やや文脈依存です．

### atom_039 Prefer HTTP header semantics over duplicate status fields

- おすすめ: `低`
- judgeability: `llm_checkable`
- 元 normative: `norm_154`
- 参照数: 未集計
- 規約: When a status field duplicates a standard HTTP header meaning and that header is returned, the HTTP header takes priority.
- 解説: HTTP header と status field が重なる場合の precedence 規約です．benchmark には少し乗せにくいです．

### atom_040 Generate user-relevant events

- おすすめ: `低`
- judgeability: `llm_checkable`
- 元 normative: `norm_162`
- 参照数: 未集計
- 規約: Generate events for situations users or administrators should be alerted about.
- 解説: event を出すべき状況の broad なガイドです．

## Naming / Labels / Annotations

### atom_041 Use PascalCase for Go field names

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_163`
- 参照数: 未集計
- 規約: Go field names use PascalCase.
- 解説: Go field naming の基本規約です．

### atom_042 Use camelCase for JSON field names

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_163`
- 参照数: 未集計
- 規約: JSON field names use camelCase.
- 解説: JSON field naming の基本規約です．

### atom_043 Avoid underscores and dashes in field names

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_163`
- 参照数: 未集計
- 規約: Go and JSON field names do not contain underscores or dashes.
- 解説: field naming で `_` や `-` を避ける規約です．

### atom_044 Match Go and JSON field names

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_163`
- 参照数: 未集計
- 規約: Go and JSON field names almost always match except for initial capitalization.
- 解説: Go/JSON field 名の整合性を求める規約です．

### atom_045 Use declarative field and resource names

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_164`
- 参照数: 未集計
- 規約: Field and resource names are declarative rather than imperative.
- 解説: imperative でなく declarative に naming する規約です．

### atom_046 Avoid FooController kind names

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_165`
- 参照数: 未集計
- 規約: Kinds do not use the deprecated `FooController` naming pattern.
- 解説: deprecated な kind naming を避ける規約です．

### atom_047 Use somethingTime suffix

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_166`
- 参照数: 未集計
- 規約: Fields representing the time when something occurs are named `somethingTime`, not `stamp`.
- 解説: time field naming の明確な規約です．

### atom_048 Use lowercase dashed map keys

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_184`
- 参照数: 未集計
- 規約: Label and annotation key names are all lowercase with words separated by dashes.
- 解説: label / annotation key format の規約です．

### atom_049 Prefix non-user labels and annotations

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_185`
- 参照数: 未集計
- 規約: Labels and annotations other than end-user keys are prefixed.
- 解説: user 用以外の map key を prefix 付きにする規約です．

### atom_050 Prefer kubernetes.io for new keys

- おすすめ: `中`
- judgeability: `machine_checkable`
- 元 normative: `norm_187`
- 参照数: 未集計
- 規約: New label and annotation map keys use the `kubernetes.io` form rather than `k8s.io`.
- 解説: `kubernetes.io` と `k8s.io` の使い分け規約です．

### atom_051 Use context-rich key prefixes

- おすすめ: `低`
- judgeability: `llm_checkable`
- 元 normative: `norm_189`
- 参照数: 未集計
- 規約: Label and annotation key prefixes carry as much context as possible.
- 解説: prefix に十分な context を持たせる規約で，semantic judgment が要ります．

## Validation / Error Messages

### atom_052 Prefer declarative validation

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_192`
- 参照数: 未集計
- 規約: New APIs prefer declarative validation where it supports the rule.
- 解説: validation の実装方針に近い規約です．

### atom_053 Validate requiredness explicitly

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_193`
- 参照数: 未集計
- 規約: Fields are declared optional or required, and validation checks that requiredness.
- 解説: requiredness を declaration と validation の両方で扱う規約です．

### atom_054 Validate string formats

- おすすめ: `中`
- judgeability: `hybrid`
- 元 normative: `norm_194`
- 参照数: 未集計
- 規約: Almost all string fields are checked for format.
- 解説: `almost all` が入るので少し曖昧ですが，string validation の大枠です．

### atom_055 Validate string maximum length

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_196`
- 参照数: 未集計
- 規約: String fields are checked for maximum length.
- 解説: string max length の明確な validation 規約です．

### atom_056 Bounds-check numeric fields

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_199`
- 参照数: 未集計
- 規約: Numeric fields are bounds-checked for both minimum and maximum values.
- 解説: numeric bounds の明確な validation 規約です．

### atom_057 Validate list maximum size

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_200`
- 参照数: 未集計
- 規約: List fields are checked for maximum size.
- 解説: list max size の明確な validation 規約です．

### atom_058 Set listType tags

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_202`
- 参照数: 未集計
- 規約: List fields have their `listType` tag set.
- 解説: `listType` tag の明確な shape 規約です．

### atom_059 Validate uniqueness for set/map lists

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_203`
- 参照数: 未集計
- 規約: Lists with set or map semantics are checked for uniqueness.
- 解説: set/map semantic list の uniqueness 規約です．

### atom_060 Validate map maximum size

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_204`
- 参照数: 未集計
- 規約: Map fields are checked for maximum size.
- 解説: map max size の validation 規約です．

### atom_061 Validate map keys

- おすすめ: `高`
- judgeability: `hybrid`
- 元 normative: `norm_206`
- 参照数: 未集計
- 規約: Map fields validate their keys as well as their values.
- 解説: map key validation を要求する規約です．

### atom_062 Use must for positive requirements

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_207`
- 参照数: 未集計
- 規約: Positive validation requirements use the word `must`.
- 解説: positive requirement wording の規約です．

### atom_063 Use must not for negative formatting requirements

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_208`
- 参照数: 未集計
- 規約: Negative formatting requirements use the phrase `must not`.
- 解説: negative formatting wording の規約です．

### atom_064 Use may not for negative behavioral requirements

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_209`
- 参照数: 未集計
- 規約: Negative behavioral requirements use the phrase `may not`.
- 解説: negative behavioral wording の規約です．

### atom_065 Quote literal strings with single quotes

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_210`
- 参照数: 未集計
- 規約: Literal string values in validation messages are written in single quotes.
- 解説: literal string の quoting 規約です．

### atom_066 Quote field names with back-quotes

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_211`
- 参照数: 未集計
- 規約: Referenced field names in validation messages are written in back-quotes.
- 解説: field name の quoting 規約です．

### atom_067 Use words for inequalities

- おすすめ: `高`
- judgeability: `machine_checkable`
- 元 normative: `norm_212`
- 参照数: 未集計
- 規約: Validation messages express inequalities with words rather than symbols.
- 解説: inequality wording の規約です．

## Allocated Values / Controller Behavior

### atom_068 Verify user-requested allocated values

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_217`
- 参照数: 未集計
- 規約: The system does not trust user-specified allocated values and verifies or confirms them before use.
- 解説: allocated value の安全性に関する規約です．重要ですが semantic です．

### atom_069 Prefer status for new APIs in this pattern

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_219`
- 参照数: 未集計
- 規約: New APIs use `status` for this pattern.
- 解説: この pattern では `status` を使うべきという API design 規約です．

### atom_070 Controllers consider async ordering

- おすすめ: `低`
- judgeability: `llm_checkable`
- 元 normative: `norm_220`
- 参照数: 未集計
- 規約: Controller implementations take care around ordering of asynchronous operations.
- 解説: async ordering 全般の broad な controller 規約です．

### atom_071 Actuate before status when necessary

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_221`
- 参照数: 未集計
- 規約: If exposing `status` before actuation would be problematic, controllers actuate first and update `status` afterward.
- 解説: status 更新前後の ordering を定める規約です．

### atom_072 Handle interrupted control loops idempotently

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_222`
- 参照数: 未集計
- 規約: Controllers handle interrupted control loops in an idempotent and consistent way.
- 解説: interrupted loop でも idempotent / consistent に扱う規約です．

### atom_073 Account for allocated object lifecycle and linkage

- おすすめ: `中`
- judgeability: `llm_checkable`
- 元 normative: `norm_223`
- 参照数: 未集計
- 規約: When using this pattern, APIs account for the lifecycle and linkage of allocated objects.
- 解説: allocated object の cleanup / linkage を考える規約です．
