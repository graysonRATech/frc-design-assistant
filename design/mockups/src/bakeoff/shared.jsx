// Shared content and TORCH theme definitions for the design-system bake-off. Each system
// (Astryx, Web Awesome, shadcn/ui) maps these same three themes onto its own tokens.

import { useId } from "react";
import { chats, sources, suggestions } from "../data.js";

export { chats, sources, suggestions };

export const THEMES = [
  { id: "auto", label: "Auto" },
  { id: "forge", label: "Forge" },
  { id: "collegiate", label: "Collegiate" },
  { id: "blueprint", label: "Blueprint" },
];

/** "auto" follows the OS: Collegiate in light mode, Forge in dark mode. */
export function resolveTheme(theme) {
  if (theme !== "auto") return theme;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "forge" : "collegiate";
}

export const palette = {
  forge: {
    mode: "dark",
    bg: "#0c1211", surface: "#131b19", raised: "#1a2422", border: "#26332f",
    text: "#eef1ec", muted: "#8fa09b", accent: "#fecc07", accent2: "#fd9727", onAccent: "#1a1300",
    accentSoft: "rgb(254 204 7 / 0.14)", user: "#0d4641", onUser: "#eef7f3",
    sidebar: "#090e0d", radius: 12,
  },
  collegiate: {
    mode: "light",
    bg: "#f8f7f4", surface: "#ffffff", raised: "#f1efea", border: "#e2ded6",
    text: "#0d4641", muted: "#5d7773", accent: "#00723e", accent2: "#fecc07", onAccent: "#ffffff",
    accentSoft: "#e2f2e7", user: "#0d4641", onUser: "#ffffff",
    sidebar: "#0d4641", radius: 8,
  },
  blueprint: {
    mode: "light",
    bg: "#f2f5f1", surface: "#fbfcfa", raised: "#e7efea", border: "#a9c1bb",
    text: "#0f2e2b", muted: "#557571", accent: "#e2700b", accent2: "#0d4641", onAccent: "#ffffff",
    accentSoft: "#fde8d2", user: "#fbfcfa", onUser: "#0f2e2b",
    sidebar: "#fbfcfa", radius: 2,
  },
};

export const fonts = {
  body: '"Barlow", system-ui, sans-serif',
  display: '"Barlow Condensed", "Barlow", sans-serif',
  mono: '"IBM Plex Mono", ui-monospace, monospace',
};

/** Placeholder flame-in-gear mark (swap in the team's real logo). */
export function Logo({ size = 32, gear = "currentColor", hole = "transparent" }) {
  const id = useId();
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="TORCH 5804">
      <defs>
        <linearGradient id={id} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#FD9727" />
          <stop offset="1" stopColor="#FECC07" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="26" fill="none" stroke={gear} strokeWidth="9" strokeDasharray="7.6 8.73" />
      <circle cx="32" cy="32" r="22" fill={gear} />
      <circle cx="32" cy="32" r="17" fill={hole} />
      <path
        d="M32 13c5 7 10 11 9 19-.6 5-4.4 9-9 9s-8.6-3.5-9-8.4c-.4-5 2.6-7.6 4.3-11.1.9 2.8 2 4.3 3.4 5.3.5-5 .2-9.4 1.3-13.8z"
        fill={`url(#${id})`}
      />
      <path d="M32 27c2.2 3 4.3 5 3.8 8.3-.3 2.1-1.9 3.7-3.8 3.7s-3.6-1.4-3.8-3.4c-.2-2.2 1.3-3.5 2.1-5.2.6 1 1.1 1.5 1.7 1.8z" fill="#FFF4C2" />
    </svg>
  );
}

export const question1 = "How do I calculate the center distance for two gears? We're pairing a 20T pinion with a 60T gear.";
export const question2 = "How should I set that up in Onshape?";

/** The first answer as Markdown with [n] citations (for systems that render Markdown). */
export const answer1Markdown = `Add the two pitch diameters and divide by two. For spur gears that's [1]:

\`C = (N₁ + N₂) / (2 × DP)\`

Most FRC gears are **20 DP**, so for your pair:

| Gear | Teeth | Pitch diameter |
|---|---|---|
| Pinion | 20 | 1.000 in |
| Driven | 60 | 3.000 in |
| **Center distance** | | **2.000 in** |

Put the bearing holes exactly that far apart in your plates [2], and check the mesh on a test print before you cut aluminum.`;

export const answer2Partial = `Start with a **master sketch** [3] so both plates share one source of truth:

1. Draw two construction circles at the pitch diameters, tangent to each other.
2. Dimension the center distance to \`2.000 in\` and lock it`;

export const chatGroups = [
  ["Today", chats.today],
  ["Previous 7 days", chats.week],
  ["Older", chats.older],
];

/** The "this is a prototype" notice, worded per theme. */
export const prototypeNotice = {
  text: "This app is in active prototyping. Expect bugs and occasional downtime.",
  label: { forge: "Pit notice", collegiate: "Prototype", blueprint: "Rev A · Preliminary" },
};
