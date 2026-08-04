# OpenReef Beta — Privacy Notice

Last updated: 2026-08-04 · Version: `2026-08-04`

> **Draft — not yet legal advice and not yet final.** Reece should complete the
> checklist at the end before this is treated as published wording.

Controller placeholder:

```text
[Legal entity or sole trader name]
[Privacy contact email]
[Address, if required]
[ICO registration number, if required]
```

---

## The short version

OpenReef runs on **your** Home Assistant, on **your** hardware. It is not a
cloud service and it does not stream your tank anywhere.

Two things leave your machine, and only after you enrol with an invite code:

1. **A check-in every 30 minutes** — counts and a status word (setup done?
   trust check ok? how many probes mapped?) so we notice when someone is stuck.
   Never readings, never names of anything.
2. **Feedback, when you press send** — your message plus enough context to fix
   the problem. The support summary that rides along is shown to you verbatim
   before sending; the optional log lines are described there and filtered to
   OpenReef's own entries.

We never collect your sensor readings, your camera images, or your Home
Assistant credentials. Leaving the beta stops both kinds of sending instantly.

---

## Who this applies to

People taking part in the OpenReef private beta, and people who join the
waiting list at openreef.co.uk.

## What we collect

### If you join the waiting list

- Your email address
- Which options you ticked (manual, beta seat, kit waitlist)
- When you signed up

### If you become a tester

- The name and email you gave us
- Your invite code, and a random install identifier generated on your machine
- Your OpenReef and Home Assistant versions
- When your install last checked in

### When your install checks in (every 30 minutes)

- Whether you have completed setup
- Your Trust Check status (`ok` / `warning` / `critical`), and when it was last run
- Counts only: how many sensors are enabled, mapped, and how much equipment is
  mapped or armed

**Counts and a status word — not the readings themselves, not entity names, not
what any of it is called.** This exists so that someone who gets stuck in setup
and gives up is noticed and offered help, instead of silently disappearing.

### When you send feedback

- What you wrote, and what kind of thing you said it was
- Optionally, what you were trying to do
- Which panel tab you were on, your OpenReef and Home Assistant versions, and
  your browser's user-agent string

### Only if you leave the Sharing toggles on

- **Your support summary** — the same text Settings → System Check has always
  let you copy by hand. It includes your tank name and owner name as you typed
  them, which Home Assistant entities you have mapped, which equipment is
  armed, your Trust Check and health score breakdown, and recent activity.
- **OpenReef log lines** — the last 80 lines of your Home Assistant log that
  mention OpenReef. Lines from other integrations are never included.

Both are optional, both default on, and both can be turned off at any time
under **Ask Reece → Sharing**. Turning one off empties the field — it isn't
merely hidden.

## What we never collect

- Sensor readings, trends, or history
- Camera images, clips, or timelapse frames
- Home Assistant long-lived access tokens, passwords, or API keys
- Anything from other integrations on your Home Assistant
- Your location, or any continuous monitoring of your tank

Everything sent outbound passes through an automatic filter that strips
anything resembling an API key, bearer token, password or access token —
including from your log lines and from text you typed yourself.

## Why we use it, and our lawful basis

| What | Why | Lawful basis |
|---|---|---|
| Waiting-list email | To tell you when the manual or a beta seat is ready | Consent |
| Tester name, email, versions | To run the beta and know who reported what | Legitimate interests |
| Check-in and activation data | To notice when someone is stuck and offer help | Legitimate interests |
| Your feedback | To fix bugs and decide what to build | Legitimate interests |
| Support summary and log lines | To diagnose your specific problem | Consent (the Sharing toggles) |

Where we rely on legitimate interests, the interest is running a small private
beta well enough to make the software safe. You can object at any time — see
**Your rights**.

## Who else sees it

- **Reece.** Realistically, only Reece. This is a one-person project.
- **Supabase** — hosts the database. Processor.
- **Vercel** — hosts the portal and the website. Processor.

We do not sell anything, share anything with advertisers, or use any of this
for marketing beyond the waiting-list email you asked for.

Your feedback may inform public release notes — but **never attributed to you
by name without asking first**, and never quoting your support summary or logs.

## International transfers

Depends on the hosting regions selected — see the checklist below, which is
not yet complete.

```text
[Supabase project region: ...]
[Vercel deployment region: ...]
[Transfer mechanism relied on, if outside the UK/EEA: ...]
```

## How long we keep it

Proposed, and subject to the checklist below:

| Data | Retention |
|---|---|
| Waiting-list emails | Until the beta ends, you ask, or 24 months — whichever is first |
| Tester records | Duration of the beta, then 12 months |
| Feedback you wrote | Duration of the beta, then 12 months — it's the record of why things changed |
| **Support summaries and log lines** | **Deleted 90 days after the item is closed** |

Support summaries and logs get the shortest life on purpose: they are the most
detailed thing we hold about your setup, and their usefulness ends when the bug
is fixed.

## Your rights

You can ask to **see**, **correct**, **delete**, or **receive a copy of**
anything we hold about you, and you can **object** to processing based on
legitimate interests. Where we rely on consent, you can **withdraw it** — the
Sharing toggles do exactly that, immediately.

There is no form. Email the address at the top, or send it through the feedback
button, and it gets done.

**Leaving the beta** (Ask Reece → Sharing → Leave the beta) stops all sending
immediately. It does not delete what was already sent — ask, and it will be.

If you're unhappy with how we've handled your data you can complain to the
Information Commissioner's Office (ico.org.uk).

## Security

- Your install talks to the portal over HTTPS, authenticated with a token
  generated for you. Only its hash is stored, never the token itself.
- Revoking a tester clears that hash, so the install stops being able to send
  on its very next request.
- The database denies all public access; every read and write goes through
  server-side code behind an owner-email allowlist.
- Feedback is append-only — even the owner cannot rewrite what you wrote.

No system is perfect, and this one is maintained by one person. That's part of
what you're accepting by taking part.

## Cookies

The portal is owner-only and sets sign-in cookies only. The marketing site sets
no tracking cookies and runs no analytics.

## Changes

The version is at the top. Material changes will be announced through the panel
before they take effect.

---

## Before publishing — Reece's checklist

- [ ] Decide the legal entity and fill in the controller block.
- [ ] Check whether ICO registration is required (it usually is for a UK
      controller processing personal data, and it is inexpensive).
- [ ] Record the Supabase and Vercel regions and complete the transfers
      section. If either is outside the UK/EEA, identify the mechanism relied
      on.
- [ ] Accept or change the proposed retention periods, then implement the
      90-day support-summary deletion — it is a claim, and claims have to be
      true.
- [ ] Confirm the legitimate-interests basis is right for check-in data, or
      move it under consent alongside the Sharing toggles.
- [ ] Add a link to this notice from openreef.co.uk, not just the portal.
- [ ] Re-read once kits or hardware ship — physical goods and payments change
      this materially.
