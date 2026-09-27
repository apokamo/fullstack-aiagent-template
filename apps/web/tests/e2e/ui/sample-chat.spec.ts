/**
 * サンプルの画面を fake model（`AGENT_MODEL_MODE=fake`）で通す E2E。
 *
 * ここが担うのは**実ブラウザでしか観測できないもの**だけである。承認の要否を
 * `mutates` から導く規則も、`resolveRequestProfile` の分岐も、状態ごとの文言も
 * backend / Small test が既に固定しているので、意味なく重複移植しない。
 *
 * **文言を確かめない。** 状態は role、testid、要素の数、URL、focus、scroll の
 * 位置、実際に送られた request で確かめる。扱う文字列は 3 つに分ける。
 *
 * - 確かめない: 画面の文言（固定文言・見出し・案内）と fake model の応答文。
 *   応答文は `apps/api/tests/test_sample_fake_model.py`（Small）が確かめる
 * - locator としてだけ使う: 操作に必要な accessible name（`Submit`、`Stop`、
 *   `承認`、`却下`、`再試行`、option の label）
 * - assertion に使ってよい: テストが入力したデータの echo（送った発話、fake model の
 *   固定引数 `NOTE_TITLE` / `NOTE_BODY`）、tool 名、profile id
 *
 * 「run が終わった」は応答文ではなく `runToEnd`（POST の応答を読み切り、停止ボタンが
 * 消える）で待ち、「結論が出た」は応答カードの直下の要素（part）の合計数で確かめる。
 *
 * 打つ文言と固定引数の正本は `apps/api/sample/fake_model.py` の定数（`TRIGGER_*` /
 * `FAKE_NOTE_*`）である。
 *
 * **`role="alert"` や件数を数えるときは `main` へ絞る。** dev server で動く E2E では
 * Next.js の dev overlay が `main` の外に要素を挿す。
 */

import { expect, test, type Page, type Request } from "@playwright/test";

import { CHAT_UNREACHABLE_ERROR_MESSAGE } from "../../../src/lib/chat-profiles";
import { pressUntilFocused, tabTo } from "./keyboard";

/** fake が `search_docs` へ倒す発話（trigger を 1 つも含まない）。 */
const SEARCH_PROMPT = "サンプル文書でテストのtierを検索して説明してください。";
/** fake が `save_note` へ倒す発話（`TRIGGER_NOTE` = 「メモ」を含む）。 */
const NOTE_PROMPT =
  "一時メモに、見出し『確認』、本文『テスト規約を確認する』を書き留めてください。";
/** `save_note` に載る固定引数（`FAKE_NOTE_TITLE` / `FAKE_NOTE_BODY`）。 */
const NOTE_TITLE = "確認";
const NOTE_BODY = "テスト規約を確認する";
/** fake が本文だけを返す発話（`TRIGGER_GREETING`）。 */
const GREETING_PROMPT = "こんにちは";
/** fake が本文を 5 断片に分けて間隔を空けて流す発話（`TRIGGER_SLOW` = 「詳しく」）。 */
const SLOW_PROMPT = "サンプル文書を詳しく説明してください。";
/** 承認再開のあとに送る次の user turn（`search_docs`）。 */
const NEXT_PROMPT = "環境変数の置き場を検索してください。";

const DS4 = "ds4-deepseek-v4-flash-chat";
const LUNA = "openai-luna-chat";
const LUNA_LABEL = "GPT-6 Luna（Chat）";

type ChatBody = {
  profile?: string;
  trigger?: string;
  messages?: unknown[];
};

/** `/api/chat` への POST か。 */
function isChatPost(request: Request): boolean {
  return (
    request.method() === "POST" &&
    new URL(request.url()).pathname === "/api/chat"
  );
}

/**
 * 実際に送られた `/api/chat` の POST の body を集める。
 *
 * **POST を丸ごと mock しない。** 中継と FastAPI の本物の境界を通し、観測だけする。
 * page の listener なので再読み込みをまたいで集め続ける。
 */
function recordChatPosts(page: Page): ChatBody[] {
  const bodies: ChatBody[] = [];
  page.on("request", (request) => {
    if (isChatPost(request)) {
      bodies.push((request.postDataJSON() as ChatBody | null) ?? {});
    }
  });
  return bodies;
}

/** 送った profile の並び。 */
function profilesOf(bodies: readonly ChatBody[]): string[] {
  return bodies.map((body) => body.profile ?? "<none>");
}

