import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "icp-import",
  h1: "The ICP Importer",
  lede: "An ICP report is forty-plus numbers in a PDF that most reefers read once, wince at, and file forever. OpenReef turns it into trends, flags — and a calibration check on your own test kits.",
  buddyLine: "Your test kit and your lab disagree by half a dKH. I'll tell you which one to stop trusting.",
  buddyPose: "point",
  img: "/demos/icp.png",
  imgAlt: "OpenReef ICP import tab in Home Assistant",
  sections: [
    {
      heading: "From lab file to tank data",
      paragraphs: [
        "Drop in a Triton CSV or an ATI PDF — or point the generic mapper at any lab's tabular export and save the mapping as a template for next quarter. The file is parsed in your browser, then everything that matters is re-derived on the backend: every lab label is resolved against 58 canonical elements (German aliases included — Alkalinität resolves just fine), below-detection markers are recognised rather than stored as zeros, and every status flag is recomputed against reef ranges instead of trusting the lab's traffic lights.",
        "Units are normalised per element, which is the unglamorous feature that matters most. Silicon and phosphorus arrive from different labs in mg/L or µg/L — mix those up and you're wrong by a factor of a thousand. OpenReef checks the unit on every element, every import.",
      ],
    },
    {
      heading: "One story, not two",
      paragraphs: [
        "The six parameters you also test at home — alkalinity, calcium, magnesium, nitrate, phosphate, salinity — don't get their own island. They fold into your ordinary reading history, tagged with their source lab, so the reef-health score, the trend graphs and the dosing advisor consume them with zero special cases. Your quarterly lab data and your Tuesday-night test kit finally plot on the same line.",
        "The RO/DI sample bundled with most kits is parsed and stored too — but never folded into tank trends. Your top-up water is not your tank.",
      ],
    },
    {
      heading: "The lie detector",
      paragraphs: [
        "The quiet killer feature: drift-check. When a report lands, OpenReef compares the lab's core values against your own recent test-kit trend. Agreement means your kits are telling the truth. Divergence gets flagged — and that flag is usually worth more than the report itself, because you dose off your kits fifty weeks a year:",
      ],
      snippet: `report.pdf → 58-element normalise pass
  Si   120 µg/L   unit-checked (the 1000× trap)
  I    0.043 ppm  low → flagged
  Ca   421 ppm    → folded into trends (ICP:ATI)
  drift: your kit alk 8.4 · lab 7.9 dKH
         → recalibrate the kit, not the reef`,
    },
  ],
  limits: [
    "The Triton and ATI adapters were built against published report formats and are still being tuned against real-world files in beta — a report that fails to parse is genuinely useful, send it in.",
    "All 58 elements are stored and flagged; today the core six drive trends and dosing, and trace-element scoring is on the roadmap.",
    "An ICP result is a snapshot of the day you sampled — often weeks old by the time it lands. OpenReef treats it as an audit and calibration check, never a live driver of automation.",
  ],
  faq: [
    {
      q: "Which labs work today?",
      a: "Triton (CSV) and ATI (PDF) have dedicated adapters. Anything else with a tabular export goes through the generic mapper, and your column mapping is saved as a template so the next report from that lab is one click.",
    },
    {
      q: "Does the ICP overwrite my test-kit history?",
      a: "No. Lab values land as ordinary readings tagged with the lab as their source, alongside your kit results — and drift-check compares the two rather than letting one silently replace the other.",
    },
    {
      q: "I have an Apex Trident — why would I need ICP import too?",
      a: "They answer different questions. The Trident measures three parameters several times a day; an ICP measures fifty-odd once a quarter, including things nothing on your tank can see — iodine, trace metals, contamination. OpenReef's job is making both land in one history instead of two apps.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
