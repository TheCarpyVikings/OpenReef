import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "mixing-station",
  h1: "The Saltwater Mixing Station",
  lede: "Every water change starts with a batch someone mixed, heated, tested and remembered. OpenReef makes the batch a first-class object: a guided workflow from RODI to storage, a contents ledger that is the truth, and a water change that refuses to run on salt water nobody can vouch for.",
  buddyLine: "Salt water you can vouch for: tested, dated, and counted to the litre.",
  buddyPose: "chilled",
  img: "/demos/mixing.png",
  imgAlt: "OpenReef Mixing Station tab in Home Assistant",
  demoLabel: "Open Water → Mixing Station in the demo",
  sections: [
    {
      heading: "A batch is a state machine, not a bucket",
      paragraphs: [
        "Dual-vessel (RODI store plus mix vessel) or single-vessel, the station walks a batch through the stages that are actually a machine's job: heating (before the salt goes in — every brand asks for it), salting and mixing on the brand's timer, the salinity test that unlocks Ready, then Storing with periodic circulation bursts so the water doesn't stagnate. Fills and transfers are your hands and a ball valve; the station times, confirms and accounts for them rather than pretending to switch what it can't.",
        "The mix clock is a stamped timestamp evaluated on read, the hatchery pattern — so a settings edit can never rewrite a running batch.",
      ],
    },
    {
      heading: "Maths you can check on the bag",
      paragraphs: [
        "A brand table of the popular salts carries each one's published grams per litre, so the dose guide gives you the full-batch figure, the top-up for whatever's already standing in the vessel, and a live what-if as you type a target. Log the refractometer reading and the correction maths tells you the grams or the RODI to hit 35 ppt exactly. A custom brand with no g/L gets no dose figure — a number OpenReef can't source is a number it won't show.",
      ],
      snippet: `NYOS · 35.0 ppt target · 50 L vessel
  full batch:      1 950 g   (39 g/L)
  top-up to full:    234 g   (6 L standing at 35.1)
  what-if 34 ppt → add 1.4 L RODI
salt stock: 3.1 kg of a 10 kg bucket — 1 more batch`,
    },
    {
      heading: "The ledger is the truth",
      paragraphs: [
        "Levels are stored anchors moved only by confirmed events — fill done, transfer done, batch used — and labelled 'estimated' until you bind real level sensors. Everything that touches the water moves the ledger: a scheduled water change debits the vessel; a hand-logged change in Maintenance debits it too; the ATO's top-off draws down the RODI store; the RODI unit meters its litres since the last reset so each filter stage earns its own replacement clock; the salt stock counts down by the batch.",
        "And it vouches: the automatic water change warns, or refuses, when there isn't a tested batch of sufficient volume in storage. That's the Trust Moat applied to the part of the hobby everyone does on faith.",
      ],
    },
  ],
  limits: [
    "Level readings are estimates until level entities are bound — the tab says so on every card, and hardware for it is on the DIY track.",
    "Brand doses are the manufacturers' published guides and are clearly approximate; your refractometer and the correction step are what make the batch exact.",
    "RODI-to-mix transfer is gravity and a valve in the reference setup — OpenReef times and confirms it, it doesn't pump it.",
    "Pump calibration is a ceremony: prep, run, stop, then read — the flush seconds are discounted everywhere so a long line can't fake a fast pump.",
  ],
  faq: [
    {
      q: "I mix in a single container. Is that supported?",
      a: "Yes — single-vessel mode skips the transfer stage, draws one vessel in the diagram, and lets each batch be saltwater or plain RODI (for top-off), so one bin can serve both jobs.",
    },
    {
      q: "What does the AWC do if I forgot to mix?",
      a: "It tells you, before it runs: no tested batch of the required volume in storage means the scheduled change warns or blocks depending on the guard you chose. A water change from stale or untested water is exactly the failure this exists to prevent.",
    },
    {
      q: "Does it track my RODI filters?",
      a: "Each stage — sediment, carbon, membrane, DI — gets a rated-litres clock fed by the unit's metered draw, so 'change the DI' arrives as litres processed, not a guess at months.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