/**
 * `action` が起こす次の `/api/chat` の run が終わるまで待つ。
 *
 * 1. その POST の応答を待ち、body を読み切るまで待つ
 * 2. 停止ボタンが消えるまで待つ（body を読み切った後も、画面が stream を処理し
 *    終えるまで停止ボタンが残る）
 *
 * **`waitForResponse` は `action` の前に登録する。** 先に登録しないと速い応答を
 * 取りこぼす。1 が解決した時点で送信は始まっているので、送信直後の「まだ生成中に
 * なっていない」瞬間と 2 を取り違えない。
 */
async function runToEnd(
  page: Page,
  action: () => Promise<void>,
): Promise<void> {
  const response = page.waitForResponse((candidate) =>
    isChatPost(candidate.request()),
  );
  await action();
  await (await response).finished();
  await expect(page.getByRole("button", { name: "Stop" })).toHaveCount(0);
}

/** 一覧が ready になるまで待つ。 */
async function waitForProfiles(page: Page): Promise<void> {
  // **一覧が ready になるまで送信を止める**ので、選択欄が操作可能になってから
  // 打つ。待たないと click が握り潰される。
  await expect(page.getByTestId("model-select")).toBeEnabled();
}

/** 一覧が ready になるまで待ってから 1 通送る。 */
async function send(page: Page, text: string): Promise<void> {
  await waitForProfiles(page);
  await page.getByRole("textbox").fill(text);
  await page.getByRole("button", { name: "Submit" }).click();
}

/** 選択欄を開いて option を選ぶ。 */
async function choose(page: Page, label: string): Promise<void> {
  await page.getByTestId("model-select").click();
  await page.getByRole("option", { name: label }).click();
}

/** assistant の 1 応答（サンプルのカード）。 */
function cards(page: Page) {
  return page.getByRole("main").getByTestId("sample-response");
}

/**
 * 全カードの直下の要素（part）。
 *
 * `SampleResponse` は part ごとに 1 要素を描き、`step-start` などは描かない。
 * 承認の再開が同じカードに続くか新しいカードになるかに依存しないよう、カード
 * 単位ではなく合計で数える。
 */
function parts(page: Page) {
  return cards(page).locator(":scope > *");
}

test(
  "/chat で送ると自分の発話と応答のカードが出て、検索の tool 結果と結論が出る",
  { tag: ["@case:S1", "@case:S11"] },
  async ({ page }) => {
    const response = await page.goto("/chat");
    expect(response?.status()).toBe(200);

    await runToEnd(page, () => send(page, SEARCH_PROMPT));

    await expect(
      page.getByRole("log").getByText(SEARCH_PROMPT, { exact: true }),
    ).toHaveCount(1);
    await expect(cards(page)).toHaveCount(1);
    // tool 結果と結論（tool 1 + 本文 1）。
    await expect(parts(page)).toHaveCount(2);
    // 呼ばれた tool が画面に出る（承認不要なので止まらない）。
    await expect(page.getByTestId("tool-header")).toContainText("search_docs");
  },
);

test(
  "一時メモを却下すると再開し、同じ tool を再提案しない",
  { tag: ["@case:A5"] },
  async ({ page }) => {
    const posts = recordChatPosts(page);
    await page.goto("/chat");

    await runToEnd(page, () => send(page, NOTE_PROMPT));
    await expect(page.getByTestId("tool-approval")).toBeVisible();

    await runToEnd(page, () =>
      page.getByRole("button", { name: "却下" }).click(),
    );

    await expect(page.getByTestId("tool-approval")).toHaveCount(0);
    // 止めた操作が再提案されない（同じ tool を撃ち直さない）。
    await expect(page.getByTestId("tool-header")).toHaveCount(1);
    // 却下した tool と受け止めの本文。
    await expect(parts(page)).toHaveCount(2);
    // 承認待ちが残っていない。
    await expect(page.getByRole("button", { name: "Submit" })).toBeEnabled();
    expect(posts).toHaveLength(2);
  },
);

