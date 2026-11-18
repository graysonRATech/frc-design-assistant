// TORCH "forge" theme. Built to static CSS + JS by `npm run themes` (no runtime style injection,
// so the page's Content-Security-Policy can stay strict).
import { defineTheme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral";
import { colorTokens, torch, typography } from "./palette.mjs";

export const forgeTheme = defineTheme({
  name: "torch-forge",
  extends: neutralTheme,
  typography,
  radius: { base: 10, multiplier: 1 },
  tokens: colorTokens(torch.forge),
});

export default forgeTheme;
