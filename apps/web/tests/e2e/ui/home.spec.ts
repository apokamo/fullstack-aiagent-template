/**
 * トップ（`/`）からチャットへの導線の E2E。
 *
 * 名称・説明・導線の表示は Small（`@case:H1`）が確かめる。ここで確かめるのは
 * 実ブラウザでの画面遷移と、キーボードだけで導線に届くことである。文言は
 * 確かめない（遷移は URL と `/chat` の選択欄で確かめる）。
 */

import { expect, test, type Page } from "@playwright/test";

import { tabTo } from "./keyboard";

/** トップの導線（`main` の中の link は 1 つだけ）。 */
function chatLink(page: Page) {
  return page.getByRole("main").getByRole("link");
}

test(
  "トップの導線で /chat に移動する",
  { tag: ["@case:H2"] },
  async ({ page }) => {
    await page.goto("/");

    await expect(chatLink(page)).toHaveCount(1);
    await chatLink(page).click();

    await expect(page).toHaveURL(/\/chat$/u);
    await expect(page.getByTestId("model-select")).toBeVisible();
  },
);

test(
  "キーボードだけで導線に移動し、/chat を開ける",
  { tag: ["@case:H3"] },
  async ({ page }) => {
    await page.goto("/");

    await tabTo(page, chatLink(page));
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/\/chat$/u);
    await expect(page.getByTestId("model-select")).toBeVisible();
  },
);
