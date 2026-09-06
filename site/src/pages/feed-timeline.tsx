import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "feed-timeline",
  h1: "The Feed Timeline",
  lede: "Every mouthful that goes into the tank today — pumped, poured, or netted from a culture — on one 24-hour strip, with planned slots that fill in as they happen. One list, computed once, read by the NPS tab, the Feeding hub and the Pulse wall alike.",
  buddyLine: "Every mouthful today, on one strip. Pumped, poured, or netted — I don't care how it got in.",
  buddyPose: "point",
  img: "/demos/feed-timeline.png",
  imgAlt: "OpenReef Feeding hub — today's feeds on the timeline strip",
  demoLabel: "Open the Feeding hub in the demo",
  sections: [
    {
      heading: "One strip, three lanes",
      paragraphs: [
        "Pump doses on one lane, hand feeds on another, the system's own events — the water change, the feed truce — underneath. A hollow mark is planned, solid is done, amber is late, red is missed, dotted is skipped. Tap any mark and its dose card opens: what, how much, from which bottle, and the buttons to log it, skip it or undo it.",
        "The strip is backend-computed. The panel never re-derives it, so the wall in the tank room and the tab on your phone can never disagree about whether the sun corals have been fed.",
      ],
    },
    {
      heading: "Feeds that are filed, not floating",
      paragraphs: [
        "A hand-fed bottle carries a plan: a dose size, and either a times-a-day count inside a feeding window (three feeds between 11:00 and 21:00 become 11:00, 16:00, 21:00) or an hours cadence with an anchor. Log a feed and it files itself into the nearest planned slot; log one late and it lands where it actually happened. Hours-cadence feeds go missed when the next one falls due; day-cadence feeds stay late until midnight. Every done feed carries a ten-minute undo — a tombstone, not a deletion, so the day's record stays honest.",
      ],
      snippet: `today · 7 feeds
  ⚙ phyto pump      11:00 ✓   15:00 ✓   19:00 ○
  ✋ amino acids     any time · due now
  ✋ coral powder    any time · due now
  ✋ live brine ×2   11:00–21:00 window
  ≈ water change    09:00 ✓  ·  truce: UV 2 h · skimmer 45 min`,
    },
    {
      heading: "The truce, drawn where it happens",
      paragraphs: [
        "When a pumped food dose pauses the UV, the ozone or the skimmer, those pauses appear as thin bands under the system lane: the ones that ran (from the truce's own history), the one running now, and the ones today's remaining pump doses will start. You can see, at a glance, that the skimmer will be off for 45 minutes after the seven o'clock feed — before it happens.",
      ],
    },
  ],
  limits: [
    "Hand feeds do not engage the feed truce, by design — you're at the tank, you decide whether the skimmer comes off.",
    "The strip shows today. History lives in the maintenance completions and the shelf's usage log; the strip is for the day in front of you.",
    "An unplanned feed shows as a 'ghost' mark: logged and counted, but it wasn't on the plan, and the strip says so rather than quietly adopting it.",
  ],
  faq: [
    {
      q: "Does this replace my feeding reminders?",
      a: "It's where they come from. The same plan that draws the slots fires the reminders — one daily digest for the chores, and the feed pushes at the hour that matters — so a slot on the strip and a nag on your phone are one thing, never two.",
    },
    {
      q: "What if I feed at a different time than planned?",
      a: "Log it with the time it happened and it files itself: into the nearest slot if it's close, as a late mark if it isn't. The plan bends to what you did; it doesn't pretend you did what it planned.",
    },
    {
      q: "Can the wall show it?",
      a: "Yes — Reef Pulse carries a compact copy of today's strip on its Today tile, read from the same backend list, so the tank room sees what's been fed without anyone opening the app.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
