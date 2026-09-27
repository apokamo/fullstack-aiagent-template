/**
 * モデル選択欄の表示と操作。
 *
 * ここで見るのは **状態 → 選択可否・表示** の写像である。実ブラウザでの選択と
 * 送信への反映は fake model の E2E（`tests/e2e/ui/sample-chat.spec.ts`）が見る。
 *
 * jsdom は Radix が使う pointer capture と `scrollIntoView` を持たないので、
 * この module のなかだけで補う（共有 setup は変えない）。
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

import {
  ModelSelect,
  type ModelSelectProps,
} from "@/components/chat/model-select";
import type { ChatProfileOption } from "@/lib/chat-profiles";

const PROFILES: readonly ChatProfileOption[] = [
  { id: "profile-a", label: "Model A", available: true },
  { id: "profile-b", label: "Model B", available: true },
];

const UNAVAILABLE: readonly ChatProfileOption[] = [
  { id: "profile-a", label: "Model A", available: true },
  {
    id: "profile-b",
    label: "Model B",
    available: false,
    unavailableReason: "サーバーに接続情報が登録されていません",
  },
];

beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.setPointerCapture ??= () => undefined;
  Element.prototype.releasePointerCapture ??= () => undefined;
  Element.prototype.scrollIntoView ??= () => undefined;
});

function renderSelect(overrides: Partial<ModelSelectProps> = {}) {
  const props: ModelSelectProps = {
    status: "ready",
    profiles: PROFILES,
    value: "profile-a",
    onValueChange: vi.fn(),
    disabled: false,
    onRetry: vi.fn(),
    ...overrides,
  };
  render(<ModelSelect {...props} />);
  return props;
}

describe("model select", { tags: ["small"] }, () => {
  it("一覧が ready なら選べて、失敗表示を出さない", () => {
    renderSelect();

    expect(screen.getByTestId("model-select")).toBeEnabled();
    expect(screen.queryByTestId("model-list-error")).toBeNull();
  });

  it("@case:P1 一覧の取得中は選べず、「読み込み中…」を出す", () => {
    renderSelect({ status: "loading", profiles: [], value: "" });

    const select = screen.getByTestId("model-select");
    expect(select).toBeDisabled();
    expect(select).toHaveTextContent("読み込み中…");
  });

  it("@case:X1 選択欄に可視ラベル「モデル」が結び付いている", () => {
    renderSelect();

    expect(screen.getByRole("combobox", { name: "モデル" })).toBe(
      screen.getByTestId("model-select"),
    );
  });

  it("@case:P8 一覧の取得中・取得失敗・生成中は選べない", () => {
    for (const overrides of [
      { status: "loading", value: "" },
      { status: "failed", value: "" },
      { disabled: true },
    ] satisfies Partial<ModelSelectProps>[]) {
      const { unmount } = render(
        <ModelSelect
          status="ready"
          profiles={PROFILES}
          value="profile-a"
          onValueChange={vi.fn()}
          disabled={false}
          onRetry={vi.fn()}
          {...overrides}
        />,
      );
      expect(screen.getByTestId("model-select")).toBeDisabled();
      unmount();
    }
  });

  it("@case:P3 @case:X2 一覧取得に失敗したら理由と再取得導線を読み上げ対象で出す", async () => {
    const onRetry = vi.fn();
    renderSelect({ status: "failed", value: "", onRetry });

    const error = screen.getByTestId("model-list-error");
    expect(error).toHaveAttribute("role", "alert");
    expect(error).toHaveTextContent(
      "モデル一覧を取得できませんでした。再取得してください。",
    );
    await userEvent.click(screen.getByRole("button", { name: "再取得" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("@case:P5 利用不可の選択肢は選べず、理由を文字で添える", async () => {
    renderSelect({ profiles: UNAVAILABLE });

    await userEvent.click(screen.getByTestId("model-select"));

    const unavailable = screen.getByRole("option", { name: /Model B/u });
    expect(unavailable).toHaveAttribute("aria-disabled", "true");
    // 色だけで区別しない（design-system.md）。
    expect(unavailable).toHaveTextContent(
      "サーバーに接続情報が登録されていません",
    );
  });

  it("@case:P7 選べる選択肢を選ぶと呼び出し側へ id を渡す", async () => {
    const onValueChange = vi.fn();
    renderSelect({ onValueChange });

    await userEvent.click(screen.getByTestId("model-select"));
    await userEvent.click(screen.getByRole("option", { name: "Model B" }));

    expect(onValueChange).toHaveBeenCalledWith("profile-b");
  });
});
