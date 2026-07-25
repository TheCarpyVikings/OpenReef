import { useState } from "react";
import type { Tone } from "../reef";
import { buddyLine, POSE_EMOJI } from "../copy";

interface Props {
  section: string;
  tone: Tone;
  hasApex: boolean | null;
  score: number;
  konami?: boolean;
}

export default function Buddy({ section, tone, hasApex, score, konami }: Props) {
  const [dismissed, setDismissed] = useState(false);
  // Real pose art lives in public/avatar/ (copied from the HA panel); falls
  // back to the emoji placeholders if a file is ever missing.
  const [artOk, setArtOk] = useState(true);
  if (dismissed) {
    return (
      <button className="buddy-restore" onClick={() => setDismissed(false)} aria-label="Bring back the reef guide">
        🪸
      </button>
    );
  }

  let { pose, text } = buddyLine(section, tone, hasApex);
  if (konami) {
    pose = "celebrate";
    text =
      tone === "professional"
        ? "Konami code accepted. The corals are spawning. This is also in the changelog."
        : "You found the spawning ritual. Thirty years of cheat codes and THIS is the best use yet.";
  } else if (section === "sandbox") {
    if (score < 55) {
      pose = "facepalm";
      text =
        tone === "professional"
          ? "In production this state would have already alerted you — with the cause and the corrective dose."
          : "Right, that's enough — in the real product I'd have pinged your phone four sliders ago. Advisory only, mind: I never touch an outlet you haven't armed.";
    } else if (score < 75) {
      pose = "concerned";
    } else if (score >= 90) {
      pose = "chilled";
    }
  }

  return (
    <aside className="buddy" aria-live="polite">
      <div className="buddy-avatar" data-pose={pose}>
        {artOk ? (
          <img
            src={`/avatar/${pose}.png`}
            alt=""
            className="buddy-art"
            onError={() => setArtOk(false)}
          />
        ) : (
          POSE_EMOJI[pose]
        )}
      </div>
      <p className="buddy-text">{text}</p>
      <button className="buddy-dismiss" onClick={() => setDismissed(true)} aria-label="Dismiss the reef guide">
        ×
      </button>
    </aside>
  );
}
