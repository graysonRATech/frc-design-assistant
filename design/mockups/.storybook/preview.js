import "../src/base.css";
import "../src/variants/forge.css";
import "../src/variants/collegiate.css";
import "../src/variants/blueprint.css";

export default {
  parameters: {
    layout: "fullscreen",
    controls: { expanded: true },
    options: { storySort: { order: ["Bake-off", ["Read me", "Astryx", "Web Awesome", "shadcn-ui", "Component kit"], "Overview", "Forge", "Collegiate", "Blueprint"] } },
  },
};
