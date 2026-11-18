// The theme setting: Auto (Collegiate in light mode, Forge in dark mode), Forge, Collegiate or
// Blueprint. Saved to the account (GET/PUT /settings) so it follows the student between devices,
// and cached in localStorage so the page opens in the right theme before the API answers.
import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { store } from "./auth.js";

export const THEMES = [
  { id: "auto", label: "Auto", description: "Follows your device: Collegiate by day, Forge in dark mode" },
  { id: "forge", label: "Forge", description: "Dark pit-and-workshop, flame accents" },
  { id: "collegiate", label: "Collegiate", description: "Light, in Collegiate School colors" },
  { id: "blueprint", label: "Blueprint", description: "An engineering drawing on grid paper" },
];

function usePrefersDark() {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return undefined;
    const update = (e) => setDark(e.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return dark;
}

/** Returns [choice, resolved theme id, setChoice]. Loads the saved choice once signed in. */
export function useThemeSetting(config, signedIn) {
  const [choice, setChoiceState] = useState(() => {
    const cached = store.get("theme");
    return THEMES.some((t) => t.id === cached) ? cached : "auto";
  });
  const dark = usePrefersDark();

  useEffect(() => {
    if (!signedIn) return;
    api(config, "GET", "/settings")
      .then(({ theme }) => {
        if (THEMES.some((t) => t.id === theme)) {
          setChoiceState(theme);
          store.set("theme", theme);
        }
      })
      .catch(() => {}); // keep the cached choice
  }, [config, signedIn]);

  const setChoice = useCallback(
    (theme) => {
      setChoiceState(theme);
      store.set("theme", theme);
      if (signedIn) api(config, "PUT", "/settings", { theme }).catch(() => {});
    },
    [config, signedIn],
  );

  const resolved = choice === "auto" ? (dark ? "forge" : "collegiate") : choice;
  return [choice, resolved, setChoice];
}
