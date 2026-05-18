# API Conventions Normative Review Notes

この archive note は，旧 223 normative constraint pass の人手 review 判断を記録したものです．当時の `keyword_normative_rules.json` と `normative_constraints.json` は再生成可能な中間生成物だったため，現在の repository には保持していません．

このファイルには，Python コードには入れない review 判断だけを記録します．

## 書き換えた規約

- `kw_norm_052`
    - Raw: `It should be included as a top level element in status, similar to`
    - Reviewed: `Conditions should be included as a top level element in \`status\`.`
    - 理由：直前の文と直後の code example に依存していて，そのままだと規約文として不完全だからです．

- `kw_norm_112`
    - Raw: `This is expected to change in the future, and new fields should explicitly set either an \`+optional\` or \`+required\` comment tag.`
    - Reviewed: `New fields should explicitly set either an \`+optional\` or \`+required\` comment tag.`
    - 理由：前半は説明であり，規約本体ではないからです．

## 除外した規約

- `kw_norm_016`
- `kw_norm_017`
- `kw_norm_030`
- `kw_norm_053`
- `kw_norm_065`
- `kw_norm_075`
- `kw_norm_111`
- `kw_norm_113`
- `kw_norm_116`
- `kw_norm_118`
- `kw_norm_120`
- `kw_norm_122`
- `kw_norm_123`
- `kw_norm_125`
- `kw_norm_130`
- `kw_norm_131`
- `kw_norm_144`
- `kw_norm_145`
- `kw_norm_147`
- `kw_norm_149`
- `kw_norm_152`
- `kw_norm_153`
- `kw_norm_161`
- `kw_norm_167`
- `kw_norm_170`
- `kw_norm_171`
- `kw_norm_173`
- `kw_norm_180`
- `kw_norm_181`
- `kw_norm_182`
- `kw_norm_183`
- `kw_norm_190`
- `kw_norm_191`
- `kw_norm_192`
- `kw_norm_193`
- `kw_norm_194`
- `kw_norm_195`
- `kw_norm_213`
- `kw_norm_228`
- `kw_norm_257`
- `kw_norm_258`
- `kw_norm_259`
- `kw_norm_260`
- `kw_norm_261`

## 除外基準

- 規約の説明に使われているだけで，再利用可能な normative statement ではない例示文
- keyword は含むが，project guideline そのものではなく説明や文脈補足に留まる文
- actionable な規約というより，example や schema 説明に近い status code detail
- 議論や反例のために source に残されている historical / unsafe example
