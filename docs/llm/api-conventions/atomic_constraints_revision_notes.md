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
Do not
Don't
Avoid
required
recommended
preferred
deprecated
```

`may`, `MAY`, `optional`, `can` だけを根拠にした文は `main_sentence` にしません．これらは「満たすべき制約」ではなく，許可，任意性，可能性の説明になりやすいためです．一方で，同じ文に `must`, `should`, `Do not`, `Avoid` などの制約 signal がある場合は候補に残します．

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

ただし，この境界だけでは文脈不足になるケースがあります．そのため，次の 2 つは例外的に context candidate に追加します．

1. 後続の箇条書きを導入する文
2. 直前文を指す語を含む文

この追加は，完全な参照解決を目指すものではありません．目的は reviewer が見る `original` の根拠不足を減らすことです．

そのため，候補を増やす規則は次の方針で切ります．

- Markdown の構造から判断できるものは広く扱う
- 代名詞や接続語の意味解釈が必要なものは，明らかに必要な候補を出すだけにする
- 候補を増やしすぎて LLM に不要な文を選ばせるより，レビュー時に不足を見つけて規則を足す方を優先する

### 後続の箇条書きを導入する文

重要キーワードを含む文が `:` で終わり，その直後に箇条書きが続く場合，その箇条書きは同じ説明単位の一部として扱います．

例：

```text
s1: API fields must follow these rules:
s2: - Use lowerCamelCase.
s3: - Avoid abbreviations.
```

この場合，`s1` だけでは「どの rules か」が分かりません．そのため，`s2` と `s3` を `s1` の `context_sentences` に出します．これは自動採用ではなく，LLM が必要な文だけを選ぶ候補です．

逆向きの形も扱います．つまり，`: ` で終わる paragraph の直後に箇条書きが続く場合，その paragraph の最後の文を，後続 bullet の `shared_context_sentences` に出します．

例：

```text
Required fields have the following properties:

- They mark themselves as required explicitly with a `+required` comment tag.
- They are never omitted from serialized objects.
```

この場合，後続 bullet の `They` は paragraph の導入文に依存しています．導入文は同じ bullet group の複数 task に効くため，`shared_context_sentences` として扱います．そのため，複数 task が同じ導入文を選んでも conflict にはしません．

この規則は，`Required fields` という文言に依存しません．条件は「同じ section 内で，paragraph が `:` で終わり，その直後に bullet group が続くこと」です．API conventions 以外の Markdown でも同じ構造なら同じ扱いになります．

### 直前文を指す語を含む文

文が `This`, `It`, `Instead` などで始まる場合や，文中に `this`, `it`, `such` などの指示語がある場合，その文だけでは対象が分からないことがあります．この場合，直前の重要キーワード文も `context_sentences` に出します．

例：

```text
s1: Conditions should be included as a top level element in status.
s2: It should not be embedded under spec.
```

`s2` の `It` は `Conditions` を指すため，`s1` を候補に出します．ただし，これも自動採用ではありません．LLM が `original` の理解に必要だと判断した場合だけ選びます．

現在の対象語は次の通りです．

```text
文頭：
It, They, This, That, These, Those, Such,
Instead, Otherwise, Therefore, However, Thus, Hence, Consequently, Accordingly,
As such, In that case, For this reason

