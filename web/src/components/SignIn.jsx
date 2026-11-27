import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useState } from "react";
import { inPanel, signIn, signInWithPopup } from "../lib/auth.js";
import { Logo, PrototypeBanner } from "./Brand.jsx";

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18">
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.7v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.4.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z" />
    </svg>
  );
}

export function SignIn({ config, themeId, error, onSignedIn }) {
  const [busy, setBusy] = useState(false);
  const [panelError, setPanelError] = useState("");
  const start = async () => {
    if (!inPanel) return signIn(config);
    setBusy(true);
    setPanelError("");
    try {
      onSignedIn(await signInWithPopup(config));
    } catch (failure) {
      setPanelError(failure.message);
    } finally {
      setBusy(false);
    }
  };
  const shown = panelError || error;
  return (
    <div className="signin">
      <PrototypeBanner themeId={themeId} />
      <div className="signin-stage">
        <Card padding={6} elevation="med" width={460} maxWidth="calc(100vw - 32px)">
          <VStack gap={3} align="center">
            <Logo size={72} />
            <Text type="label" color="accent" className="eyebrow">FRC Team 5804 · Collegiate School</Text>
            <Heading level={1} justify="center">TORCH Design Assistant</Heading>
            <Text color="secondary" justify="center" as="p">
              Mechanism design, Onshape CAD and fabrication answers from team-approved references like FRCDesign.org.
            </Text>
            <Button
              variant="secondary"
              size="lg"
              width="100%"
              label={busy ? "Finish signing in in the popup…" : "Sign in with Google"}
              icon={<GoogleMark />}
              disabled={busy}
              onClick={start}
            />
            <Text type="supporting" justify="center" as="p">
              For TORCH students and mentors. Use your school Google account.
              {inPanel ? " Sign-in opens in a small window." : ""}
            </Text>
            {shown ? <Banner status="error" title={shown} /> : null}
          </VStack>
        </Card>
      </div>
      <footer className="signin-foot">
        <span>2022 World Championship · 3rd place</span>
        <span>2023 Newton Division winners</span>
      </footer>
    </div>
  );
}
