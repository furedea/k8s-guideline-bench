# Beyond-Syntax レビューのための kube-api-linter 参照

このメモは，API convention constraint の人間レビューで参照するために，Kubernetes repository で有効化されている kube-api-linter rule を整理したものです．

これは補助資料であり，自動判定手順ではありません．

## 対象範囲

Kubernetes repository では，`hack/golangci.yaml` 経由で kube-api-linter が有効化されています．plugin の詳細設定は次のファイルから取り込まれています．

```text
hack/kube-api-linter/kube-api-linter.yaml
```

現在の Kubernetes 設定では，まず kube-api-linter の全 rule を無効化し，その後に 15 個の rule だけを明示的に有効化しています．そのため，この参照資料では `kube_api_linter_rules.csv` にある 15 個の有効 rule を主な対象にします．

## レビュー時の使い方

- draft constraint が有効な kube-api-linter rule に直接対応する場合，`Beyond-Syntax` は `false` 寄りです．
- keyword が重なっているだけで `Beyond-Syntax=false` と判定しないでください．
- constraint が API design の意味判断を必要とする場合，関連語が linter rule に出ていても人間判断として扱ってください．
- 一般的な Go linter や formatter は補助的な baseline です．draft constraint が format や generic Go style を明示的に扱っている場合だけ考慮してください．

## 有効 rule

有効 rule の一覧は次の CSV にあります．

```text
docs/llm/api-conventions/kube_api_linter_rules.csv
```

この CSV はスプレッドシート上で検索しやすいように作っています．特に `Keywords` 列を使うと，draft constraint に出てくる `optional`，`condition`，`int32`，`json tag`，`listType`，`timestamp`，`map` などの語から対応しそうな rule を探せます．

## 設定上見えるが無効な rule

Kubernetes の設定ファイルには，コメントアウトされた kube-api-linter rule もいくつかあります．

```text
maxlength
nobools
nofloats
nophase
requiredfields
uniquemarkers
```

これらは現在の Kubernetes 設定では enforcement 対象ではありません．規約が将来的・原理的には tool-detectable である可能性を示す補助情報にはなりますが，`Beyond-Syntax=false` の直接根拠としては使わないでください．

## 例外設定

Kubernetes には次の例外設定もあります．

```text
hack/kube-api-linter/exceptions.yaml
```

例外設定は，有効 rule が弱い，あるいは無効である，という意味ではありません．これは，互換性リスクなしには修正できない既存 API の問題を見逃すための allowlist です．レビュー時には，例外設定は「その種類の問題が tool-detectable である」ことの補助的な証拠になります．ただし，古い API では互換性のために修正できない場合がある，という点に注意してください．
