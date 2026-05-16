# API Conventions Atomic Constraints Revision Notes

このメモは，API conventions から atomic constraints を作り直すための確認用メモです．

今回の見直しで一番大きく変わった点は，`original` を「広めに取った paragraph / bullet」ではなく，「constraint の根拠として reviewer が見る最小限の原文」に近づけることです．ただし，抽出時に広い文脈が不要になるわけではないため，広い原文と reviewer に見せる原文を分けて扱います．

## 目的

これまでの `original` は，paragraph や bullet の単位で広く取られることがありました．その結果，1 つの paragraph に複数の重要キーワード文があると，複数の constraint が同じ `original` を共有し，どの文からどの constraint が出たのかが分かりにくくなっていました．

今回の目的は次の 3 つです．

1. constraint の根拠文を reviewer が追いやすくする
2. LLM には必要な周辺文を渡しつつ，LLM に原文を書き換えさせない
3. 同じ補足文が複数 constraint に曖昧に割り当てられるケースを機械的に検出する

## 原文の持ち方

原文は 2 段階で持ちます．

### `block_original`

`block_original` は，これまでに近い広めの原文です．paragraph や bullet のまとまりを保持します．

これは主に監査用です．LLM や reviewer が「この文は元々どの文脈にあったのか」を確認できるように残します．ただし，最終的な constraint の根拠としてそのまま使うとは限りません．

### `original`

`original` は，最終的に review sheet で reviewer が見る根拠文です．これは LLM が自由に生成する文ではなく，元の文をそのまま選んで機械的に結合します．

基本形は次の通りです．

```text
original = main sentence + selected context sentences
```

`main sentence` は必ず入ります．`context sentences` は，LLM が必要だと選んだものだけを入れます．文の編集，言い換え，短縮はしません．

## 文の分類

1 つの block を sentence に分割し，それぞれに `s1`, `s2`, `s3` のような ID を付けます．

その上で，文を次の 3 種類に分けます．

### `main_sentence`

`main_sentence` は，constraint の中心になる文です．

典型的には，次のような重要キーワードを含む文です．

```text
MUST
MUST NOT
SHOULD
SHOULD NOT
must
must not
should
should not
required
recommended
preferred
deprecated
```

1 つの `main_sentence` から，原則として 1 つ以上の atomic constraint を作ります．

### `shared_context_sentences`

`shared_context_sentences` は，block の冒頭にあり，最初の `main_sentence` より前にある説明文です．

block 冒頭の説明は，後ろの複数の `main_sentence` に共通して効くことがあります．そのため，同じ `shared_context_sentence` が複数 task で選ばれても conflict にはしません．

例：

```text
s1: Optionality affects API compatibility.
s2: Fields must be either optional or required.
s3: This avoids ambiguous client behavior.
s4: New fields should explicitly set either `+optional` or `+required`.
```

この場合，`s1` は block 全体の前提説明なので，`s2` の task と `s4` の task の両方で使われても自然です．

### `context_sentences`

`context_sentences` は，`main_sentence` の周辺にある補足文です．

これは主語，対象，理由，例外条件などを補うために LLM に渡します．ただし，どの `main_sentence` に属するかが曖昧になりやすいため，最終的に同じ `context_sentence` が複数の `main_sentence` に選ばれた場合は conflict として扱います．

## context の範囲

`context_sentences` は，隣り合う `main_sentence` を境界として機械的に作ります．

例：

```text
s1: Optionality affects API compatibility.
s2: Fields must be either optional or required.
s3: This avoids ambiguous client behavior.
s4: Older APIs sometimes relied on implicit optionality.
s5: New fields should explicitly set either `+optional` or `+required`.
s6: This is expected to become stricter in the future.
s7: Generated clients rely on this metadata.
s8: Validation must reject unset required fields.
s9: This protects clients from incomplete objects.
```

この block には `main_sentence` が 3 つあります．

```text
s2
s5
s8
```

各 task に渡す文は次のようになります．

```text
task for s2:
  main_sentence:
    s2
  shared_context_sentences:
    s1
  context_sentences:
    s3
    s4

task for s5:
  main_sentence:
    s5
  shared_context_sentences:
    s1
  context_sentences:
    s3
    s4
    s6
    s7

task for s8:
  main_sentence:
    s8
  shared_context_sentences:
    s1
  context_sentences:
    s6
    s7
    s9
```

`s1` は冒頭説明なので全 task に共有します．一方，`s3`, `s4`, `s6`, `s7` は通常の補足文なので，複数 task で選ばれたら曖昧さとして検出します．

## LLM に渡すもの

LLM には，原文を書かせません．LLM には，必要な context sentence の ID だけを選ばせます．

入力例：

```json
{
    "task_id": "block_0001_s5",
    "block_original": "Optionality affects API compatibility. Fields must be either optional or required. This avoids ambiguous client behavior. Older APIs sometimes relied on implicit optionality. New fields should explicitly set either `+optional` or `+required`. This is expected to become stricter in the future. Generated clients rely on this metadata. Validation must reject unset required fields. This protects clients from incomplete objects.",
    "main_sentence": {
        "id": "s5",
        "text": "New fields should explicitly set either `+optional` or `+required`."
    },
    "shared_context_sentences": [
        {
            "id": "s1",
            "text": "Optionality affects API compatibility."
        }
    ],
    "context_sentences": [
        {
            "id": "s3",
            "text": "This avoids ambiguous client behavior."
        },
        {
            "id": "s4",
            "text": "Older APIs sometimes relied on implicit optionality."
        },
        {
            "id": "s6",
            "text": "This is expected to become stricter in the future."
        },
        {
            "id": "s7",
            "text": "Generated clients rely on this metadata."
        }
    ]
}
```

