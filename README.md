# k8s-guideline-bench

既存 OSS プロジェクト（Kubernetes API）を対象に，プロジェクト固有の開発ガイドライン（Kubernetes API conventions）の AI Coding Agent による遵守性能を定量評価するためのベンチマーク基盤．

## 研究目的

**AI を開発者として見たとき，どのような開発プロセスやタスク，コンテキストを与えると性能が上がるのかを定量評価する．**

具体的には，Kubernetes API conventions を複数の与え方で提示した上で，リファクタリングコミット適用前のコードを各種 AI Coding Agent にリファクタリングさせ，どの程度ガイドラインを遵守しているかを LLM-as-a-Judge により評価する．

## 出典

このリポジトリは，Kubernetes project の API conventions 文書を `docs/source/api-conventions.md` に含め，ベンチマーク構築のための研究入力として atomic constraints の抽出に利用している．元文書のライセンスと履歴は upstream の Kubernetes リポジトリを参照する．

## 研究進捗

1. [x] 対象 OSS（開発ガイドライン）を決定
2. [x] 開発ガイドラインの規約群から Atomic Constraints（AI 生成コードの制約適否を判定しやすい規約）を策定
3. [x] リファクタリング PR を取得しデータセット化（`src/dataset_construction/`）
4. [x] AI Coding Agent に PR 本文，リファクタリング前のベースファイル群，規約一覧ファイルを与えてリファクタリングを実行（`src/agent_execution/`）
5. [x] 生成された Patch を LLM-as-a-Judge で atomic constraint ごとに評価（`src/llm_judgment/`）
6. [ ] LLM-as-a-Judge の妥当性担保のため工程 5 を人間にも実施させ比較
7. [ ] モデル変更 or コンテキスト（ファイル群，規約）の与え方を変更して 4-5 を実施
8. [ ] 結果をまとめる

## パイプライン

4 段階構成．各段階は `src/<stage>/` 直下にモジュール + CLI エントリポイントを置き，TDD で実装する．

| # | 段階 | ディレクトリ | CLI | 主な入出力 |
| --- | --- | --- | --- | --- |
| 1 | 制約抽出 | `src/constraint_extraction/` | `uv run python src/constraint_extraction/main.py {source-selection,review-sheet}` | ガイドライン原文 → Atomic Constraints（JSON） |
| 2 | データセット構築 | `src/dataset_construction/` | `uv run python src/dataset_construction/build_dataset.py --spec config/dataset_spec.json` | Kubernetes リポジトリ + GitHub PR metadata → `datasets/<pr_number>/` |
| 3 | Agent 実行 | `src/agent_execution/` | (Stage 4 から呼び出し) | `base/` + 規約 → `predicted_patch.diff` |
| 4 | LLM-as-a-Judge | `src/llm_judgment/` | `uv run python src/llm_judgment/run_experiment.py --spec config/experiment_spec_pilot.json` | `predicted_patch.diff` + 規約 → `judgments.json` + 集計 |

`CompletionClient` Protocol に沿って Anthropic / OpenAI 互換クライアントを実装．テスト時は Protocol に適合する fake client を注入．

### 成果物のディレクトリ構造

```
datasets/
└── <pr_number>/
    ├── base/<changed_files>       # PR マージ直前の main の状態
    ├── gold/<changed_files>       # PR マージ後 (merge_commit) の状態
    ├── gold_patch.diff            # git diff base_sha head_sha
    └── task.json                  # pr_number, base_sha, head_sha, title, body, labels, changed_files

results/
├── experiment_report.json         # 全 run の集計レポート
└── <run_id>/<pr_number>/
    ├── prompt.txt                 # Agent への入力
    ├── raw_response.txt           # Agent の生出力
    ├── predicted_patch.diff       # 抽出されたパッチ
    ├── run_metadata.json          # Agent 実行メタデータ
    ├── judge_targets.json         # Judge 対象 constraint
    └── judgments.json             # 制約毎の Judge 結果
```

## データセット構築

### 方針

**SWE-bench 方式 = "merged PR を 1 インスタンス"** を採用．リファクタリングコミットを grep で拾う方式は採用しない．

**理由**:

- 評価対象は「ガイドラインに沿ったリファクタか」であって，個別コミットの質ではない．PR が 1 つの意味単位（reviewer 合意の単位）．
- 中間コミット（typo 修正，レビュー指摘反映）をノイズとして自動排除できる．
- Kubernetes の `kind/cleanup` ラベル運用が `prow` bot により強制されるため，**マージ済み PR ラベル = 信頼度の高い intent 信号**．コミットメッセージの `grep` より false positive が桁違いに低い．
- SWE-bench / BugsInPy / Long Code Arena など主要なベンチマークがこの粒度を採用している．

### 収集の粒度

1 PR = 1 `DatasetInstance`．PR 内部の複数コミット（typo 修正，レビュー指摘反映など）は全部まとめて 1 つの差分として扱う．

各 PR について，**start 地点（base_sha）** と **goal 地点（head_sha）** の 2 つを押さえ，その間の差分と PR 自身のメタデータ一式をデータセット化する．

**2 つの SHA**

- `head_sha` = PR マージ後の状態．`gh api /pulls/{n}` の `merge_commit_sha`．Kubernetes は rebase merge 運用なので main ブランチ上にそのまま存在する
- `base_sha` = PR マージ直前の main．`head_sha` の親コミット

**保存する 4 種類**

| 名前 | 中身 | 使い道 |
| --- | --- | --- |
| `base/` | `base_sha` 時点の変更ファイル実体（ツリー形式） | AI Coding Agent へ「リファクタ前の状態」として渡す |
| `gold/` | `head_sha` 時点の変更ファイル実体 | 人間参照用．LLM-as-a-Judge には渡さない（正解リーク防止） |
| `gold_patch.diff` | `git diff base_sha head_sha -- <changed_files>` | 正解パッチ．人間評価の参照用 |
| `task.json` | `pr_number` / `base_sha` / `head_sha` / `title` / `body` / `labels` / `merged_at` / `changed_files` / `added_lines` / `deleted_lines` | Agent prompt 組立と後段集計のメタデータ |

