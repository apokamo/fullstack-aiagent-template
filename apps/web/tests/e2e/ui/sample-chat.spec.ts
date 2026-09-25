/**
 * サンプルの画面を fake model（`AGENT_MODEL_MODE=fake`）で通す E2E。
 *
 * ここが担うのは**実ブラウザでしか観測できないもの**だけである。承認の要否を
 * `mutates` から導く規則も、`resolveRequestProfile` の分岐も backend / Small test が
 * 既に固定しているので、意味なく重複移植しない。ここで確かめるのは次の 3 本である。
 *
 * 1. 検索: `/chat` が開き、tool 結果と結論が出る。
 * 2. 承認: 承認前に止まり、承認すると再開する。承認再開は元の run の profile を運び、
 *    次の user turn は選び直した profile を運ぶ。
 * 3. 却下: 却下しても再開し、同じ tool を撃ち直さない。
 *
 * 打つ文言と固定引数の正本は `apps/api/sample/fake_model.py` の定数（`TRIGGER_*` / `FAKE_NOTE_*` / `*_TEXT`）で、
 * 検索の答えは `apps/api/sample/corpus.py` の同梱コーパスから決まる。
 *
 * **`role="alert"` や件数を数えるときは `main` へ絞る。** dev server で動く E2E では
 * Next.js の dev overlay が `main` の外に要素を挿す。
 */

import { expect, test, type Page } from "@playwright/test";

/** fake が `search_docs` へ倒す発話（trigger を 1 つも含まない）。 */
const SEARCH_PROMPT = "サンプル文書でテストのtierを検索して説明してください。";
/** 同梱コーパスの先頭ヒット（`testing-tiers`）の見出しを引用した結論。 */
const SEARCH_ANSWER = "「テストの tier」に記載があります。";
/** fake が `save_note` へ倒す発話（`TRIGGER_NOTE` = 「メモ」を含む）。 */
const NOTE_PROMPT =
  "一時メモに、見出し『確認』、本文『テスト規約を確認する』を書き留めてください。";
/** `save_note` に載る固定引数（`FAKE_NOTE_TITLE` / `FAKE_NOTE_BODY`）。 */
const NOTE_TITLE = "確認";
const NOTE_BODY = "テスト規約を確認する";
/** 承認後の結論（`SAVED_TEXT`）。 */
const SAVED_TEXT = "一時メモに書き留めました。この内容は保持されません。";
/** 却下後の受け止め（`DENIED_TEXT`）。 */
const DENIED_TEXT =
  "書き留めませんでした。必要になったらもう一度お知らせください。";
/** 承認再開のあとに送る次の user turn と、その結論。 */
const NEXT_PROMPT = "環境変数の置き場を検索してください。";
const NEXT_ANSWER = "「環境変数の置き場」に記載があります。";

const DS4 = "ds4-deepseek-v4-flash-chat";
const LUNA = "openai-luna-chat";
const LUNA_LABEL = "GPT-6 Luna（Chat）";

/** 一覧が ready になるまで待ってから 1 通送る。 */
async function send(page: Page, text: string): Promise<void> {
  // **一覧が ready になるまで送信を止める**ので、選択欄が操作可能になってから
  // 打つ。待たないと click が握り潰される。
  await expect(page.getByTestId("model-select")).toBeEnabled();
  await page.getByPlaceholder("質問を入力").fill(text);
  await page.getByRole("button", { name: "Submit" }).click();
}

/** 選択欄を開いて option を選ぶ。 */
async function choose(page: Page, label: string): Promise<void> {
  await page.getByTestId("model-select").click();
  await page.getByRole("option", { name: label }).click();
}

/** assistant の 1 応答（サンプルのカード）。 */
function cards(page: Page) {
  return page.getByTestId("sample-response");
}

test("/chat が開き、検索の tool 結果と結論が出る", async ({ page }) => {
  const response = await page.goto("/chat");
  expect(response?.status()).toBe(200);
  await send(page, SEARCH_PROMPT);

  await expect(page.getByText(SEARCH_ANSWER)).toBeVisible();
  await expect(cards(page)).toHaveCount(1);
  // 呼ばれた tool が画面に出る（承認不要なので止まらない）。
  await expect(page.getByTestId("tool-header")).toContainText("search_docs");
});

test("一時メモを却下すると再開して書き留めなかった旨が出る", async ({
  page,
}) => {
  await page.goto("/chat");
  await send(page, NOTE_PROMPT);

  await expect(page.getByTestId("tool-approval")).toBeVisible();
  await page.getByRole("button", { name: "却下" }).click();

  await expect(page.getByText(DENIED_TEXT)).toBeVisible();
  await expect(page.getByTestId("tool-approval")).toHaveCount(0);
  // 止めた操作が再提案されない（同じ tool を撃ち直さない）。
  await expect(page.getByRole("main").getByText(SAVED_TEXT)).toHaveCount(0);
});

test("一時メモは承認前に止まり、承認すると元の run の profile で再開し、次の user turn は選び直した profile で送る", async ({
  page,
}) => {
  /*
   * **POST を丸ごと mock しない。** 中継と FastAPI の本物の境界を通し、送られた
   * profile だけを観測する。
   */
  const sent: string[] = [];
  await page.route("**/api/chat", async (route) => {
    const body = route.request().postDataJSON() as { profile?: string };
    sent.push(body?.profile ?? "<none>");
    await route.continue();
  });

  await page.goto("/chat");
  // 起動 profile は `playwright.config.ts` が DS4 に pin している。
  await send(page, NOTE_PROMPT);

  const approval = page.getByTestId("tool-approval");
  await expect(approval).toBeVisible();
  await expect(page.getByTestId("tool-header")).toContainText("save_note");
  // モデルが渡した引数が承認する前に読める（何を承認するのかが分かる）。
  await expect(cards(page)).toContainText(NOTE_TITLE);
  await expect(cards(page)).toContainText(NOTE_BODY);
  // **承認前に実行されていない。** 実行結果の文言はまだどこにも無い。
  await expect(page.getByRole("main").getByText(SAVED_TEXT)).toHaveCount(0);

  // 承認待ちのあいだに画面の選択を変える（生成中ではないので選べる）。
  await choose(page, LUNA_LABEL);
  await page.getByRole("button", { name: "承認" }).click();

  // 承認は 2 本目の run を自動で起こす（`sendAutomaticallyWhen`）。
  await expect(page.getByText(SAVED_TEXT)).toBeVisible();
  await expect(approval).toHaveCount(0);
  // 1 本目と承認再開の 2 本目は同じ profile（元の run を引き継ぐ）。
  expect(sent).toEqual([DS4, DS4]);

  // 続く user turn は現在選択している profile で送られ、応答も出る。
  await send(page, NEXT_PROMPT);
  await expect(page.getByText(NEXT_ANSWER)).toBeVisible();
  expect(sent).toEqual([DS4, DS4, LUNA]);
});
