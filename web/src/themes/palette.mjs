// TORCH 5804 colors, from Collegiate School's brand (deep teal, green, flame gold and orange).
export const torch = {
  forge: {
    bg: "#0c1211", surface: "#131b19", muted: "#1a2422", border: "#26332f", emphasized: "#3a4a46",
    text: "#eef1ec", secondary: "#8fa09b", accent: "#fecc07", onAccent: "#1a1300", accentMuted: "#3a3410", textAccent: "#fecc07",
  },
  collegiate: {
    bg: "#f8f7f4", surface: "#ffffff", muted: "#f1efea", border: "#e2ded6", emphasized: "#0d4641",
    text: "#0d4641", secondary: "#5d7773", accent: "#00723e", onAccent: "#ffffff", accentMuted: "#e2f2e7", textAccent: "#00723e",
  },
  blueprint: {
    bg: "#f2f5f1", surface: "#fbfcfa", muted: "#e7efea", border: "#a9c1bb", emphasized: "#0d4641",
    text: "#0f2e2b", secondary: "#557571", accent: "#0d4641", onAccent: "#ffffff", accentMuted: "#fde8d2", textAccent: "#e2700b",
  },
};

/** Token overrides shared by the three themes; each color is the same in light and dark mode. */
export function colorTokens(p) {
  const both = (v) => [v, v];
  return {
    "--color-accent": both(p.accent),
    "--color-on-accent": both(p.onAccent),
    "--color-accent-muted": both(p.accentMuted),
    "--color-text-accent": both(p.textAccent),
    "--color-icon-accent": both(p.textAccent),
    "--color-background-body": both(p.bg),
    "--color-background-surface": both(p.surface),
    "--color-background-card": both(p.surface),
    "--color-background-popover": both(p.surface),
    "--color-background-muted": both(p.muted),
    "--color-text-primary": both(p.text),
    "--color-text-secondary": both(p.secondary),
    "--color-icon-primary": both(p.text),
    "--color-icon-secondary": both(p.secondary),
    "--color-border": both(p.border),
    "--color-border-emphasized": both(p.emphasized),
  };
}

export const typography = {
  scale: { base: 15, ratio: 1.2 },
  body: { family: "Barlow", fallbacks: "system-ui, sans-serif" },
  heading: { family: "Barlow Condensed", fallbacks: "Barlow, sans-serif" },
  code: { family: "IBM Plex Mono", fallbacks: "ui-monospace, monospace" },
};
