import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * shadcn/ui 生成コンポーネントが `@/lib/utils` から import する class 名結合ヘルパ。
 * `components.json` の `aliases.utils` がこのパスを指している。
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
