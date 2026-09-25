# git規約

この文書は、branch、commit、PRの作り方と、コードのコメントに書くことを決めます。commitとPRを作るときに
読みます。Issueからmergeまでの流れは[開発ワークフロー](development-workflow.md)を参照してください。

## branch

- kajiで作業するときは、kajiが渡す`branch_name`をそのまま使います。形は`<prefix>/<Issue番号>`で、prefixは
  Issueの`type:*` labelから決まります（例: `type:bug`なら`fix/42`）。対応は[Issueラベル](issue-labels.md)に
  あります
- 手作業で作るときも同じ形にします。Issueが無い小さな変更は`chore/<短い説明>`のように、prefixと内容が
  分かる名前にします
- defaultのbranchへ直接commitしません

## commitの粒度

- 1つのcommitには1つの目的の変更を入れます。整形だけの変更、ファイルの移動、動作の変更は分けます
- 各commitの時点で、`make check-all`が通る状態を保ちます
- 生成物（lockfileの更新、formatterの結果）は、それを生んだ変更と同じcommitに入れます

## commit message

- 1行目は英語の命令形で、変更の内容を書きます（例: `Check cross-document anchors in the Markdown link check`）。
  `feat:`のようなprefixは付けません
- 1行目は72文字以内を目安にし、末尾にピリオドを付けません
- 理由や影響の説明が要る場合は、空行を挟んで本文に書きます

## commitの前に確かめること

- `git status`でstageした内容を確かめ、意図しないfile（`secrets/`、`.env`、生成されたartifact）が入って
  いないことを確認します
- pre-commitのhook（gitleaks、ruff、markdownlint、Prettier）を通します。hookを飛ばしてcommitしません

## PR

- 1つのPRは1つのIssueに対応させます。関係の無い変更を混ぜません
- 本文には、Issueへのリンク、変更の要約、実行した確認（laneと結果）を書きます。kajiを使う場合、本文の形は
  `pull-request-create` skillが決めます
- レビューの指摘への対応は、新しいcommitとして積みます

## 履歴の書き換え

- pushしていないcommitは、`git commit --amend`やrebaseで整理してかまいません
- pushしたbranchの履歴は、PRの作成者だけが、レビューの前に限って書き換えます。defaultのbranchの履歴は
  書き換えません

## コメントの方針

- コードのコメントには、コードから読み取れない理由と制約だけを書きます
- 変更の経緯、Issue・PRの番号、作業の段階、設計文書の節番号は書きません。それらはIssue、PR、commit
  messageに残します。コードが残る限りコメントも読まれるため、経緯を書くと、関係の無くなった情報が
  残り続けます
