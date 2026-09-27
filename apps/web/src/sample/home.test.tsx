/**
 * サンプルエージェントのトップページ。
 *
 * 名称と説明は root layout（`src/app/layout.tsx`）の metadata と同じ文言である。
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./home";
import { metadata } from "@/app/layout";

describe("sample home", { tags: ["small"] }, () => {
  it("@case:H1 metadata と同じ名称・説明と、チャットへの導線を出す", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { level: 1, name: String(metadata.title) }),
    ).toBeInTheDocument();
    expect(screen.getByText(String(metadata.description))).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "チャットを開く" }),
    ).toHaveAttribute("href", "/chat");
  });
});