test(
  "一時メモは承認前に止まり、承認すると元の run の profile で再開し、次の user turn は選び直した profile で送る",
  { tag: ["@case:A1", "@case:A4", "@case:A6"] },
  async ({ page }) => {
    const posts = recordChatPosts(page);
    await page.goto("/chat");
    // 起動 profile は `playwright.config.ts` が DS4 に pin している。
    await runToEnd(page, () => send(page, NOTE_PROMPT));

    const approval = page.getByTestId("tool-approval");
    await expect(approval).toBeVisible();
    await expect(page.getByTestId("tool-header")).toContainText("save_note");
    // モデルが渡した引数が承認する前に読める（何を承認するのかが分かる）。
    await expect(cards(page)).toContainText(NOTE_TITLE);
    await expect(cards(page)).toContainText(NOTE_BODY);
    // **承認前に実行されていない。** 再開の run は起きておらず、結論も無い。
    expect(posts).toHaveLength(1);
    await expect(parts(page)).toHaveCount(1);

    // 承認待ちのあいだに画面の選択を変える（生成中ではないので選べる）。
    await choose(page, LUNA_LABEL);
    // 承認は 2 本目の run を自動で起こす（`sendAutomaticallyWhen`）。
    await runToEnd(page, () =>
      page.getByRole("button", { name: "承認" }).click(),
    );

    await expect(approval).toHaveCount(0);
    await expect(parts(page)).toHaveCount(2);
    // 1 本目と承認再開の 2 本目は同じ profile（元の run を引き継ぐ）。
    expect(profilesOf(posts)).toEqual([DS4, DS4]);

    // 続く user turn は現在選択している profile で送られ、応答も出る。
    await runToEnd(page, () => send(page, NEXT_PROMPT));
    await expect(parts(page)).toHaveCount(4);
    expect(profilesOf(posts)).toEqual([DS4, DS4, LUNA]);
  },
);

test("停止ボタンで生成が止まる", { tag: ["@case:S4"] }, async ({ page }) => {
  await page.goto("/chat");
  await send(page, SLOW_PROMPT);

  const stop = page.getByRole("button", { name: "Stop" });
  await expect(stop).toBeVisible();
  const aborted = page.waitForEvent("requestfailed", isChatPost);
  await stop.click();

  // 進行中の POST が中断される（stream を読み切る前に止まる）。
  await aborted;
  await expect(stop).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Submit" })).toBeVisible();
  await expect(page.getByRole("textbox")).toBeEditable();
});

test.describe("表示の伸びと自動スクロール", () => {
  // 時間の上限ではなく、2 つの応答で中身がはみ出す高さにする。
  test.use({ viewport: { width: 1280, height: 360 } });

  test(
    "応答が流れるにつれて新しいカードの表示が伸び、下までスクロールする",
    { tag: ["@case:S9"] },
    async ({ page }) => {
      await page.goto("/chat");
      await runToEnd(page, () => send(page, GREETING_PROMPT));
      await expect(cards(page)).toHaveCount(1);

      /** 会話の scroll 要素と 2 件目のカードの寸法。 */
      const measure = () =>
        page.evaluate(() => {
          const log = document.querySelector('[role="log"]');
          const scroller = Array.from(
            log?.querySelectorAll<HTMLElement>("*") ?? [],
          ).find((element) =>
            ["auto", "scroll"].includes(getComputedStyle(element).overflowY),
          );
          if (!scroller) {
            throw new Error("会話の scroll 要素が見つかりません");
          }
          const card = log?.querySelectorAll(
            '[data-testid="sample-response"]',
          )[1];
          return {
            scrollHeight: scroller.scrollHeight,
            clientHeight: scroller.clientHeight,
            gapToBottom:
              scroller.scrollHeight -
              scroller.scrollTop -
              scroller.clientHeight,
            scrollerBottom: scroller.getBoundingClientRect().bottom,
            cardBottom: card?.getBoundingClientRect().bottom ?? null,
          };
        });

      const before = await measure();

      // SLOW の run で新しく作られる 2 件目のカードだけを観測する（GREETING の
      // 既存カードは記録しない）。
      await page.evaluate(() => {
        const log = document.querySelector('[role="log"]');
        if (!log) {
          throw new Error("会話が見つかりません");
        }
        const lengths: number[] = [];
        (window as unknown as { slowCardLengths: number[] }).slowCardLengths =
          lengths;
        new MutationObserver(() => {
          const card = log.querySelectorAll(
            '[data-testid="sample-response"]',
          )[1];
          if (card) {
            lengths.push(card.textContent?.length ?? 0);
          }
        }).observe(log, {
          childList: true,
          subtree: true,
          characterData: true,
        });
      });

      await runToEnd(page, () => send(page, SLOW_PROMPT));
      await expect(cards(page)).toHaveCount(2);

      const lengths = await page.evaluate(
        () =>
          (window as unknown as { slowCardLengths: number[] }).slowCardLengths,
      );
      const grown = lengths.filter((length) => length > 0);
      // 表示が段階的に伸びた（一度に出たのではない）。
      expect(new Set(grown).size).toBeGreaterThanOrEqual(2);
      expect(grown).toEqual([...grown].sort((a, b) => a - b));

      // SLOW のカードで中身がはみ出した。
      const after = await measure();
      expect(after.scrollHeight).toBeGreaterThan(before.scrollHeight);
      expect(after.scrollHeight).toBeGreaterThan(after.clientHeight);
      // 下端にいて、新しいカードの末尾が見えている。
      await expect
        .poll(async () => (await measure()).gapToBottom)
        .toBeLessThanOrEqual(1);
      await expect
        .poll(async () => {
          const { cardBottom, scrollerBottom } = await measure();
          return cardBottom !== null && cardBottom <= scrollerBottom + 1;
        })
        .toBe(true);
    },
  );
});

