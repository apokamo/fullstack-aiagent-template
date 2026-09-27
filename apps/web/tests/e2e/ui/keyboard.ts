/**
 * キーボードだけで操作する E2E の共通 helper（テストではない module）。
 *
 * **Tab の回数を固定しない。** dev server は `main` の外に focus できる要素
 * （Next.js の dev overlay）を挿すことがあるので、focus を確かめながら進める。
 * 上限を置くので、focus が来ない場合は黙って成功せず失敗する。
 */

import { expect, type Locator, type Page } from "@playwright/test";

/** `target` に focus があるか。 */
async function isFocused(target: Locator): Promise<boolean> {
  return target.evaluate((element) => element === document.activeElement);
}

/**
 * `target` に focus が来るまで `key` を押す。`maxPresses` 回で来なければ失敗する。
 */
export async function pressUntilFocused(
  page: Page,
  target: Locator,
  key: string,
  maxPresses: number,
): Promise<void> {
  for (let pressed = 0; pressed < maxPresses; pressed += 1) {
    if (await isFocused(target)) {
      break;
    }
    await page.keyboard.press(key);
  }
  await expect(target).toBeFocused();
}

/** `target` に focus が来るまで Tab を押す。`maxPresses` 回で来なければ失敗する。 */
export async function tabTo(
  page: Page,
  target: Locator,
  maxPresses = 30,
): Promise<void> {
  await pressUntilFocused(page, target, "Tab", maxPresses);
}
