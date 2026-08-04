import type { Tester } from "./types";

/*
 * Who needs a nudge.
 *
 * The research on beta programs is blunt about this: testers who stop using
 * the product and stop responding are the highest-risk signal, and integration
 * friction is a top reason people give up WITHOUT saying anything. With ten
 * testers, losing three quietly costs a third of the signal.
 *
 * WHY THE THRESHOLDS ARE SO TIGHT
 * The integration syncs every 30 minutes on its own timer, with no human
 * involved. So `last_seen_at` does not mean "when they last logged in" — it
 * means "when their Home Assistant last checked in". A day of silence is
 * therefore not someone being busy; it is an install that has been uninstalled,
 * disabled, or taken offline. That is a much stronger signal than beta tooling
 * normally gets, and it deserves a much shorter fuse than a login-based one.
 *
 * Pure and total: takes `now` rather than reading the clock, so it is
 * deterministic and can be reasoned about without running the app.
 */

export type AttentionLevel = "critical" | "warning" | "info";

export type Attention = {
  level: AttentionLevel;
  label: string;
  why: string;
};

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** Milliseconds since an ISO timestamp, or null when absent/unparseable. */
function since(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  return Number.isNaN(then) ? null : now - then;
}

/**
 * The single most important thing about this tester right now, or null if
 * they're fine. Deliberately returns ONE item: a list of five concerns per
 * person is a list nobody reads, and the top one is almost always the one to
 * act on.
 */
export function attentionFor(
  tester: Tester,
  feedbackCount: number,
  now: number = Date.now(),
): Attention | null {
  if (tester.status === "revoked" || tester.status === "paused") return null;

  const enrolledAgo = since(tester.enrolled_at, now);
  const seenAgo = since(tester.last_seen_at, now);
  const invitedAgo = since(tester.created_at, now);

  // Never redeemed the code. Either it never reached them, or the install
  // beat them. Three days is long enough that it isn't just a busy weekend.
  if (tester.status === "invited" || enrolledAgo === null) {
    if (invitedAgo !== null && invitedAgo > 3 * DAY) {
      return {
        level: "warning",
        label: "Never joined",
        why: "Invited but the code was never redeemed. Worth checking it arrived.",
      };
    }
    return null;
  }

  // Their install has stopped checking in. It syncs every 30 minutes by
  // itself, so this is not inattention — something is off.
  if (seenAgo === null || seenAgo > 3 * DAY) {
    return {
      level: "critical",
      label: "Install gone",
      why: "No check-in for days. Uninstalled, beta switched off, or Home Assistant is down.",
    };
  }
  if (seenAgo > DAY) {
    return {
      level: "warning",
      label: "Not checked in",
      why: "Silent for over a day, when it should report every 30 minutes.",
    };
  }

  // Reporting fine, but something in their tank is genuinely wrong. This
  // outranks engagement worries — they may be mid-problem and not have said.
  if (tester.trust_status === "critical") {
    return {
      level: "critical",
      label: "Trust check critical",
      why: "Their own Trust Check is reporting a critical problem.",
    };
  }

  // Installed it, syncing happily, never finished the wizard. This is the
  // classic silent-churn shape and the one worth reaching out about first.
  if (tester.setup_complete === false && enrolledAgo > 2 * DAY) {
    return {
      level: "critical",
      label: "Stuck in setup",
      why: "Enrolled over two days ago and still hasn't completed setup.",
    };
  }

  // Half-mapped probes: they started and stalled on the fiddly part.
  if (
    typeof tester.sensors_enabled === "number" &&
    typeof tester.sensors_mapped === "number" &&
    tester.sensors_enabled > 0 &&
    tester.sensors_mapped < tester.sensors_enabled &&
    enrolledAgo > 2 * DAY
  ) {
    return {
      level: "warning",
      label: "Probes unmapped",
      why: `Only ${tester.sensors_mapped} of ${tester.sensors_enabled} sensors mapped.`,
    };
  }

  // Set up, but never trusted it with a socket. They're watching, not using —
  // which means the feedback you're getting isn't about the risky parts.
  if (tester.equipment_armed === 0 && enrolledAgo > 7 * DAY) {
    return {
      level: "info",
      label: "Nothing armed",
      why: "A week in with no equipment armed — they're watching, not controlling.",
    };
  }

  // Working fine and using it, but has never said a word. Not a problem to
  // fix, a person to ask.
  if (feedbackCount === 0 && enrolledAgo > 14 * DAY) {
    return {
      level: "info",
      label: "Never sent feedback",
      why: "Two weeks in, everything running, and not a single report.",
    };
  }

  return null;
}

const RANK: Record<AttentionLevel, number> = { critical: 0, warning: 1, info: 2 };

/** Most urgent first. */
export function byUrgency(a: Attention, b: Attention): number {
  return RANK[a.level] - RANK[b.level];
}

export const LEVEL_TONE: Record<AttentionLevel, string> = {
  critical: "tone-danger",
  warning: "tone-work",
  info: "tone-seen",
};
