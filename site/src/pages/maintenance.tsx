import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "maintenance",
  h1: "Maintenance Reminders",
  lede: "Reef maintenance isn't hard — it's relentless. Thirteen recurring jobs on thirteen different clocks, and forgetting the boring one is how tanks quietly decline. OpenReef keeps the calendar, nags exactly once a day, and logs what actually happened.",
  buddyLine: "Your RO/DI filters were due in March. It is no longer March.",
  buddyPose: "facepalm",
  img: "/demos/maintenance.png",
  imgAlt: "OpenReef maintenance tab in Home Assistant",
  sections: [
    {
      heading: "The whole routine, pre-loaded",
      paragraphs: [
        "Thirteen default tasks cover the standard reef routine, each on a sensible cadence you can change (1–365 days), plus your own custom tasks on top:",
      ],
      list: [
        "Every few days — glass cleaning (3), water change, skimmer cup, filter socks, detritus blow (7)",
        "Fortnightly — dosing/kalk reservoir refill, ATO reservoir check (14)",
        "Monthly — carbon, GFO, pH probe calibration, salinity calibration (30)",
        "The long clocks nobody remembers — pump descale (90), RO/DI filters (180)",
      ],
    },
    {
      heading: "Reminders that respect your phone",
      paragraphs: [
        "The due evaluator runs in the backend, in lockstep with the panel — so reminders fire even when no browser is open anywhere. Once a day, at a time you choose, due and overdue tasks land as one Home Assistant notification plus an optional push to your phone through the companion app. One daily digest is the anti-spam control: you'll never get thirteen separate pings.",
        "Tasks can run on a simple cadence or a fixed day — water change every Monday, not 'every 7 days drifting through the week'. Snooze a task and it stays quiet; skip one and the clock restarts honestly.",
      ],
    },
    {
      heading: "A logbook that fills itself in",
      paragraphs: [
        "Completions are records, not checkmarks: when you log a water change you can log the litres, and your automatic water changes log themselves — tagged by source, so the maintenance history distinguishes 'the AWC did 25 L on Thursday' from 'I did a 30 L bucket day'. Same-day automatic runs merge into one entry, so a trickle schedule doesn't flood the history. Up to 200 completions are kept per task — a couple of years of honest reefkeeping, queryable.",
      ],
      snippet: `water change · every Mon 09:00
  ✓ yesterday   25.0 L   (awc, automatic)
  ✓ 8 days ago  25.0 L   (awc, automatic)
  ✓ 15 days ago 30.0 L   "manual bucket day"
clean skimmer cup · every 14 days
  ⚠ due — last done 15 days ago`,
    },
  ],
  limits: [
    "Reminders are free and stay free: Home Assistant notifications and companion-app push — no subscription between you and your own task list, which is more than can be said for most aquarium reminder apps.",
    "One digest a day by design. If you want a second nag, that's what an overdue state on the Pulse wall is for.",
    "OpenReef logs what you tell it (and what the AWC does) — it can't see that you actually rinsed the skimmer cup.",
    "The due evaluator and the panel share one definition of 'due' — deliberately, so the reminder on your phone and the badge on the tab can never disagree.",
  ],
  faq: [
    {
      q: "Can I add my own tasks?",
      a: "Yes — custom tasks sit alongside the defaults with the same cadence, fixed-day, snooze and history machinery. The thirteen built-ins are a starting point, not a cage.",
    },
    {
      q: "What does 'fixed day' mean vs a cadence?",
      a: "A 7-day cadence means 'a week after whenever you last did it' — which drifts. A fixed day means water change is Monday, full stop. Both are supported per task; use whichever matches how you actually live.",
    },
    {
      q: "Do automatic water changes tick the box?",
      a: "Yes. Every AWC run logs a completion against the water-change task with its real litres, tagged as automatic — so the reminder never nags you for a change the machine already did.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
