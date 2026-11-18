import { appPage } from "../markup.js";
import { Html } from "./variant.jsx";

export default { title: "Overview" };

const directions = [
  {
    id: "forge",
    name: "Forge",
    blurb: "Dark pit-and-workshop. Near-black greens, with the flame gradient saved for actions, citations and the live cursor.",
    swatches: ["#0c1211", "#131b19", "#0d4641", "#fecc07", "#fd9727", "#eef1ec"],
  },
  {
    id: "collegiate",
    name: "Collegiate",
    blurb: "Light and editorial, closest to the school site. Deep teal ink, Collegiate green actions, gold highlights, condensed uppercase headlines.",
    swatches: ["#0d4641", "#00723e", "#fecc07", "#f8f7f4", "#e2f2e7", "#ffffff"],
  },
  {
    id: "blueprint",
    name: "Blueprint",
    blurb: "An engineering drawing. Grid paper, teal linework, mono labels, a title block, and citations drawn as BOM balloons.",
    swatches: ["#f2f5f1", "#0d4641", "#0f2e2b", "#e2700b", "#a9c1bb", "#fbfcfa"],
  },
];

export const SideBySide = {
  name: "Side by side",
  render: () => <Html html={`<div class="compare">${directions
    .map(
      (d) => `<figure>
        <figcaption><b>${d.name}</b>${d.blurb}</figcaption>
        <div class="swatches">${d.swatches.map((c) => `<span style="background:${c}" title="${c}"></span>`).join("")}</div>
        <div class="frame"><div class="scale">${appPage(d.id)}</div></div>
        <div class="frame"><div class="scale">${appPage(d.id, { screen: "empty" })}</div></div>
      </figure>`,
    )
    .join("")}</div>`} />,
};
