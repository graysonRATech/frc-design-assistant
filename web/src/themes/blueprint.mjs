// TORCH "blueprint" theme. Built to static CSS + JS by `npm run themes` (no runtime style injection,
// so the page's Content-Security-Policy can stay strict).
import { defineTheme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral";
import { colorTokens, torch, typography } from "./palette.mjs";

export const blueprintTheme = defineTheme({
  name: "torch-blueprint",
  extends: neutralTheme,
  typography,
  radius: { base: 0, multiplier: 0 },
  tokens: colorTokens(torch.blueprint),
});

export default blueprintTheme;