出力例：

```json
{
    "selected_context_sentence_ids": ["s1", "s7"]
}
```

この出力を受け取ったら，機械的に次の `original` を作ります．

```text
Optionality affects API compatibility. New fields should explicitly set either `+optional` or `+required`. Generated clients rely on this metadata.
```

LLM は `original` を直接書きません．選ばれた ID に対応する原文を，元の順序で結合するだけです．

## conflict 検出

LLM が context sentence を選んだ後，機械的な検査を行います．

検査することは次の 2 つです．

1. 存在しない sentence ID を選んでいないか
2. 同じ通常 context sentence を複数の `main_sentence` が選んでいないか

`shared_context_sentences` は複数 task で共有してよいので，重複しても conflict にしません．

一方，通常の `context_sentences` が重複して選ばれた場合は conflict として返します．

例：

```text
task for s2 selected: s3
task for s5 selected: s3
```

この場合，`s3` が `s2` と `s5` のどちらの根拠なのか曖昧です．そのため，この 2 task を再判定対象にします．

## 再判定

conflict が出た場合，block 全体をやり直すのではなく，conflict に関係した task だけを LLM に再判定させます．

再判定時には，少なくとも次を明示します．

```text
The following context sentence was selected for multiple main sentences.
Choose it only for the main sentence where it is necessary as source evidence.
If it is only general background, do not select it unless it is needed to make the original understandable.
```

これにより，曖昧な補足文が複数 constraint の `original` に混ざることを防ぎます．

## `may` / `MAY` の扱い

`may` 系は，通常の obligation としては扱いにくいです．

特に，次のような文は benchmark の primary constraint にはしません．

```text
may
may not
MAY
MAY NOT
optional
OPTIONAL
```

理由は，これらが「実装が必ず満たすべき規約」ではなく，許可，可能性，任意性を表すことが多いためです．

ただし，`may` 系をすべて無視するわけではありません．次のような場合は別扱いにします．

- 同じ main sentence に `MUST` や `should` などの強い signal がある
- `may not` という phrase 自体の使い方を規定している
- permission ではなく，禁止や wording rule として客観的に判定できる

この分類は，review sheet に余計な列を増やすためではなく，内部で候補を落とした理由を説明できるようにするために持ちます．

## `beyond_syntax` の扱い

`beyond_syntax` は，constraint の採用条件ではありません．採用するかどうかは，atomic で judgeable かどうかで決めます．

`beyond_syntax` は，その constraint が既存 lint で検出できる種類のものか，それとも semantic / design judgment を必要とするものかを説明するラベルです．

機械的に確認できるものは，Kubernetes 側の custom lint 設定から拾います．見る対象は少なくとも次です．

```text
kubernetes/hack/kube-api-linter/kube-api-linter.yaml
kubernetes/hack/kube-api-linter/exceptions.yaml
kubernetes/hack/golangci.yaml
sigs.k8s.io/kube-api-linter の enabled linter
```

ただし，`beyond_syntax` は完全に機械的には決めません．既存 lint と直接対応するものは機械的に下書きできますが，semantic / design judgment が必要なものは最終的に人間レビューで確認します．

例：

```text
beyond_syntax = false:
  public integer field が int32 / int64 を使っている
  list field に list semantics marker がある
  optional / required marker が明示されている

beyond_syntax = true:
  spec field が declarative な semantics を持っている
  condition type が user にとって意味のある state を表している
  controller が interrupted control loop 後も idempotent に振る舞う
```

## 最終的な流れ

最終的な抽出フローは次の形にします．

1. Markdown から block を機械的に集める
2. block を sentence に分割し，sentence ID を振る
3. 重要キーワードを含む文を `main_sentence` とする
4. block 冒頭の説明文を `shared_context_sentences` とする
5. 隣の `main_sentence` を境界に `context_sentences` を作る
6. LLM に context sentence ID だけを選ばせる
7. 選択結果を機械的に検査する
8. conflict があれば該当 task だけ再判定する
9. 選ばれた原文を元の順序で結合して `original` を作る
10. `original` から atomic constraint text を作る
11. 人間が review sheet で確認する

この設計では，LLM は文脈選択と constraint text の整理に使います．一方で，`original` の本文そのものは必ず source document から機械的に作ります．

## 実行手順

まず，Markdown から `main_sentence` と候補文を機械的に作ります．既存の結果を残したい場合は，先に `sentence_selection_tasks.json` と `sentence_selection_audit.json` を `.old` などへ移動します．

```bash
uv run python src/constraint_extraction/main.py sentence-selection-tasks
```

次に，LLM に context sentence ID だけを選ばせます．この段階では LLM に原文を書かせません．出力先の `sentence_context_selection.json` には，選ばれた ID と，その ID から機械的に復元した `original` と，重複選択の conflict が保存されます．

Claude CLI を使う例：

```bash
uv run python src/constraint_extraction/main.py sentence-context-selection \
  --model claude-sonnet-4-6
```

OpenAI-compatible endpoint を使う例：

```bash
uv run python src/constraint_extraction/main.py sentence-context-selection \
  --client-type openai_compatible \
  --api-key-env LOCAL_LLM_API_KEY \
  --base-url http://localhost:8001/v1 \
  --model mistralai/Devstral-Small-2507 \
  --max-tokens 8192
```

conflict が 0 でない場合は，同じ通常 context sentence が複数の `main_sentence` に選ばれています．その場合は，対象 task だけを再判定する必要があります．`shared_context_sentences` は共有してよい文なので，重複しても conflict にはしません．
