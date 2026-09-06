import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "brine-hatchery",
  h1: "The Brine Hatchery",
  lede: "Live baby brine is the best food most reefs never get, because hatching it is a 24-hour chore with four clocks nobody keeps in their head. OpenReef keeps them: the hatch, the yolk, the fridge, and the enrichment — every one a real stamp, every push at the hour that matters.",
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
      heading: "A clock that knows what eggs you bought",
      paragraphs: [
        "Four egg presets carry their own hatch hours — standard Great Salt Lake cysts around 24 h, decapsulated around 16 h, high-hatch premium grades around 20 h, and a cool room without a heater budgeting up to 36 h — because temperature rules the clock. The hatch is a stamped timestamp evaluated on read: incubating with an honest percentage, ready in its harvest window, then overdue with a grace period while the yolk clock keeps running. The card shows the expectation adjusted to your room (27.6 °C → expect ~20.6 h) and a cyst guide at 2 g per litre with a rough nauplii count.",
        "Up to four vessels, and the tab is blunt about continuity: with 24-hour eggs and 24-hour brine life, an unbroken supply needs two hatcheries — so it plans the next hatch to land before the current harvest fades, and tells you when one vessel isn't enough.",
      ],
    },
    {
      heading: "Two nutrition clocks, not one",
      paragraphs: [
        "Freshness runs on a two-rate clock: a batch spends its window at the room rate (24 h) until the moment it goes into the fridge, then at the fridge rate (48 h) from then on — so a fresh load fridged at once gets the full two days, one fridged after twelve warm hours has half its life left and spends that half slowly, and taking it out banks the hours the fridge saved.",
        "Nutrition is a second clock entirely. An unenriched batch runs on yolk — prime for the first 24 hours, then fading as reserves burn down. An enriched batch has been fed: it isn't starving at 24 h, it's gut-loaded and carrying the DHA that Great Salt Lake nauplii never have on their own; what ticks from then is the boost draining away. And the enrichment soak anchors on the first dose, not the load, because instar I nauplii cannot eat — the molt lands six to twelve hours after hatching, and emulsion dosed before it just fouls the water.",
      ],
      snippet: `hatchery 1 · premium · 24 h clock
  14 h elapsed · ~10 h to go · 27.6 °C → expect ~20.6 h
  next hatch 09:26 tomorrow — keeps the chain unbroken
fridge bottle 180 ml · mixed 6 h ago · ~18 h of life left
enrichment: first dose due once the nauplii can eat`,
    },
    {
      heading: "The rig, drawn live",
      paragraphs: [
        "Two vessels, three valves, one mesh. The drawing follows whatever stage the hatchery is in — air on for the hatch, shells floating and cysts sinking, the transfer to the live vessel, the crud bleed, the mesh drain through a 120 µm disc, the backflush that washes the nauplii home — and Play the stages walks a newcomer through the whole sequence before they've wet a hose.",
        "Every harvest debits the cysts and feeds the timeline: the brine container's doses land on today's strip as planned slots, a hand-feed logs against the container or the fridge bottle, and Hatched & loaded arrives on your phone as a button, not a paragraph. Quiet hours hold the ready push overnight and say how long it's been waiting when it finally lands.",
      ],
    },
  ],
  limits: [
    "The hatch hours are presets and a temperature adjustment, not a sensor in the cone — the harvest window is a forecast you confirm by looking.",
    "Enrichment is a step you do; OpenReef times the soak, debits the bottle and refuses to bottle mid-soak, but it can't see the emulsion go in.",
    "Continuous supply genuinely needs two vessels; with one, the tab tells you so and plans around the gap rather than pretending.",
    "Feeding out live brine is a hand dose today unless a live-food pump is linked in Settings — then the pump doses it and the shelf debits it.",
  ],
  faq: [
    {
      q: "Why does it care whether the brine went in the fridge?",
      a: "Because the fridge roughly doubles brine life, but only for the hours it was actually cold. The two-rate clock gives credit for exactly that time — a batch fridged at once keeps two days, one fridged late keeps less, and the number on the card is honest either way.",
    },
    {
      q: "What's the point of enriching if I feed them within a day?",
      a: "Great Salt Lake nauplii carry almost no DHA on their own; a few hours in an enrichment emulsion after their first molt loads them with it. OpenReef delays the dose until they can actually eat, then counts down the boost so you feed at the peak, not after it's gone.",
    },
    {
      q: "Do I need NPS corals for this?",
      a: "No — the hatchery page says it itself: no NPS corals required. Live brine is the best conditioning food for most fish and LPS; the NPS system just gives it a bigger job.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
