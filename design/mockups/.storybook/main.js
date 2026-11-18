/** Storybook for the UI mockups and the design-system bake-off (React + Vite). */
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";

export default {
  stories: ["../src/stories/*.stories.@(js|jsx)"],
  framework: { name: "@storybook/react-vite", options: {} },
  core: { disableTelemetry: true },
  async viteFinal(config) {
    config.plugins = [...(config.plugins || []), tailwindcss()];
    config.resolve = config.resolve || {};
    config.resolve.alias = { ...(config.resolve.alias || {}), "@": fileURLToPath(new URL("../src", import.meta.url)) };
    return config;
  },
};
