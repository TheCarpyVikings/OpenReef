import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "nps-system",
  h1: "The Automated NPS System",
  lede: "Non-photosynthetic corals don't run on light — they run on logistics: live food, several times a day, forever, with the water exchanged to carry the waste back out. OpenReef turns that logistics problem into a schedule: the food shelf, the pumps, the brine hatchery, and the water exchange in one place.",
  buddyLine: "Sun corals eat like teenagers. I run the kitchen, the fridge, and the bin.",
  buddyPose: "smug",
  img: "/demos/nps.png",
  imgAlt: "OpenReef NPS tab — the feeding station diagram in Home Assistant",
  demoLabel: "Open Feeding → NPS in the demo",
  sections: [
    {
      heading: "The food shelf: every bottle, honestly counted",
      paragraphs: [
        "Register what you own — phyto, zooplankton blends, bacteria, aminos, two-part — and each bottle gets a live remaining ledger, an opened-shelf-life clock, and a usage history. From that history the shelf forecasts runway per bottle: dead-reckoned from what you actually logged, so a bottle with no history gets no forecast rather than a guess. Expiry is opt-in per product and fails closed: a perishable bottle with no opened date counts as expired, because food of unknown age is not food.",
        "A dosing pump can be bridged to a bottle, so every automatic dose debits the shelf the same way a hand dose does. The shelf knows when you're about to run out before you do.",
      ],
    },
    {
      heading: "Feeding creates waste — so the exchange is part of the plan",
      paragraphs: [
        "Live brine goes in with a line-flush chaser, and the chaser is usually bigger than the dose. Both went into the tank, so both must come back out: every brine feed accrues an owed drain that the water-change pumps pay back as a matched exchange, capped and reported rather than silently banked. The nutrient budget then holds the whole thing to account — a rough model of nitrogen and phosphorus load against what your water changes export, with a steady-state nitrate estimate and a warning when the tank is running too clean for corals that eat.",
        "After a food dose, the feed truce pauses what would eat the food first — UV, ozone, skimmer — on armed equipment only, and restores exactly what it paused, stamped, when the window ends.",
      ],
    },
    {
      heading: "The brine hatchery: every clock is real",
      paragraphs: [
        "Hatch, harvest, hold, enrich. Four egg-type presets, a hatch clock that adjusts its expectation to the room temperature, a fridge bottle with its own shelf life, cyst freshness from the date you opened the tin, and a species library that compiles which foods cover which mouths. The reminders land on your phone as actionable pushes — Hatched & loaded — at the hour that matters, not at 09:00 because that's when apps like to nag.",
      ],
      snippet: `hatchery 1 · premium cysts · 24 h clock
  14 h elapsed  ·  ~10 h to go  ·  27.6 °C → expect ~20.6 h
  next hatch: 09:26 tomorrow — keeps the chain unbroken
fridge bottle 180 ml · ~18 h of life left
shelf: amino acids 18 % — reorder`,
    },
  ],
  limits: [
    "The nutrient budget is a rough model — a load-versus-export estimate for making decisions, not a replacement for testing nitrate and phosphate.",
    "Runway forecasts need a few logged doses before they say anything; the first week of a new bottle reads 'no history yet' on purpose.",
    "The matched-drain exchange needs the AWC's drain pump; with no AWC hardware the owed litres are still counted and shown, so you can do the change by hand.",
    "Species plans compile particle-size coverage from a ten-species library; it's a starting recipe for what your corals need, not a guarantee they'll take it.",
  ],
  faq: [
    {
      q: "Do I need NPS corals to use any of this?",
      a: "No. The shelf, the hatchery and the feed timeline work for any tank that feeds live or bottled food. NPS corals are what make the full system — exchange, truce, budget — worth automating.",
    },
    {
      q: "What does 'fails closed' mean for expiry?",
      a: "If a product is marked perishable and you never recorded when you opened it, OpenReef treats it as expired rather than assuming it's fine. It's the same rule the dosing engine uses for reagent freshness: unknown age is not safe age.",
    },
    {
      q: "Does the feed truce switch things off behind my back?",
      a: "Only armed equipment with a truce profile you set (UV, ozone, skimmer), only after a food dose, and it restores exactly the entities it paused. Hand feeds deliberately don't trigger it — you're standing there; you decide.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
