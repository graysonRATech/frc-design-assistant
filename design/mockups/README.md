# UI mockups

Static mockups of three visual directions for the chat page, built as Storybook stories. Nothing here
talks to the app; it's for picking a direction before the real UI upgrade.

```
npm install
npm run storybook     # http://localhost:6006
```

- **Bake-off** builds the same chat screen with three open-source design systems, each wearing the
  TORCH themes, with a working theme picker and the prototype banner:
  [Astryx](https://github.com/meta/astryx) (Meta; React + StyleX), [Web Awesome](https://webawesome.com)
  (web components) and [shadcn/ui](https://ui.shadcn.com) (Radix + Tailwind, copied into
  `src/bakeoff/shadcn/components/ui`). **Component kit** shows each system's buttons, inputs,
  toggles, badges, banners and type.
- **Overview / Side by side** compares the three visual directions (hand-written HTML/CSS).
- Each direction has: Conversation (with a streaming answer), New chat, Sign in, Phone, and Phone with
  the chat list open.

How it's built: `src/markup.js` renders one page structure for every direction, and each
`src/variants/*.css` restyles it through design tokens plus its own details. The chosen direction's
tokens and rules port straight into `web/style.css`.

The flame-in-gear mark in `markup.js` is a placeholder drawn for these mockups. Replace it with the
team's official logo file.

Brand inputs: Collegiate School colors (deep teal `#0D4641`, green `#00723E`, gold `#FECC07`, orange
`#FD9727`, mint `#ABE5B8`) and fonts (Barlow, Barlow Condensed), plus IBM Plex Mono for technical labels.
