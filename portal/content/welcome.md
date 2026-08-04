# Welcome to the OpenReef beta

You're one of a handful of people running this. That's not a marketing line —
you can count the testers on your fingers, and Reece reads every word that
comes in. What you notice in the next few weeks will shape what this becomes.

This page is the two-minute version of how to get value out of the beta (and
give some back) without risking your tank.

---

## The one rule

**OpenReef never controls anything you haven't mapped *and* armed yourself.**

Mapping tells it which Home Assistant entity a thing is. Arming is a separate,
deliberate switch that says "you may actually turn this on and off". Until you
arm something, OpenReef watches and advises — it touches nothing.

So the safe way in is the order below: watch first, control later.

## Your first hour

1. **Run the setup wizard.** It suggests entity mappings from what it can see
   in your Home Assistant; correct anything it guessed wrong. If your probes
   come from an Apex, pick the Apex path — that's the setup it's best at.
2. **Map your sensors, arm nothing.** Get temperature, salinity, pH showing
   real numbers in Live Stats. Wrong numbers here are exactly the kind of bug
   worth reporting.
3. **Open Trust Check** (Mission Control). It's OpenReef grading its own
   trustworthiness on your system — sensors reporting, mappings sane, alerts
   deliverable. Chase it to green *before* you trust anything else it says.
   Getting stuck here is worth a report, not an evening of frustration.
4. **Send a test notification** (Settings) so you know alerts actually reach
   your phone before the night you need one.

## Your first week

- **Live with it read-only.** Watch Live Stats and the health ring against
  what your own eyes and your existing controller say. Disagreements are
  gold — report them.
- **Then arm one boring thing.** A light, a pump you can afford to have
  misbehave — not the heater, not the ATO. Watch it through a Feed cycle or
  two.
- **Escalate at your own pace.** Heater and ATO last, after the failsafe
  warnings have told you what they want, and only with your independent
  protections in place (mechanical thermostat, float switch). The beta
  agreement means what it says: your tank stays yours.

## Telling Reece things

The **Ask Reece** button (bottom-right, every tab) is the whole feedback
system. What makes it worth using over a message:

- **Your diagnostics ride along automatically** — version, tab, support
  summary, the OpenReef lines from your log — so "it broke" is enough; the
  context comes with it. You can preview exactly what gets sent, and the
  **Sharing** tab turns any of it off.
- **"Something unsafe" jumps the queue.** Equipment did something you didn't
  expect? Sort the tank first, then use that button — it lands at the top of
  the pile as a blocker.
- **Half-formed counts.** "This felt confusing" and "this was nice" are both
  real feedback. Nice-thing reports genuinely matter: they mark what must not
  get broken.
- **You'll hear back.** When something you sent gets fixed (or won't be),
  the reply arrives in the panel with a notification. The dot on the button
  means there's something for you.

While enrolled, your install also checks in every half hour with setup counts
and its Trust Check status — so if you get stuck, Reece notices without you
having to say so. It's counts and a status word, never readings or names; the
[privacy notice](/privacy) has the full list, and leaving the beta stops all
of it instantly.

## What's rough right now

The honest list lives in `OPENREEF_BETA_LIMITATIONS.md` in the repo and moves
with each release. Headlines: automated dosing and water changes exist but are
young — treat them as advisory until you've watched them; camera intelligence
is early; releases are frequent, so **update often and hard-refresh the
browser after each one** (Ctrl+Shift+R — it's panel code).

## Leaving

Any time, no explanation: **Ask Reece → Sharing → Leave the beta**. Sending
stops instantly; ask and anything already sent gets deleted. No hard feelings
— an honest "this isn't for me yet" is also data.

---

Thanks for being here this early. Now go feed your fish. 🐟
