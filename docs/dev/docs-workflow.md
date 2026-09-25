# ドキュメントの書き方

この文書は、文書の置き場所、書き方、言語、検査を決めます。文書を追加・変更するときと、agent向けの入口を
変えるときに読みます。どの変更で文書を更新するかは[ドキュメント更新基準](documentation-update-criteria.md)を
参照してください。

## 置き場所

`docs/`には、現在有効な仕様、規約、手順だけを置きます。

| 内容 | 置き場所 |
|---|---|
| 目的を達成する手順 | `docs/howto/` |
| backend、frontend、containerなどの正確な契約 | `docs/reference/` |
| 開発と運用の規約 | `docs/dev/` |
| architectureと技術選択の説明 | `docs/`直下 |
| リポジトリの説明と目次 | rootの`README.md` |

- 変更の経緯、作業の段階ごとの記録、日付付きの測定値、TODO、調査の過程は文書に書きません。経緯と結果は
  Issue・PRに、過去の内容はgitの履歴に残します。`docs/archive/`は作りません
- Issueごとの実装設計は[`designs/`](../../designs/README.md)に置きます。現在の仕様の正本としては扱いません
- 空のdirectoryや、将来のための空の文書は作りません。新しい文書は、読み手、正本として持つ内容、既存の
  文書と分ける理由がある場合だけ追加します

## 段階的開示

読み手が必要な分だけを順に読めるよう、文書を層に分けます。

| 層 | 文書 | 持つもの | 持たないもの |
|---|---|---|---|
| 0 | rootの`README.md` | リポジトリの説明（数行）と目次 | コマンド、手順、make target、構成表、要件表 |
| 1 | `docs/README.md` | 読み手の目的ごとの索引。各リンクに1行の説明を付ける | 規約の本文 |
| 2 | 各文書 | 冒頭の2〜3行で何を決める文書か・いつ読むかを書き、その後に規約か手順を置く。細部は下の層へリンクする | ほかの文書の内容の再掲 |
| 3 | コードと設定 | 値の正本（`Makefile`、`pyproject.toml`、`package.json`、`.env.example`など） | — |

## 正本を1つにする

- 同じ規約を複数の文書に書きません。ほかの文書の規約が要る場合はリンクします
- 閾値、件数、model名、version、make targetの中身のようなコードの値は文書に写さず、正本のfileを示します
- コマンド、path、label、設定のkey、動作についての記述は、リポジトリの実装と照らし合わせてから書きます
- skill、コード、テストから参照されている文書のpathと見出しは、変えるときに参照元も合わせて直します。
  リンクの検査が見出しのanchorまで確かめます

## 言語

- `docs/**`、`README.md`、`CONTRIBUTING.md`は日本語で書きます
- agent向けの`.claude/skills/**`、`AGENTS.md`、`CLAUDE.md`は英語で書きます。ただしworkflow skillの
  機械が読む節（`## いつ使うか`、`## 入力`とその小見出し）は日本語の表記に固定します

## agent向けの入口

- リポジトリが保守するagentの入口は、rootの`AGENTS.md`と`CLAUDE.md`、`apps/web/AGENTS.md`と
  `apps/web/CLAUDE.md`の4つです
- 入口には、読むタイミング、作業に応じた参照先、参照先に従う案内だけを書きます。規約の条件、例外、判定の
  基準、コマンドの詳細は`docs/**`と`.claude/skills/**`の正本に置き、入口に要約を書きません
- 生成・外部管理されるブロック（`apps/web/AGENTS.md`の`BEGIN:nextjs-agent-rules`から
  `END:nextjs-agent-rules`まで）と`apps/web/CLAUDE.md`のimportは、生成元の契約に従って残します

## 検査

文書かskillを変えたら、次を実行します。

```sh
make verify-docs
```

`make verify-docs`は、リンクとanchorの検査、kaji skillの契約の検査、kaji workflowのYAMLの検査
（`kaji validate`）、markdownlintを実行します。違反は、`make verify-docs`を実行するkajiのstepで
blockingになります。GitHubのstatus checkは品質の証跡に使いません。

- 対象は`docs/**/*.md`、`designs/**/*.md`、`evals-evidence/**/*.md`、`.claude/skills/**/*.md`、rootの
  `README.md`、`CONTRIBUTING.md`、`AGENTS.md`、`CLAUDE.md`、`apps/web/AGENTS.md`、`apps/web/CLAUDE.md`です。
  一覧の正本は`scripts/docs/check-links.js`とrootの`package.json`の`docs:lint`です
- リンクの検査は、Markdownのlinkとimageについて、文書からの相対pathの実在、リポジトリの外へ出ないこと、
  リポジトリのrootからの絶対pathを使わないこと、percent encoding、文書をまたぐanchorを確かめます。
  anchorはGitHubと同じ規則で見出しから作るidと、HTMLの`id`と`name`に照らします
- 外部URLに届くか、Claude Codeのimport記法は検査しません
- 同じ文書の中のfragmentと、reference definitionの定義と使用は、markdownlintのMD051、MD052、MD053が
  検査します
- markdownlintのMD041はrootの文書を入口として使う構成と合わないため、MD060は表の区切りの幅と配置に意味が
  無いため、無効にしています。設定は`.markdownlint.json`です

## docs Issueとdev Issue

`type:docs`のIssueは文書だけを変えるworkflowを選びます。文書の変更にコードか設定の変更が要る場合は、
docsではなくdevのIssueにします。
