// Root: loads /config.json, finishes the Google sign-in redirect, applies the theme, and shows
// either the sign-in screen or the chat.
import { useEffect, useState } from "react";
import { Theme } from "@astryxdesign/core/theme";
import { torchBlueprintTheme } from "./themes/torch-blueprint.js";
import { torchCollegiateTheme } from "./themes/torch-collegiate.js";
import { torchForgeTheme } from "./themes/torch-forge.js";
import { completeRedirect, currentSession } from "./lib/auth.js";
import { useThemeSetting } from "./lib/theme.js";
import { ChatApp } from "./components/ChatApp.jsx";
import { SignIn } from "./components/SignIn.jsx";

const THEME_OBJECTS = { forge: torchForgeTheme, collegiate: torchCollegiateTheme, blueprint: torchBlueprintTheme };
const MODES = { forge: "dark", collegiate: "light", blueprint: "light" };

export function App() {
  const [config, setConfig] = useState(null);
  const [session, setSession] = useState(undefined); // undefined while loading, null when signed out
  const [authError, setAuthError] = useState("");
  const [choice, themeId, setChoice] = useThemeSetting(config, !!session);

  useEffect(() => {
    (async () => {
      const cfg = await (await fetch("/config.json", { cache: "no-store" })).json();
      setConfig(cfg);
      const params = new URLSearchParams(location.search);
      if (params.has("error")) {
        history.replaceState(null, "", location.pathname);
        // Cognito prefixes trigger errors, e.g. "PreSignUp failed with error <message>."
        setAuthError((params.get("error_description") || params.get("error")).replace(/^.*failed with error\s*/i, ""));
        return setSession(null);
      }
      try {
        setSession(params.has("code") ? await completeRedirect(cfg, params) : await currentSession(cfg));
      } catch (error) {
        setAuthError(error.message);
        setSession(null);
      }
    })().catch(() => setAuthError("Couldn't load the app. Try refreshing."));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.torchTheme = themeId;
  }, [themeId]);

  const signedOut = (message) => {
    setAuthError(message || "");
    setSession(null);
  };

  return (
    <Theme theme={THEME_OBJECTS[themeId]} mode={MODES[themeId]}>
      <div className={`torch-app torch-${themeId}`}>
        {!config || session === undefined ? (
          authError ? <p className="boot-error">{authError}</p> : null
        ) : session ? (
          <ChatApp config={config} session={session} themeId={themeId} themeChoice={choice} onThemeChange={setChoice} onSignedOut={signedOut} />
        ) : (
          <SignIn config={config} themeId={themeId} error={authError} />
        )}
      </div>
    </Theme>
  );
}
