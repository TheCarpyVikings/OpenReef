import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "brine-hatchery",
  h1: "The Brine Hatchery",
  lede: "Track live brine from hatch to harvest, storage and enrichment. OpenReef turns your logged actions and chosen timings into reminders and supply estimates, so you can plan the next batch and check hatch-out when it matters.",
  buddyLine: "Hatch, harvest, hold, enrich. Four clocks, one tin of eggs, and a phone that knows which one is ticking.",
  buddyPose: "thinking",
  img: "/demos/hatchery/3-the-rig-live.png",
  imgAlt: "The hatchery rig drawn live — two vessels, three valves, one mesh — following the stage the hatch is in",
  demoLabel: "Open Feeding → Brine hatchery in the demo",
  gallery: [
    { src: "/demos/hatchery/2-today.png", alt: "Today: the hatch at 58 %, the fridge bottle, the brine container and the plan for the next hatch" },
    { src: "/demos/hatchery/1-summary.png", alt: "The four numbers: batch progress, container, next hatch, and the temperature-adjusted clock" },
    { src: "/demos/nps/4-brine-hatchery.png", alt: "The hatchery card as it appears on the NPS tab" },
  ],
  sections: [
    {
      heading: "A clock for each hatchery",
      paragraphs: [
        "Each vessel keeps its own cyst type and hatch clock. Standard, premium and hatchable decapsulated cysts start with a 24 h planning default; the cool-room preset starts at 36 h. Follow the supplier's timing and inspect the hatch: grade and shell removal alone do not establish completion time. The optional temperature model is a rough heuristic. The cyst guide starts at 2 g per litre; its nauplii count is illustrative.",
        "Use up to four vessels. The planner compares when each could complete its next batch, checks storage and volume limits, and reports projected supply gaps. Steady supply depends on cycle lengths, spacing, harvest handling and feed demand; two cones do not guarantee it.",
      ],
    },
    {
      heading: "Two nutrition clocks, not one",
      paragraphs: [
        "The handling model budgets 24 h warm or 48 h cold for plain brine, accounting for when refrigeration starts. Under that model, twelve warm hours use half the budget, leaving 24 cold hours. Refrigeration cannot restore an expired batch, and topping up does not renew older brine. These are planning limits, not measurements of viability.",
        "Unfed nauplii use their reserves from hatch onward; loading the container does not establish their biological age. Enrichment uptake requires feeding-stage nauplii. OpenReef counts the configured soak from the first logged dose and the post-soak window from its planned end, so a late confirmation does not renew the clock. Confirm the animals' stage and follow the enrichment product's instructions.",
      ],
      snippet: `hatchery 1 · premium · 24 h clock
  14 h elapsed · ~10 h to the planned harvest
  next start considers each cone's completion time
fridge bottle 180 ml · its own storage clock
enrichment: confirm feeding stage before dosing`,
    },
    {
      heading: "The rig, drawn live",
      paragraphs: [
        "Two vessels, three valves, one mesh. The drawing follows whatever stage the hatchery is in — air on for the hatch, shells floating and cysts sinking, the transfer to the live vessel, the crud bleed, the mesh drain through a 120 µm disc, the backflush that washes the nauplii home — and Play the stages walks a newcomer through the whole sequence before they've wet a hose.",
        "Harvests enter the journal, and feeds debit the container or fridge bottle. The hatch-ready reminder provides a Hatched & loaded button; it still needs you to check the hatch. Quiet hours can delay that reminder. The 120 µm screen retains nauplii and larger debris: keep it submerged, rinse gently and inspect the catch.",
      ],
    },
  ],
  limits: [
    "The hatch hours are presets and a temperature adjustment, not a sensor in the cone — the harvest window is a forecast you confirm by looking.",
    "Enrichment is a step you do; OpenReef times the soak, debits the bottle and refuses to bottle mid-soak, but it can't see the emulsion go in.",
    "Supply forecasts assume prompt harvests and restarts, sufficient batch volume and the chosen storage windows. The rack forecast does not schedule the physical cleaning, rinsing or enrichment workflow.",
    "Feeding out live brine is a hand dose today unless a live-food pump is linked in Settings — then the pump doses it and the shelf debits it.",
  ],
  faq: [
    {
      q: "Why does it care whether the brine went in the fridge?",
      a: "Cold storage slows development and energy use. The app applies a planning model to the time logged warm and cold; it cannot measure survival, oxygen or nutritional content. Check storage conditions and the batch itself before feeding.",
    },
    {
      q: "What's the point of enriching if I feed them within a day?",
      a: "An appropriate enrichment can change the food's nutrient profile for the animals you keep. Uptake depends on feeding stage, product, density, aeration and duration. OpenReef times the protocol you select; it cannot confirm a nutrient level from elapsed time alone.",
    },
    {
      q: "Do I need NPS corals for this?",
      a: "No. The hatchery works independently of NPS mode. Choose live brine and any enrichment according to the feeding needs and prey size of your livestock.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
