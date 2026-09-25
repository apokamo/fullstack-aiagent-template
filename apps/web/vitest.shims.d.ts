import "vitest";

declare module "vitest" {
  interface TestTags {
    tags: "small" | "medium" | "large" | "smoke" | "a11y" | "performance";
  }
}
