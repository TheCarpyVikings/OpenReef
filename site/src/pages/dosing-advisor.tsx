import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "dosing-advisor",
  h1: "The Dosing Advisor",
  lede: "Alkalinity, calcium and magnesium consumption worked out from the tests you already do — with projections, and dose suggestions in plain English. Advisory only, always.",
  buddyLine: "The maths is free. Trident reagents are the printer ink of the sea.",
  buddyPose: "smug",
  img: "/demos/dosing.png",
  imgAlt: "OpenReef Dosing Advisor tab in Home Assistant",
  sections: [
    {
      heading: "Consumption, not snapshots",
      paragraphs: [
        "A single test tells you where your tank is. A trend tells you where it's going — and how fast. The Dosing Advisor turns your test history into daily consumption rates for alk, calcium and magnesium, then projects forward: at this rate, when do you drift out of range?",
        "That's the question that actually matters, and it's the one most reefers answer with a shrug and a slightly bigger dose.",
      ],
    },
    {
      heading: "Feed it any tests",
      paragraphs: [
        "It doesn't care where the numbers come from — everything folds into one history:",
      ],
      list: [
        "Trident results, straight from Home Assistant",
        "Manual test kits, logged in the panel",
        "ICP reports — Triton CSV and ATI PDF import supported",
      ],
    },
    {
      heading: "Advice you can audit",
      paragraphs: [
        "No black box. Every suggestion states its working: the measured consumption rate, the projected date you leave your target range, the suggested change in ml/day, and when to re-test to confirm it landed. If the honest answer is \"not enough data yet\", it says that instead of guessing.",
        "It also understands two-part chemistry — including that alk and calcium doses want spacing, not a simultaneous dump.",
      ],
    },
  ],
  limits: [
    "It needs a real history — days to weeks of tests, not one measurement. Advice quality follows test quality.",
    "It suggests; you decide. OpenReef never adjusts a pump or switches an outlet you haven't mapped and armed yourself.",
    "Big corrections should be slow. If your numbers are far off, it will tell you to fix them gradually rather than chase a target overnight.",
  ],
  faq: [
    {
      q: "Does it dose automatically?",
      a: "No. It computes and explains; changing the dose is your call. Equipment control in OpenReef always requires you to map and arm the hardware yourself first.",
    },
    {
      q: "Does it replace my Trident?",
      a: "The opposite — it's the brain on top of it. The Trident gives you excellent data; the Advisor turns that data into decisions. It also works from manual tests if you don't own one.",
    },
    {
      q: "What does Apex Fusion not do here?",
      a: "Fusion shows you the graphs. It doesn't compute consumption, project when you'll leave range, or suggest a dose change — that maths is exactly the gap OpenReef fills.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