**`changed_files`**：`gh api /repos/.../pulls/{n}/files` が返す PR 全体の変更ファイル集合．そこから [フィルタ層](#フィルタ層この順で適用) の #2（パス）と #3（glob 除外）を通した後の集合が最終的に `base/` `gold/` `gold_patch.diff` の対象になる．

### フィルタ層（この順で適用）

1. **ラベル選別**：`gh search prs label:kind/cleanup repo:kubernetes/kubernetes is:merged` で第 1 段の recall を確保．`required_pr_labels`（ANY-OF）と `excluded_pr_labels`（例：`kind/api-change`, `kind/feature`, `kind/bug`）で精度を上げる．
2. **パス絞り込み**：`target_paths`（`api/`, `pkg/apis/`, `staging/src/k8s.io/{api,apimachinery,apiserver}/`）に 1 ファイルでも該当する PR のみ採用．該当外ファイルは `changed_files` から落とす．
3. **除外パターン**：`exclusion_patterns`（glob）で `zz_generated_*.go` などの機械生成物を落とす．
4. **空 patch 除外**：`git diff base_sha head_sha -- <changed_files>` が空になる PR は除外する．GitHub の PR files に履歴上の差分が残っていても，main に実際に取り込まれた差分が空なら Agent evaluation の正解として使えないためである．
5. **サイズフィルタ**：`min_changed_files`，`min_changed_lines` のみを適用する．1 行 typo / 空変更などの自明な PR を下限で弾く．上限（`max_changed_files` / `max_changed_lines`）は，恣意的な閾値で大規模 cleanup を除外する論理的根拠がないため設定しない（`null`）．大規模 PR 由来の偏りはサイズ別の事後分析で扱う方針．
6. **挙動保存検証**（任意）：`verification_level="build"` で PR マージ後のコード（`head_sha`）に対して変更ファイルのパッケージだけ `go build` する．データセットに壊れたコード（import 欠落・型不整合など）を入れると AI の出力が悪いのかそもそもビルドが通らないのか区別できなくなるので弾く．**テストまでやらないのは**，Kubernetes 全テストは実行に数時間〜かかり pilot では重すぎるため．ビルド通過だけでも破壊的変更の大半は検知できるので費用対効果でこの粒度にしている．失敗 PR は `rejected_root/` へ退避．
7. **件数上限**：`pr_limit`（採用 PR 件数の上限）．`null` ならフィルタ後の候補を切り詰めない．

### 全期間 dataset の注意点

`since=null` は GitHub repository の `createdAt` を取得し，その日から `pr_search_window_days` ごとに `gh search prs --merged-at <start>..<end>` を実行する．GitHub Search は 1 回あたり 1000 件上限なので，広い期間では日付窓で欠落を避ける．`gh search prs` は GitHub Search API の rate limit に当たりやすいため，呼び出し間隔を空けて実行する．`config/dataset_spec.json` では呼び出し数を抑えるため 30 日窓を使う．

全期間 dataset では model cutoff は使わない．これは汚染回避を目的にした評価ではなく，Kubernetes の履歴全体にある guideline-relevant cleanup PR を広く集めるための構成である．

ただし，次のバイアスは残る．`kind/cleanup` は Kubernetes のラベル運用に依存するため，古い時期の PR を取り逃がす可能性がある．`target_paths` は現在の API 関連ディレクトリを基準にしているため，過去の構造変更前の API 関連 PR を落とす可能性がある．`verification_level="build"` は現在の toolchain で過去 commit をビルドするため，当時は妥当だった PR でも依存関係や toolchain 差で落ちる可能性がある．さらに，現代の `source/api-conventions.md` を基準に judge する場合，古い PR 時点の API conventions と現代の conventions が異なっていた可能性があるため，年代別の分析軸を残して解釈する．

### 全期間 dataset の実行結果

| 段階 | 件数 | 直前段階からの drop | 主な意味 |
| --- | --: | --: | --- |
| 詳細取得後 | 14043 | - | `kind/cleanup` で取得できた merged PR |
| ラベル再確認後 | 12731 | 1312 | 除外ラベルを持つ PR を除外 |
| パス選別後 | 1742 | 10989 | Kubernetes API 関連のパスへの変更のみ |
| サイズフィルタ後 | 1224 | 518 | 1 行 typo 等の小さすぎる PR を除外 |
| 再現環境での動作 | 1224 | 0 | `verification_level=none` のため追加 drop なし |

#### 「14043」が初期段階件数として妥当な理由

PR 番号は 13 万番台まで進んでいるが，これは **PR 数ではなく連番**にすぎない．実際の総数と内訳は以下のとおりで，**約 9 割は対象外ラベルかマージ未到達で消える**ため，残り約 1.4 万件が `kind/cleanup × merged` の実母数になる．

| 指標 | 件数 | 補足 |
| --- | --: | --- |
| PR 番号の最新値 | ~138,500 | 単なる連番．issue と共有番号空間で歯抜けあり |
| リポジトリの実 PR 総数 | 89,057 | 全 state 含む（GraphQL `pullRequests.totalCount`） |
| そのうち merged | 36,267 | open / closed / draft を除外 |
| **`kind/cleanup` × merged**（本 dataset の母集団） | **約 14,000** | `kind/feature` / `kind/bug` / `kind/api-change` 等を除外した残り |

GitHub Search の `issueCount` は古い PR で大幅に過小報告する（例：2019 年は `issueCount=6` と返るが，本 dataset の crawl では同年 2839 件取れる）．そのため本実装では `issueCount` には依存せず，30 日窓で `gh search prs --merged-at <start>..<end>` を全期間スライスして取りこぼしを防いでいる．

#### パス選別が最大の絞り込みである理由

最も大きい drop はパス選別である．これは Kubernetes 全体の `kind/cleanup` PR の多くが API conventions 評価対象の `api/`，`pkg/apis/`，`staging/src/k8s.io/api/`，`staging/src/k8s.io/apimachinery/`，`staging/src/k8s.io/apiserver/` に触れていないためである．この段階は dataset の主題を Kubernetes API conventions に寄せるための中心的な recall/precision 調整であり，単なる件数削減ではない．

#### サイズフィルタの扱い

`max_changed_files` / `max_changed_lines` の上限は，恣意的な閾値で大規模 cleanup を除外する論理的根拠がないため設定しない（`null`）．`min_changed_lines=5` のみ「1 行 typo の自明 PR を除く」根拠で残す．大規模 PR 由来の偏りはサイズ別の事後分析で扱う．

#### 再現環境での動作確認

`verification_level="build"` を有効にすると，PR の `head_sha` に対し変更ファイルのパッケージだけ `go build` を試す（テストまでは時間がかかるため当面なし）．`config/dataset_spec.json` では現行 `none`．有効化すると当時の依存関係や toolchain 差で落ちるため drop が発生する．

実行後確認では，`datasets/` 直下の instance 数，`task.json` 数，`gold_patch.diff` 数，`base/` 数，`gold/` 数は一致する．ただし一部の instance では `gold_patch.diff` が空になる（例：PR #96657）．これは local git の不具合ではなく，「PR は確かに開かれて merge されたが，main に取り込まれた時点ではもう中身が変わっていなかった」ケースである．

具体的に PR #96657 で何が起きたかを順を追うと：

1. PR #96657 は `storage_factory_test.go` への変更を提案し，GitHub の "Files changed" ビューにはその差分が記録される．
2. しかし PR がレビュー中の間に，他の PR 経由で main 上の同じファイルが先に同じ状態へ書き換わってしまった（例：別 cleanup PR が同じ修正を含んでいた／途中で revert があった等）．
3. その状態で PR #96657 が merge されると，main 上に作られる merge commit と，merge 直前の main（merge commit の first parent）とを比べたときに，対象ファイルの差分は **0 byte** になる．main 視点では「すでにそうなっていた」ためである．

GitHub の PR ページが見せる「Files changed」は **PR branch を base branch と比較した歴史上の差分**で，本リポジトリが採用する `git diff base_sha merge_commit_sha -- <file>` は **main に実際に取り込まれた変更**を見ている．両者は通常一致するが，上記のような race を起こした PR では一致しない．

Agent evaluation では「main に取り込まれた gold patch」を正解として使うため，gold patch が空の instance は学習・採点ともに使えない．したがって dataset 構築時にこの instance は除外する．

### Intent source（Agent への入力に同梱する情報）

- **必須**：PR title + PR body（`gh api /repos/.../pulls/{n}`）
- **補助**：PR labels（分類情報）
- **不採用**：リンクされた issue 本文（Kubernetes では小〜中規模 cleanup が issue を立てない文化のため recall 低下が大きい．将来必要なら追加）

`task.json` に `title`, `body`, `labels` を含めることで，Stage 3 の Agent prompt で `ContextStrategy` に応じて活用できる．

### DatasetSpec (`config/dataset_spec.json`) 主要フィールド

| フィールド | 説明 |
| --- | --- |
| `github_repo` | `"kubernetes/kubernetes"` |
| `repo_path` | ローカルの Kubernetes clone のパス（`git diff` 用） |
| `target_paths` | 対象ディレクトリのプレフィックス |
| `exclusion_patterns` | glob で除外するファイル |
| `since` | マージ日時の下限．`null` なら GitHub repository の作成日から検索する |
| `model_cutoffs` | 互換用フィールド．全期間 dataset では下限として使わない |
| `pr_search_window_days` | GitHub Search の 1000 件上限を避けるための日付窓幅 |
| `required_pr_labels` / `excluded_pr_labels` | ラベル絞り込み |
| `pr_cache_dir` | PR metadata の JSON キャッシュ |
| `min_changed_files` / `min_changed_lines` | サイズフィルタ下限（1 行 typo 等を除外）．`max_*` は論理的根拠がないため `null` 推奨 |
| `verification_level` | `"none"` or `"build"` |
| `rejected_root` | 検証失敗 PR の退避先（未指定ならその場で削除） |
| `pr_limit` | 採用 PR 数の上限 |
| `datasets_root` | `datasets/` の出力先 |

## Agent 実行（Stage 3）

Stage 2 で作った `datasets/<pr_number>/base/` と atomic constraints を AI Coding Agent に渡し，リファクタ後の patch を生成させる．複数モデル × 複数コンテキスト戦略の直交比較を 1 run = `(run_id, model, context_strategy)` として実行．

実行方式は Docker agentic 固定．runner は `base_sha` の Kubernetes source tree から Agent 用の `/work` を作り，Agent は container 内でリポジトリと必要な context file を自分で参照する．作業後の `git diff --no-color HEAD -- <changed_files>` を runner が `predicted_patch.diff` として回収する．

### 入出力

| 項目 | 内容 |
| --- | --- |
| 入力 | `datasets/<pr_number>/{base/, task.json}` + `constraints/api_conventions_atomic_constraints_73.json` |
| 出力 | `results/<run_id>/<pr_number>/{prompt.txt, raw_response.txt, predicted_patch.diff}` |
| 呼び出し元 | Stage 4 (`run_experiment.py`) から．本段階に独立 CLI は無い |

### Prompt 組立（`agent_runner.build_agentic_workspace_prompt`）

1. **Task 見出し**：`task.json` の `title`
2. **PR body**：`pr_body.clean_pr_body()` で Kubernetes PR テンプレートの boilerplate（`<!-- ... -->` HTML コメント，`/kind cleanup` 等 prow slash command，`release-note NONE` ブロック，空見出し，過剰空行）を除去してから挿入．**データセット段階では生 body を保持し，ここで初めてクリーニングする**ことで，将来 strategy ごとに異なる前処理（要約 / raw など）に差し替え可能
3. **Workspace**：repository root（既定 `/work`）と `/bench/task.json` の場所を示す
4. **Project guidelines**：`ContextStrategy` に応じて，制約ファイルの参照または inline 制約を与える
5. **Initial file context**：必要な場合だけ，`initial_context_files` で指定したファイル本文を初期 prompt に入れる

基本はファイル本文やルール本文を prompt に埋め込まず，Agent に repository と `/bench/task.json` を参照させる．比較実験では `context_strategy` と `context_files` により，制約なし，原文 Markdown，73 個の atomic constraints JSON を切り替える．`bench_context/` は container に read-only mount する．

### ContextStrategy（制約の与え方）

研究目的の「コンテキストをどう与えると性能が上がるか」の直交軸．

| strategy | 制約の与え方 | 用途 |
| --- | --- | --- |
| `inline_constraints` | constraint を prompt 本文に埋め込み．`initial_constraint_ids` 指定時は該当 constraint のみ | 初期ルール提示の比較 |
| `attached_file_constraints` | `constraints.json` を `/bench/constraints.json` として mount し，prompt にはパスだけ書く | 外部ファイル参照の比較 |
| `api_conventions_md` | `docs/source/api-conventions.md` を `/bench/api-conventions.md` として mount | 原文ドキュメント探索の比較 |
| `atomic_constraints_73_json` | `constraints/api_conventions_atomic_constraints_73.json` を `/bench/api_conventions_atomic_constraints.json` として mount | Judge と同じ 73 個の atomic constraints の比較 |
| `normative_constraints_223_json` | `constraints/api_conventions_normative_constraints_223.json` を `/bench/api_conventions_normative_constraints.json` として mount | 223 個の reviewed normative constraints の ablation 用 |
| `no_constraints` | 制約を渡さない | 下限値．モデルの事前学習知識だけで判定 |

pilot / full の主比較では `no_constraints`，`api_conventions_md`，`atomic_constraints_73_json` を使う．`inline_constraints`，`attached_file_constraints`，`normative_constraints_223_json` は ablation 用に残している．

### Judge Client（抽象化）

`CompletionClient` Protocol (`completion_client.py`)：

```python
def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str: ...
```

実装は 2 種：

- `AnthropicCompletionClient`：Anthropic SDK 直
- `OpenAICompatibleCompletionClient`：OpenAI 互換エンドポイント（`opencode.ai/zen` 経由で Kimi / MiniMax / Qwen 等）

`ClientSpec` (JSON) から `completion_client_factory.build_completion_client()` が Judge client の実体を組み立て．API key は環境変数名 (`api_key_env`) で渡す．Agent 実行にはこの completion client を使わない．

`judge_config.judge_mode` は既定 `reference_based`．この mode では predicted patch と gold patch の両方を Judge に渡し，人間の refactoring を参照しながら atomic constraint ごとの可否を判定する．`patch_only` にすると gold patch を渡さず，predicted patch 単体の API convention compliance を見る．最終分析では constraint compliance と task success を分けるため，`patch_only` も利用できるようにしている．

Judge は `verdict` とは別に `patch_effect` を返す．`compliant` は最終コードが制約に従っていることを示すだけで，patch がその制約を新たに満たしたとは限らない．そのため主な成功数は `patch_effect=applied_by_patch` かつ `verdict=compliant` の `newly_satisfied` として集計する．`already_satisfied` は「元から満たされていた制約」なので成功カウントには入れない．

### Agent matrix（`config/experiment_spec_pilot.json` / `config/experiment_spec_full.json`）

通常は `agent_matrix` で model × context の直積を短く書く．loader が `agent_configs[]` に展開し，`run_id` は `<prefix>_<model>_<context>` になる．`agent_configs[]` を直接書く明示形式も互換用に残しているが，pilot / full では使わない．

| フィールド | 説明 |
| --- | --- |
| `run_id_prefix` | `pilot` / `full` など成果物ディレクトリ名の prefix |
| `models` | モデル ID の配列（例：`opencode-go/qwen3.6-plus`）．`docker.openai_compatible_provider` を併用する場合は provider prefix を書かず，素の model id（例：`Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8`）を書ける |
| `context_strategies` | 比較する context strategy の配列 |
| `max_tokens` | agent command に環境変数 `MAX_TOKENS` として渡す上限 |
| `docker` | Docker agentic 実行設定（`image` / `backend` / `agent_command` / `docker_args`） |
| `worktree_strategy` | 既定 `cow_snapshot`．必要なら `git_worktree` に切替可能 |
| `skip_existing` | 既存 `predicted_patch.diff` があれば Agent 実行を skip |
| `keep_worktree` / `keep_failed_worktree` | 成功/失敗時に `/work` の host 側 copy を残すか |

`agent_command` は container 内で実行される shell command で，`$AGENT_PROMPT_PATH`，`$TASK_PATH`，`$CONSTRAINTS_PATH`，`$MODEL`，`$MAX_TOKENS` を参照できる．

`docker.backend` は既定 `custom_cli`．この mode では runner は `$MODEL` などの共通 env と mount だけを用意し，`agent_command` の中身には介入しない．`opencode` を指定すると OpenCode backend として扱い，local OpenAI-compatible endpoint を agent に使うための `openai_compatible_provider` を指定できる．

`docker.backend="opencode"` かつ `docker.openai_compatible_provider` を指定すると，runner は OpenCode 用の `OPENCODE_CONFIG_CONTENT` を自動生成して container に渡す．`client.base_url` が `localhost` / `127.0.0.1` の場合は，container から host の local server へ到達できるよう `host.docker.internal` へ自動書き換えし，`--add-host=host.docker.internal:host-gateway` も自動付与する．API key 用 env は `client.api_key_env` から自動 passthrough されるため，local agent 用に `env_passthrough` を手で増やす必要はない．

`api_conventions_md`，`atomic_constraints_73_json`，`normative_constraints_223_json` の `context_files` は loader が既定値を補う．個別 run ごとに特殊な mount や token 数を変えたい場合だけ，明示的な `agent_configs[]` を使う．

### WorktreeStrategy

既定は `cow_snapshot`．PR ごとに `results/<scope>/base_snapshots/<pr_number>/` へ `git archive base_sha` で `.git` を含まない clean snapshot を作り，各 run はそこから copy-on-write copy を作る．run worktree は `git init` + `git add .` + `git commit -m base` で独立 repo にするため，Agent は `git status` / `git diff` / `git add` / `git reset` を通常どおり使える．一方で本物の Kubernetes history は渡さないので，正解 PR を `git log` / `git show` で探す leakage 経路を閉じられる．

`git_worktree` は `git worktree add --detach <base_sha>` で本物の Kubernetes history を持つ worktree を作る strategy．履歴探索まで含めたい少数 ablation 用に残すが，full run では checkout I/O と history leakage の両面から `cow_snapshot` を使う．

### 実行と resume

`run_experiment.py` は既存 dataset を読み込み，`agent_configs[]` ごとに Agent を実行してから Judge に渡す．大規模実験の前に少数 instance で smoke test できるよう，CLI は `--instance-id` と `--limit` を持つ．

```bash
uv run python src/llm_judgment/run_experiment.py \
  --spec config/experiment_spec_pilot.json \
  --instance-id 100108 \
  --limit 1
```

Docker 実行では `results/<run_id>/<pr_number>/worktree/` を container の `/work` に mount する．Agent は `/work` を直接編集し，runner が実行後の diff を `predicted_patch.diff` として保存する．`AgentRunConfig.skip_existing=true` の場合，既存の `results/<run_id>/<pr_number>/predicted_patch.diff` があれば Docker 実行を skip し，resume 用の既存結果として扱う．成功した instance の worktree は既定で削除し，失敗した instance は原因調査用に既定で残す．Agent command が失敗した instance は `raw_response.txt` に exit code と stdout/stderr を残し，Judge には渡さず run 全体は続行する．

Judge の resume は `judge_config.skip_existing=true` で別に制御する．有効時は `results/<run_id>/<pr_number>/judgments.json` と `judgments.partial.json` から `status=ok` の constraint judgment を再利用し，未完了または失敗した rule だけを再判定する．`agent_matrix.skip_existing` は Agent 実行だけに効くため，実験を中断再開する設定では両方を明示する．

`judge_target_policy="gold_scope"` の場合，Strategy 側 Judge は human gold patch から作った固定 scope（gold が新たに満たした規約 + gold 時点で既に守られていた規約）だけを評価する．この結果は既存の full judge 結果を壊さないよう，`results/<run_id>__gold_scope/<pr_number>/judgments.json` に保存する．既に `results/<run_id>/<pr_number>/judgments.json` に full judge 結果がある場合は，scope 内の `status=ok` judgment を scoped run にコピーして再利用し，不足分だけを新たに judge する．

`judge_target_policy="all_constraints"` は従来通り全 constraint を評価する．この mode では `extra_new` を観測できるが，実行時間は長い．`gold_scope` mode では scope 外を評価しないため `extra_new` は探索指標としては使わず，通常比較では `new_rules`，`lost_existing`，`eval_error` を見る．

### Patch 回収

Agent の標準出力は diff と見なさない．Agent が container 内の worktree を編集した後，runner が `git diff --no-color HEAD -- <changed_files>` を実行して `predicted_patch.diff` を作る．標準出力と標準エラーは `raw_response.txt` に保存する．Stage 4 の judge はこの diff と atomic constraint を照合する．

### 既存研究との位置付け

| 観点 | SWE-bench | RefactoringMiner | このベンチ |
| --- | --- | --- | --- |
| 収集単位 | PR 全体 | コミット + AST 差分 | **PR 全体** |
| intent source | issue 本文 | なし（AST から自動） | PR 本文 + labels |
| 粒度選択の理由 | issue = 仕様の自然言語記述 | refactoring type の厳密ラベル | ガイドライン準拠の評価単位 |
| リポ選別 | squash merge 運用のリポ優先 | 任意 | Kubernetes 固定 + 厳密ラベル運用を利用 |

## 対象

- **OSS**：Kubernetes API（固有の API 規約がまとまっており，設計的規約があるためタスク難易度も適切）
- **対象規約**：`source/api-conventions.md`（`kubernetes/community/contributors/devel/sig-architecture/source/api-conventions.md`）
    - 他の規約はソースが散らばり外部リンク参照もあるため一旦 API 規約のみに絞る
- **対象ディレクトリ**：
    - `api/`
    - `pkg/apis/`
    - `staging/src/k8s.io/api/`
    - `staging/src/k8s.io/apimachinery/`
    - `staging/src/k8s.io/apiserver/`

## Atomic Constraints

**Atomic Constraint**：AI 生成コードの制約への適否を判定しやすく整えられた規約．

### 基準（with 近藤先生，CIFE，CodeIF 等の先行研究）

- **Atomic**：1 つの制約が 1 つの要求のみを表す
    - 判定：制約を意味のある 2 つの sub-constraint に分割できるか？
    - 例 Y：`Raise ValueError for invalid input`
    - 例 N：`Return a float and raise ValueError for invalid input`
- **Beyond-Syntax**：静的解析ツールが検出・修正できない
    - 判定：既存の静的解析ツール（go vet, staticcheck, golint）で自動検出・修正できるか？
    - 例 Y：`Public integer fields MUST use Go int32 or int64, not int`（AST で判定可能 → 没）
    - 例 N：`Spec fields should have declarative rather than imperative names`（意味解釈が必要）
- **Diff-Code-Related**：AI Coding Agent が生成した変更差分のみから制約適否を判断できる
    - 判定：diff 外のコード・未変更ファイル・実行時挙動・外部コンテキストを見ずに判断できるか？
    - 例 Y：`bool fields use pointer types`
    - 例 N：`Users can disable auto-generation`（PR 外の controller 実装を見ないと不能）
- **Objective**：制約適否の判定が人によって変わらない
    - 判定：何を満たせば遵守で何を満たさなければ違反かを客観的に説明できるか？
    - 例 Y：`bool fields use pointer types`
    - 例 B（Borderline）：`Fields in spec use declarative names`
    - 例 N：`conditions should convey properties users care about`
- **Grounded**：引用元の規約の前提条件・対象スコープ・制約内容を忠実に反映している
    - 判定：原文と制約文を比較して原文の意図が変化していないか？
    - 例 Y：原文の制約内容を漏れなく反映したもの
    - 例 N：原文の前提条件（例：`physical resource`）が落ちたもの

### 後で考える基準

- **Distinct**（制約セットレベル）：制約セット内で同じ違反を測定する制約がない
    - 判定：制約 A を違反すると必然的に制約 B も違反/遵守となる制約がないか？
    - 例 N（包含）：`starts with uppercase letter` と `Use PascalCase`
    - 例 N（相互排他）：`starts with uppercase letter` と `use snake_case`
- **Judgeability**：machine / hybrid / llm
- **Category**：naming / structure / validation / ...

### 元規約からの絞り込み手順

1. 重要度キーワード（MUST, SHOULD 等）を含む規約文を機械抽出
2. 抽出文の不完全な部分を補完・example や不要な説明文の削除を LLM で実行
3. 意味を成す規約文が Atomic Constraint 基準を満たすかを人力チェック（← 現在停止中）
    - 一人判定は偏りリスクがあるため，無作為シャッフルした候補を二人以上で 20-50 件判定
    - Kappa agreement ≥ 0.7-0.8 なら一人判定に信頼を置く

参考：[近藤先生の記事](https://posl.esa.io/posts/867)

## AI Coding Agent 候補

ローカル実行ではなく，opencode-go 経由の API / サブスク型エンドポイントを使う．pilot では Qwen3.6 Plus，MiniMax M2.7，Kimi K2.5 を中心に，`no_constraints`，`api_conventions_md`，`atomic_constraints_73_json` の 3 context を比較する．full run では pilot 結果を見てモデル数と context を絞る．

## ディレクトリ構成

```
.
├── config/                              # Stage ごとの run spec (JSON)
│   ├── source_selection.json
│   ├── dataset_spec.json
│   ├── experiment_spec_pilot.json
│   └── experiment_spec_full.json
├── docs/                                # Provenance 別の規約原文・中間成果物
│   ├── source/api-conventions.md
│   ├── mechanical/api-conventions/keyword_normative_rules.json
│   ├── llm/api-conventions/normative_constraints.json
│   ├── llm/api-conventions/normative_interpretations.json
│   ├── llm/api-conventions/normative_review_notes.md
│   ├── llm/api-conventions/atomic_constraints.json
│   ├── llm/api-conventions/atomic_constraints_report.md
│   ├── llm/api-conventions/atomic_selection_guide.md
│   ├── human/api-conventions/shigyos_atomic_constraints.csv
│   └── logs/audit/<YYYY-MM-DD>.jsonl    # constraint extraction の audit log
├── constraints/                          # 実験実行用 catalog
│   ├── api_conventions_atomic_constraints_73.json
│   └── api_conventions_normative_constraints_223.json
├── src/
│   ├── diff_hunk_classification.py      # API conventions 関連 hunk のヒューリスティック分類
│   ├── common/                          # 共有ユーティリティ
│   │   ├── base.py                      # Pydantic FrozenModel 基底
│   │   ├── error.py
│   │   ├── git_repository.py            # `repo_path` 不在時の自動 clone
│   │   └── project_paths.py
│   ├── constraint_extraction/           # Stage 1: 制約抽出
│   │   ├── main.py                      # source-selection / review-sheet サブコマンド CLI
│   │   ├── source_selection.py
│   │   ├── source_selection_config.py
│   │   ├── normative_constraint.py
│   │   ├── normative_audit.py
│   │   └── atomic_constraint.py
│   ├── dataset_construction/            # Stage 2: データセット構築
│   │   ├── build_dataset.py             # CLI エントリポイント
│   │   ├── dataset_spec.py
│   │   ├── dataset_builder.py
│   │   ├── dataset_store.py             # 永続化 / 再読込
│   │   ├── pr_collection.py             # gh api 経由の PR メタデータ取得
│   │   └── verification.py              # go build 挙動保存チェック
│   ├── agent_execution/                 # Stage 3: Agent 実行
│   │   ├── agent_runner.py
│   │   ├── pr_body.py
│   │   ├── client_spec.py
│   │   ├── completion_client.py         # Protocol
│   │   ├── completion_client_factory.py
│   │   ├── anthropic_client.py
│   │   └── openai_compatible_client.py
│   └── llm_judgment/                    # Stage 4: LLM-as-a-Judge
│       ├── run_experiment.py            # CLI エントリポイント
│       ├── experiment.py
│       └── judge.py
├── docker/Dockerfile                     # opencode-go agent 実行 image
├── tests/                               # pytest (src/<stage>/ に pythonpath 通し済み)
├── flake.nix / .envrc                   # 開発環境（Nix + direnv）
├── pyproject.toml / uv.lock             # Python 依存管理（uv）
└── README.md                            # 本ファイル
```

## Setup

### 前提

| ツール | 用途 |
| --- | --- |
| [direnv](https://direnv.net) | `.env` の current shell への自動注入 |
| [uv](https://github.com/astral-sh/uv) | Python 依存管理 |
| Docker（OrbStack 等） | agent 実行 container |
| `gh` CLI | dataset 構築で GitHub PR metadata を取得 |
| `git` | Kubernetes repository の clone と snapshot 作成 |

### 手順

```sh
# 1. 開発環境
direnv allow
uv sync

# 2. agent 実行用 image を build
docker build -t k8s-bench-agent -f docker/Dockerfile .

# 3. API key を投入
# .env を作り，OPENCODE_API_KEY=... を書く
```

`config/*_spec.json` の `repo_path`（既定 `kubernetes/`）が存在しない場合，dataset 構築と experiment 実行の入口で `https://github.com/kubernetes/kubernetes.git` を自動 clone する．既に clone 済みなら再 clone しない．clone 先に Git repository ではない同名ディレクトリがある場合は，誤上書きを避けるため停止する．

### `.env` の自動ロード

`.envrc` に以下を追記すると direnv 組み込みの `dotenv` ディレクティブが `.env` を current shell に注入する：

```sh
watch_file .env
dotenv
```

`direnv allow` を再実行すれば，以後 cd した瞬間に `OPENCODE_API_KEY` が shell に乗る．これは agent container（`DockerAgentConfig.env_passthrough`）と judge client（`judge_config.client.api_key_env`）の双方が同じ env を読む構成と整合する．

`.env` は `.gitignore` 済みで commit されない．暗号化して commit したい場面が来たら `dotenvx encrypt` を後付けで導入できる．

### Smoke run

最小構成（1 agent × 1 instance）で pipeline を疎通確認：

```sh
uv run python src/llm_judgment/run_experiment.py \
  --spec config/experiment_spec_pilot.json --limit 1
```

成果物は `results/pilot/<run_id>/<pr_number>/` 以下．`experiment_report.json` の `newly_satisfied` / `effective_total` が出力されれば Agent 実行から Judge 集計まで疎通している．

### Pilot run (9 agent × N instance)

```sh
uv run python src/llm_judgment/run_experiment.py \
  --spec config/experiment_spec_pilot.json
```

`--instance-id <pr>` または `--limit N` でサブセット指定可．

### Local server run on sam

sam へデータを移行した後は，データ再構築ではなく実行環境の確認から始める．local 100 PR 実験の spec は `config/experiment_spec_local_100.json` を使う．この spec は `judge_target_policy="gold_scope"` なので，Strategy 側 Judge は gold scope に入った規約だけを評価する．

#### 1. Python / Docker の確認

```sh
uv sync
docker build -t k8s-bench-agent -f docker/Dockerfile .
docker run --rm k8s-bench-agent true
```

#### 2. Local LLM server を起動

vLLM と SGLang を比較する場合，ポートを分けて起動する．どちらも OpenAI-compatible endpoint として `client_type="openai_compatible"` から呼び出す．

vLLM:

```sh
export LOCAL_LLM_API_KEY=local-token

vllm serve Qwen/Qwen2.5-Coder-14B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --api-key "$LOCAL_LLM_API_KEY" \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.90 \
  --enable-prefix-caching \
  --generation-config vllm
```

SGLang:

```sh
export LOCAL_LLM_API_KEY=local-token

python -m sglang.launch_server \
  --model-path Qwen/Qwen2.5-Coder-14B-Instruct \
  --host 0.0.0.0 \
  --port 8001 \
  --api-key "$LOCAL_LLM_API_KEY" \
  --context-length 16384
```

`config/experiment_spec_local_100.json` の `judge_config.client.base_url` と `judge_config.model` は，起動した server と model に合わせて変更する．sam 上で experiment も実行する場合，base URL は `http://localhost:8000/v1` のようにする．手元の machine から sam の server を叩く場合は `http://sam:8000/v1` を使う．

#### 3. 疎通確認

```sh
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $LOCAL_LLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct",
    "messages": [{"role": "user", "content": "Return JSON: {\"ok\": true}"}],
    "max_tokens": 32
  }'
```

#### 4. Smoke run

まず 1 PR で Agent 実行，Judge，fair report まで通す．

```sh
uv run python src/llm_judgment/run_experiment.py \
  --spec config/experiment_spec_local_100.json \
  --limit 1

uv run python src/llm_judgment/compute_fair_report.py \
  --spec config/experiment_spec_local_100.json
```

#### 5. Small comparison

vLLM と SGLang を比較する場合は，同じ model，同じ 10 PR で wall time，`eval_error`，JSON parse failure，GPU utilization を見る．

```sh
uv run python src/llm_judgment/run_experiment.py \
  --spec config/experiment_spec_local_100.json \
  --limit 10
```

#### 6. 100 PR run

Smoke と small comparison が通ったら 100 PR を回す．`skip_existing=true` なので中断後も再実行で resume する．

```sh
uv run python src/llm_judgment/run_experiment.py \
  --spec config/experiment_spec_local_100.json

uv run python src/llm_judgment/compute_fair_report.py \
  --spec config/experiment_spec_local_100.json
```

### Pilot fair report

通常の集計では，AI が作った差分ごとに「どの規約が今回の変更に関係するか」を判定する．この方法だと，同じ model でも context strategy が変わるだけで評価対象の規約数が変わり，strategy 間比較が歪む可能性がある．

pilot ではこの問題を避けるため，まず人間が merge した正解差分を Sonnet Judge で評価し，PR ごとに「この PR で本来見るべき規約」を固定する．その固定された規約集合に対して，各 AI の結果を後から採点し直す．既に作成済みの AI 実行結果と Judge 結果は再利用し，人間の正解差分から作った評価対象だけを追加で保存する．

```sh
uv run python src/llm_judgment/run_gold_scope.py \
  --spec config/experiment_spec_pilot.json

uv run python src/llm_judgment/compute_fair_report.py \
  --spec config/experiment_spec_pilot.json
```

`compute_fair_report.py` は `results/pilot/fair_report.json` を更新し，次の列を表示する．

| 列 | 意味 | 良い方向 |
| --- | --- | --- |
| `PR` | dataset instance の PR 番号 | - |
| `new_rules` | 人間の正解差分が新たに満たした規約のうち，AI の差分も新たに満たせた数．`達成数/対象数` 形式 | 大きいほど良い |
| `lost_existing` | 人間の正解差分では既に守られていた規約のうち，AI の差分後に明示的に `violated` と判定された数．`not_applicable` は含めない | 小さいほど良い |
| `extra_new` | 人間の正解差分では新規達成扱いでないが，AI の差分では新たに満たしたと判定された規約数 | 解釈注意 |
| `eval_error` | Judge が有効に判定できなかった数．`not_judged`，API failure，parse failure，timeout など．AI の規約違反としては数えない | 小さいほど良い |

2026-05-11 時点の pilot（10 PR，3 models × 3 context strategies，73 atomic constraints for test）の結果は以下．

| model | context strategy | new_rules | lost_existing | extra_new | eval_error |
| --- | --- | --: | --: | --: | --: |
| Qwen3.6 Plus | no_constraints | 3/5 | 0 | 1 | 0 |
| Qwen3.6 Plus | api_conventions_md | 2/5 | 0 | 1 | 0 |
| Qwen3.6 Plus | atomic_constraints_73_json | 4/5 | 0 | 0 | 0 |
| MiniMax M2.7 | no_constraints | 3/5 | 0 | 1 | 0 |
| MiniMax M2.7 | api_conventions_md | 3/5 | 0 | 1 | 0 |
| MiniMax M2.7 | atomic_constraints_73_json | 5/5 | 0 | 1 | 0 |
| Kimi K2.5 | no_constraints | 3/5 | 0 | 1 | 0 |
| Kimi K2.5 | api_conventions_md | 4/5 | 0 | 3 | 0 |
| Kimi K2.5 | atomic_constraints_73_json | 3/5 | 0 | 0 | 3 |

- 人間の正解差分が新たに満たした規約は合計 5 個だけ
- MiniMax では atomic constraints を渡した条件が 5/5 で最も良い
- Qwen も atomic constraints を渡した条件が 4/5 で最も良い
- Kimi は API conventions の原文 Markdown を渡した条件が 4/5 で最も良い
- `lost_existing=0` なので，今回の pilot では「正解差分では既に守られていた規約を AI が明示的に破った」例は観測されていない
- Kimi の atomic constraints 条件では `eval_error=3` が残っているため，その 3 件は規約違反としてではなく評価失敗として別扱いにする
- `extra_new` は追加で良い修正をした可能性もあるが，gold scope の取りこぼしや Judge の揺れもあり得るため，個別 PR の差分確認が必要

## 開発

公開 README には開発ルールを細かく重複して書かず，検証コマンドだけを置く．コーディング規約や TSDD の運用はエージェント設定とテストに寄せる．

```sh
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest
```

## Original（原文）の切り出し方

レビューシートの `original` 列は `source/api-conventions.md` から自動抽出される．抽出単位は **block**（Markdown 上の意味のあるひとかたまり）で，具体的には以下の 2 種類のみ切り出す．

1. **段落**：空行で区切られた連続する普通の文のかたまり（途中改行があっても空行がなければ同じ段落）
2. **bullet**：`- ...` / `* ...` / `1. ...` で始まる 1 項目（マーカーなしの継続行は吸収）

以下は切り出し **対象外**．

- `## ...` などの見出し（section 名として内部記録のみ）
- ` ``` ` で囲まれたコードブロック（中身全スキップ）
- 最初の見出しより前の前書き

### 具体例

````markdown
# API Conventions

前書き（これは block にならない）．

## Types (Kinds)

The name of a list kind must end with "List". Lists have a limited set of common metadata. All lists use the required "items" field.

Objects should have a spec and a status.

- Use pointers for bool fields.
- Use omitempty for optional fields that may be empty.
- Avoid int, use int32 or int64.

```go
type Pod struct { ... }
```

Another paragraph here with a MUST clause.
````

切り出される block：

| # | kind | 行範囲 | text |
| --- | --- | --- | --- |
| 1 | paragraph | `7-9` | `The name of a list kind must end with "List". Lists have a limited set of common metadata. All lists use the required "items" field.` |
| 2 | paragraph | `11-11` | `Objects should have a spec and a status.` |
| 3 | bullet | `13-13` | `Use pointers for bool fields.` |
| 4 | bullet | `14-15` | `Use omitempty for optional fields that may be empty.` |
| 5 | bullet | `16-16` | `Avoid int, use int32 or int64.` |
| 6 | paragraph | `21-21` | `Another paragraph here with a MUST clause.` |

ポイント：

- **block 1** は空行がないので 1 段落．文単位に分割後，MUST/SHOULD 等キーワードを含む文だけが constraint になる．結果として複数の norm が同じ `source_span` を共有．
- **block 4** は継続行として bullet に吸収．
- **block 3, 4, 5** は隣接していても別 block（bullet は 1 項目 = 1 block）．
- コードブロックは丸ごとスキップされ，**block 6** は後段落として拾われる．

### Original と Constraint(s) の対応

- **段落内の複数 MUST 文** → `text`（Constraint）は文ごとに分かれるが，`source_span` と `original` は全て同じ．
- **bullet** → `text` も `source_span` も bullet 丸ごと 1 つ．bullet 内に MUST が複数あっても 1 constraint にまとめる．

実装は `src/constraint_extraction/normative_audit.py` の `_collect_blocks` と `src/constraint_extraction/main.py` の `_extract_original` を参照．

## 開発ルール

- 実装は Kent Beck TDD + Agile-like SDD（`~/.claude/rules/coding_guideline.md`, `~/.claude/rules/asdd_workflow.md`）に準拠
- ディレクトリ名はハイフン区切り，ファイル名はアンダースコア区切り
- コードコメントは英語，コミットメッセージは Conventional Commits（英語）
- VCS は jj（Jujutsu）優先
- push は明示的指示がない限り実行しない
