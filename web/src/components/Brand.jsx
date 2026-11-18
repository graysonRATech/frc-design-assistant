import { useId, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";

/** Placeholder mark (a flame inside a gear) until the team's official logo file is dropped in. */
export function Logo({ size = 32 }) {
  const id = useId();
  return (
    <svg className="torch-logo" width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="TORCH 5804">
      <defs>
        <linearGradient id={id} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#FD9727" />
          <stop offset="1" stopColor="#FECC07" />
        </linearGradient>
      </defs>
      <circle className="torch-logo-gear" cx="32" cy="32" r="26" fill="none" strokeWidth="9" strokeDasharray="7.6 8.73" />
      <circle className="torch-logo-body" cx="32" cy="32" r="22" />
      <circle className="torch-logo-hole" cx="32" cy="32" r="17" />
      <path
        d="M32 13c5 7 10 11 9 19-.6 5-4.4 9-9 9s-8.6-3.5-9-8.4c-.4-5 2.6-7.6 4.3-11.1.9 2.8 2 4.3 3.4 5.3.5-5 .2-9.4 1.3-13.8z"
        fill={`url(#${id})`}
      />
      <path d="M32 27c2.2 3 4.3 5 3.8 8.3-.3 2.1-1.9 3.7-3.8 3.7s-3.6-1.4-3.8-3.4c-.2-2.2 1.3-3.5 2.1-5.2.6 1 1.1 1.5 1.7 1.8z" fill="#FFF4C2" />
    </svg>
  );
}

const NOTICE_LABEL = { forge: "Pit notice", collegiate: "Prototype", blueprint: "Rev A · Preliminary" };

/** "Expect bugs" notice, worded per theme. Dismissing hides it until the next visit. */
export function PrototypeBanner({ themeId }) {
  const [hidden, setHidden] = useState(() => sessionStorage.getItem("prototype-notice") === "hidden");
  if (hidden) return null;
  return (
    <div className="prototype-banner">
      <Banner
        status="warning"
        container="section"
        collapsible={false}
        isDismissable
        dismissLabel="Hide this notice"
        onDismiss={() => {
          sessionStorage.setItem("prototype-notice", "hidden");
          setHidden(true);
        }}
        title={
          <>
            <span className="prototype-label">{NOTICE_LABEL[themeId]}</span>
            This app is in active prototyping. Expect bugs and occasional downtime.
          </>
        }
      />
    </div>
  );
}
