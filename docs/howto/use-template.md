# テンプレートの使い方

この文書は、テンプレートから自分のリポジトリを作り、名前を付け替え、サンプルを自分のエージェントへ
置き換える手順を示します。テンプレートを使い始めるときに読みます。

## リポジトリを作る

GitHubの「Use this template」で新しいリポジトリを作り、cloneします。その後、
[開発環境](development-environment.md)の手順で起動できることを確かめます。

## 名前を付け替える

テンプレートの名前`fullstack-aiagent-template`を、自分のプロジェクトの名前に置き換えます。

| 対象 | 置き換える場所 |
|---|---|
| Pythonのpackage名 | `pyproject.toml`の`[project] name`、`apps/api/core/config.py`の`DISTRIBUTION_NAME` |
| buildに渡すversionのenv名 | `Dockerfile`の`SETUPTOOLS_SCM_PRETEND_VERSION_FOR_<package名>` |
| npmのpackage名 | rootの`package.json`の`name` |
| Composeのproject名とimage名 | `docker-compose.yml`と`docker-compose.override.yml`の`name`と`image` |
| webのログのservice名 | `apps/web/src/lib/logger.ts`の`SERVICE_NAME` |
| kajiのworktreeの名前 | `.kaji/config.toml`の`worktree_prefix` |
| 見出しと著作権の表記 | `README.md`、`LICENSE` |

名前を変えたらlockfileを作り直します。

```sh
uv lock
npm install --package-lock-only --ignore-scripts
```

置き換え漏れが無いことを確かめます。lockfileを除いて何も出なければ完了です。

```sh
git grep -n -i -e "fullstack-aiagent-template" -e "fullstack_aiagent_template" -- ':!*.lock' ':!*package-lock.json'
```

DB名（`app_dev`、`app_test`）は変えなくても動きます。変える場合は`scripts/db/init-db.sql`、
`secrets/db.env`、各`secrets/*.env`の接続先をそろえて変えます。

## GitHubリポジトリとつなぐ

kajiを使う場合は、kajiが操作するGitHubリポジトリを設定します。テンプレートの`.kaji/config.toml`の
`repo`は`<owner>/<repo>`という仮の値で、設定するまでkajiのGitHub操作は失敗します。

1. `.kaji/config.toml`の`[provider.github]`で、`repo`を自分のリポジトリ（`owner/name`）に、`git_remote`を
   そのリポジトリを指すremote名に設定します
2. `gh auth status`で、そのリポジトリを操作できるaccountでloginしていることを確かめます
3. 適当なIssueを1件作り、`uv run kaji issue view <番号>`でそのIssueが表示されることを確かめます。別の
   リポジトリのIssueが表示された場合は、`repo`を見直します
4. Issueのlabelを作ります。まず変更の内容を確かめ、問題が無ければ`--apply`を付けて実行します

   ```sh
   uv run python -m scripts.github.sync_labels --repo <owner>/<repo>
   uv run python -m scripts.github.sync_labels --repo <owner>/<repo> --apply
   ```

   labelの定義は`.github/labels.yml`、意味は[Issueラベル](../dev/issue-labels.md)にあります

## サンプルを置き換える

サンプルは`apps/api/sample/`と`apps/web/src/sample/`にあります。共通部分は変えずに、次の順で置き換えます。
境界は[アーキテクチャ](../architecture.md#サンプルと共通部分の境界)を参照してください。

1. agentとtool: `apps/api/sample/agent.py`のinstructionとtool、`tools.py`、同梱文書の`corpus.py`を
   置き換えます。手順は[toolの追加](add-tool.md)を参照してください
2. fake model: `apps/api/sample/fake_model.py`の応答を、新しいtoolに合わせて書き換えます。E2Eはこの
   fake modelで動きます
3. 画面: `apps/web/src/sample/`の見出しと応答の描き方を書き換えます。E2E（`apps/web/tests/e2e/`）も
   新しい流れに合わせます
4. eval: `apps/api/sample/evals/`のdataset、scorer、rubricを置き換え、baselineを測り直します。手順は
   [evalの追加](add-eval.md)を参照してください

各段階で`make check-all`を、画面を変えたら`make test-e2e`も実行します。

## 使わない部分を外す

### kaji

kajiを使わない場合は、次を削除します。

- `.kaji/`、`.claude/skills/`、`.agents/skills/`、`designs/`、`scripts/kaji/`
- `scripts/docs/check_kaji_skills.py`、`scripts/docs/kaji_skill_rules.py`と、それを検査するテスト
  （`scripts/tests/test_kaji.py`）
- `pyproject.toml`の開発用依存の`kaji`
- `Makefile`の`verify-docs`のうち、kaji skillとworkflowを検査する手順
- `docs/dev/`のkajiの文書（workflow、skill、ラベル、完了基準）と、そこへのリンク

削除したら`make check-all`を実行し、`AGENTS.md`と`docs/README.md`から消えた文書へのリンクを外します。

### eval

evalを使わない場合は、次を削除します。

- `apps/api/sample/evals/`、`apps/api/agent/evals/`、`evals-evidence/`
- 関係するテスト（`apps/api/tests/`の`test_eval_*`と`test_sample_eval_*`）
- `Makefile`の`evals`で始まるtarget
- `pyproject.toml`のcoverageの`omit`にある`*/agent/evals/runner.py`
- `docs/howto/add-eval.md`と、`evals-evidence/`への参照（`docs/dev/docs-workflow.md`の検査対象、
  `scripts/docs/check-links.js`と`package.json`の`docs:lint`の対象、`.claude/skills/issue-close/SKILL.md`）
- `docs/dev/llm-evals.md`のevalの節と、そこへのリンク。`make test-llm`を残す場合は文書ごとは消しません

kajiを残す場合は、kaji skillがevalのlaneと`docs/dev/llm-evals.md`を参照しているので、合わせて見直します。
削除したら`make verify-docs`と`make check-all`を実行します。
