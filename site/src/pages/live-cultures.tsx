import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "live-cultures",
  h1: "Live Cultures",
  lede: "A brine hatch is a batch measured in hours. A rotifer jar is a standing population measured in days, and a copepod tub is slower still. OpenReef runs all three temporal regimes on one tab — with real clocks, a learning journal, and a phone that asks the right question at the right time.",
  buddyLine: "A rotifer jar is a population, not a batch. I keep the clocks; you keep the sieve.",
  buddyPose: "thinking",
  img: "/demos/cultures/2-the-rack.png",
  imgAlt: "The rack: two jars and the rotifer bottle, each with its clocks, chores, signs and the heat guard",
  demoLabel: "Open Feeding → Cultures in the demo",
  gallery: [
    { src: "/demos/cultures/3-the-rig-live.png", alt: "The cone rig drawn live — air, purge, harvest, refill — following the jar's stage" },
    { src: "/demos/cultures/1-summary.png", alt: "Due now, the rotifer bottle, jar backup status and the room temperature" },
    { src: "/demos/cultures/4-how-each-one-wants-keeping.png", alt: "How each species wants keeping: the presets behind the clocks" },
  ],
  sections: [
    {
      heading: "Two species, two rhythms",
      paragraphs: [
        "Rotifers (L-type) are a chemostat: the daily harvest is the water change is the ammonia control, and a sieve-and-restart every fortnight means the week-four ciliate crash never arrives. Tigriopus copepods are forgiving and slow: feed every few days, harvest weekly, change water when the jar tells you. The presets carry the numbers from the research sweep — salinity, temperature bands, feed and harvest intervals, first-harvest day — and every cadence can be overridden per jar.",
        "Honesty rules, the OpenReef way: a clock with no stamp reads 'unknown', never a guess; a chore is due when its interval has elapsed since it was last done; temperature advice never moves a clock.",
      ],
    },
    {
      heading: "The rig, the journal, and what it learns",
      paragraphs: [
        "Rotifers live in an inverted-bottle cone rig drawn live on the tab (air on, purge, harvest, refill), copepods in their tub. Each daily tap logs a sign — the water's tint, an egg ratio, the temperature — and the journal turns that into learned cadences: how fast this jar clears its feed, how long a run lasts before it wants a restart, what it yields per day. When the learned number disagrees with the preset, an Apply chip offers to re-time the chore.",
        "Harvested rotifers go to their own fridge bottle — never the brine's live vessel — and an optional DHA soak sits between harvest and feeding, because the standard rotifer feed carries almost no DHA and enrichment is what makes rotifers a complete food.",
      ],
      list: [
        "Split into B: one jar first, a backup seeded from the restart when a crash would otherwise zero you",
        "Heat guard: the culture's own temperature tiers, watched against the cooling forecast — a UK heatwave is how the last culture died",
        "Actionable pushes — Harvested / Fed / Restarted / Later — straight from the notification",
        "A shareable culture card, generation and lineage included",
      ],
    },
    {
      heading: "What 'due' looks like",
      paragraphs: ["Three chores due on a real morning:"],
      snippet: `rotifers A · day 6 of 14 · 4 L at 27 ppt
  harvest — the cone's own clock says now
  restart — sign: cloudy, clearing slow
tigriopus B · day 20 · feed (every 3 days)
room 27.6 °C — warm for the pods, watch it
rotifer bottle · 600 ml · fresh, ~82 h left`,
    },
  ],
  limits: [
    "Presets are research-backed hobbyist numbers, not a hatchery manual — your jar's learned cadences will beat them within a few weeks, which is the point.",
    "The DHA soak is a process step you do; OpenReef times it, debits the enrichment bottle, and won't let you bottle a crop mid-soak — it can't see the water.",
    "The heat guard needs the cooling headroom forecast to be configured; without a weather entity it falls back to live room temperature only.",
    "Logging is deliberately basic — a daily tap and a tint. The value is in doing it every day, not in the fields.",
  ],
  faq: [
    {
      q: "I've never cultured rotifers. Where do I start?",
      a: "The tab opens with an arrival walkthrough for a virgin rack: seed one jar from the starter bottle, feed to a light-green tint, first harvest around day six. One jar first — the Split into B action appears when you're ready for a backup.",
    },
    {
      q: "Why does it insist on restarting a healthy-looking jar?",
      a: "Because rotifer cultures crash from the inside: ciliates build up on a fortnight timescale and the crash arrives at week four looking sudden. The restart-before-it-crashes rule is the whole method; the journal will shorten or lengthen it from your own run lengths.",
    },
    {
      q: "Can this feed my tank automatically?",
      a: "The harvest goes to a fridge bottle that the food shelf and feed timeline know about, so the bottle's doses show on today's strip. Pumping live rotifers is hardware-track work; today the feed-out is a hand dose with a reminder.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