test(
  "送信の失敗から再試行すると失敗の表示が消え、送り直せる",
  { tag: ["@case:E2"] },
  async ({ page }) => {
    const posts = recordChatPosts(page);
    // 最初の POST だけ中継が FastAPI に届かなかった応答にする。2 本目は本物の境界を通る。
    await page.route(
      "**/api/chat",
      (route) =>
        route.fulfill({
          status: 502,
          contentType: "application/json",
          body: JSON.stringify({ error: CHAT_UNREACHABLE_ERROR_MESSAGE }),
        }),
      { times: 1 },
    );
    await page.goto("/chat");

    await runToEnd(page, () => send(page, SEARCH_PROMPT));

    const alerts = page.getByRole("main").getByRole("alert");
    await expect(alerts).toHaveCount(1);
    const retry = alerts.getByRole("button", { name: "再試行" });
    await expect(retry).toBeVisible();

    await runToEnd(page, () => retry.click());

    await expect(alerts).toHaveCount(0);
    await expect(cards(page)).toHaveCount(1);
    expect(posts).toHaveLength(2);
  },
);

test(
  "承認待ちで再読み込みすると会話が消え、書き込みは実行されない",
  { tag: ["@case:A8"] },
  async ({ page }) => {
    const posts = recordChatPosts(page);
    await page.goto("/chat");
    await runToEnd(page, () => send(page, NOTE_PROMPT));
    await expect(page.getByTestId("tool-approval")).toBeVisible();

    await page.reload();
    await waitForProfiles(page);

    await expect(cards(page)).toHaveCount(0);
    await expect(page.getByTestId("tool-approval")).toHaveCount(0);
    // 空の会話の案内だけがある。
    await expect(page.getByRole("log").getByRole("heading")).toHaveCount(1);

    await runToEnd(page, () => send(page, GREETING_PROMPT));

    // 承認の再開の POST は無い（書き込みは実行されない）。
    expect(posts).toHaveLength(2);
    // 次の送信は前の会話を運ばない。
    expect(posts[1].trigger).toBe("submit-message");
    expect(posts[1].messages).toHaveLength(1);
  },
);

test(
  "再読み込みするとモデルの選択が既定に戻る",
  { tag: ["@case:P11"] },
  async ({ page }) => {
    const posts = recordChatPosts(page);
    await page.goto("/chat");
    await waitForProfiles(page);
    await choose(page, LUNA_LABEL);

    await page.reload();
    await waitForProfiles(page);
    await runToEnd(page, () => send(page, GREETING_PROMPT));

    // 既定は DS4（`playwright.config.ts` と `make test-e2e` が `LLM_PROFILE` を pin）。
    expect(profilesOf(posts)).toEqual([DS4]);
  },
);

test(
  "キーボードだけでモデル選択・送信・承認ができる",
  { tag: ["@case:X3"] },
  async ({ page }) => {
    const posts = recordChatPosts(page);
    await page.goto("/chat");
    await waitForProfiles(page);

    const select = page.getByTestId("model-select");
    await tabTo(page, select);
    await page.keyboard.press("Enter");
    const options = page.getByRole("option");
    await expect(options.first()).toBeVisible();
    await pressUntilFocused(
      page,
      page.getByRole("option", { name: LUNA_LABEL }),
      "ArrowDown",
      await options.count(),
    );
    await page.keyboard.press("Enter");
    await expect(options).toHaveCount(0);

    await tabTo(page, page.getByRole("textbox"));
    await page.keyboard.type(NOTE_PROMPT);
    await runToEnd(page, () => page.keyboard.press("Enter"));
    await expect(page.getByTestId("tool-approval")).toBeVisible();

    await tabTo(page, page.getByRole("button", { name: "承認" }));
    await runToEnd(page, () => page.keyboard.press("Enter"));

    await expect(page.getByTestId("tool-approval")).toHaveCount(0);
    // キーボードの選択が送信に反映され、承認で再開した。
    expect(profilesOf(posts)).toEqual([LUNA, LUNA]);
  },
);