文中：
it, its, itself, they, them, their, this, that, these, those, such
```

この規則は完璧な参照解決ではありません．目的は，明らかに文脈不足になりやすい文に対して，LLM が選べる候補を機械的に増やすことです．

ただし，`this`, `it`, `these` などは何を指すかが文によって大きく変わります．そのため，これらを見つけたからといって，前方の複数文を広く候補に入れることはしません．通常は直前の重要キーワード文だけを候補にします．

例外として，`the two` や `both` のように「2 つの対象」を明示している文だけは，直前の重要キーワード文を最大 2 つまで候補にします．

例：

```text
s1: Go field names must be PascalCase.
s2: JSON field names must be camelCase.
s3: Other than capitalization of the initial letter, the two should almost always match.
```

`s3` の `the two` は，直前 2 文の比較を指している可能性が高いです．このため，`s1` と `s2` を `s3` の候補に出します．

この規則は，field name 専用ではありません．条件は「main sentence に `the two` または `both` があり，その前に重要キーワード文があること」です．一方で，`these`, `those`, `they` だけで直前 2 文を候補にすることはしません．それらは 1 文を指す場合も，節全体や段落全体を指す場合もあり，誤って広い文脈を混ぜやすいためです．

`the former`, `the latter`, `respectively` のような表現は，今のところ追加していません．実例が出たら追加できますが，現時点では対象を広げすぎるより，明らかに必要な `the two` / `both` に留めます．

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
- `may` 系を含むが，主たる signal は `Do not`, `Avoid`, `must`, `should` などである

`no ... may be defined` や `use "may"` のような特殊表現を細かく拾うための独自規則は，現時点では入れません．得られる候補が少ない一方で，抽出ロジックが複雑になりすぎるためです．必要になったら，人間レビューで落ちた実例を見てから追加します．

内部では，候補から落ちた理由を `permissive_only`, `example_sentence`, `http_status_code_child` などとして audit に残します．review sheet に分類列を増やすためではなく，「なぜ候補から外れたか」を後で確認するためです．

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
6. `:` で箇条書きを導入する文には，後続の箇条書きを候補として足す
7. 指示語や接続語で文脈不足になりやすい文には，直前の重要キーワード文を候補として足す
8. LLM に context sentence ID だけを選ばせる
9. 選択結果を機械的に検査する
10. conflict があれば該当 task だけ再判定する
11. 選ばれた原文を元の順序で結合して `original` を作る
12. `original` から atomic constraint text を作る
13. 人間が review sheet で確認する

この設計では，LLM は文脈選択と constraint text の整理に使います．一方で，`original` の本文そのものは必ず source document から機械的に作ります．

## 生成物の置き場所

現状の CLI は，機械抽出結果を `docs/mechanical/api-conventions/` に，LLM 補助の選択結果を `docs/llm/api-conventions/` に出します．ただし，これらは設計文書ではなく，再生成可能な研究成果物です．

長期的には，生成物は `artifacts/constraint-extraction/` や `generated/constraint-extraction/` のような `docs/` 外のディレクトリに移す方が分かりやすいです．一方で，今すぐ既定出力先を変えると，既存のコマンド，README，過去成果物，テストの参照をまとめて変更する必要があります．そのため，この見直しでは出力先は変えず，`docs/` 内で設計メモと生成物を明確に区別します．

古い 73 constraint pass の説明資料は `docs/archive/api-conventions/` に退避します．設計判断の現行参照先はこのファイルです．

## 実行手順

通常はサブコマンドを指定せずに実行します．この場合，次の順で標準工程が動きます．

1. `sentence-selection-tasks`
2. `sentence-context-selection`
3. `review-sheet`

```bash
uv run python src/constraint_extraction/main.py
```

既存の結果を残したい場合は，先に生成物を `.old` などへ移動します．抽出ロジックを変えた場合も，同じファイル名で上書きされるため，前回結果を比較したいなら先に退避します．

```bash
mv docs/mechanical/api-conventions/sentence_selection_tasks.json \
  docs/mechanical/api-conventions/sentence_selection_tasks.json.old
mv docs/mechanical/api-conventions/sentence_selection_audit.json \
  docs/mechanical/api-conventions/sentence_selection_audit.json.old
mv docs/llm/api-conventions/sentence_context_selection.json \
  docs/llm/api-conventions/sentence_context_selection.json.old
```

必要な工程だけを個別に動かす場合は，サブコマンドを指定します．まず，Markdown から `main_sentence` と候補文を機械的に作ります．

```bash
uv run python src/constraint_extraction/main.py sentence-selection-tasks
```

次に，LLM に context sentence ID だけを選ばせます．この段階では LLM に原文を書かせません．出力先の `sentence_context_selection.json` には，選ばれた ID と，その ID から機械的に復元した `original` と，重複選択の conflict が保存されます．

`sentence_context_selection.json` は，正常で再利用可能な結果が既にある場合は skip します．抽出ロジックや task の中身を変えた後に完全にやり直したい場合は，古いファイルを `.old` に移動してから実行します．

Codex を batch 実行で使う例：

```bash
uv run python src/constraint_extraction/main.py sentence-context-selection \
  --batch-size 25
```

`codex` コマンド名，model，timeout を変える場合：

```bash
uv run python src/constraint_extraction/main.py sentence-context-selection \
  --codex-command codex \
  --model gpt-5.2 \
  --timeout-seconds 1800 \
  --max-retries 3 \
  --batch-size 25
```

Codex が存在しない sentence ID を選んだ場合や，同じ通常 context sentence を複数の `main_sentence` に選んだ場合は，該当 task だけを自動で再実行します．`--max-retries` 回連続で直らない場合は停止し，どの task がどの理由で失敗したかを表示します．

最終出力で conflict が 0 でない場合は，同じ通常 context sentence が複数の `main_sentence` に選ばれています．`shared_context_sentences` は共有してよい文なので，重複しても conflict にはしません．
