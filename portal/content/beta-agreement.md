# OpenReef Beta Tester Agreement

Last updated: 2026-08-04 · Version: `2026-08-04`

> **Draft — not yet legal advice and not yet final.** Reece should read the
> checklist at the end before this is treated as published wording. It is
> written to be *read*, because a wall of legalese that testers skip protects
> nobody.

Controller / provider placeholder:

```text
[Legal entity or sole trader name]
[Contact email]
[Address, if required]
```

---

## The short version

OpenReef is unfinished software that can switch your reef equipment on and off.
You are still the person responsible for your tank. Keep your own safety nets.
Don't arm anything you couldn't afford to lose. Tell us when it goes wrong, and
we'll fix it and tell you.

If you're not comfortable with that, the honest answer is that the beta isn't
for you yet — and that's fine.

---

## 1. What the beta is

OpenReef Core is in active development. You are getting it early, free of
charge, in exchange for nothing except your willingness to tell us when it
misbehaves.

That means:

- **Things will break.** Features will change, be renamed, or be removed.
- **Data may be lost.** Config formats change between releases. Keep backups.
- **Releases are frequent** and not all of them are as well tested as they
  should be.
- **Support is one person.** Reece reads everything, but there is no SLA and no
  guaranteed response time.

Current known limits are listed in `OPENREEF_BETA_LIMITATIONS.md`, which is
updated as the beta moves.

## 2. Safety — the part that actually matters

**OpenReef can control equipment that keeps living animals alive.** Heaters,
return pumps, ATO, dosers, wavemakers. Getting that wrong kills livestock.

By taking part you accept that:

- **Your tank remains your responsibility.** OpenReef is a tool you operate,
  not a service that takes over.
- **You will keep independent failsafes.** Mechanical thermostats, float
  switches, hardware limits — the things that work when software doesn't.
  OpenReef's own documentation tells you to; this is us saying it again.
- **You will not arm equipment you are not prepared to lose control of.**
  Arming is deliberate, per device, and reversible. It is opt-in for a reason.
- **You will not rely on OpenReef as your only alerting.** It cannot warn you
  if Home Assistant is down, the machine is off, or your network has dropped.
- **You will test before you trust.** The smoke tests exist so you can prove
  behaviour on your own system before it matters.

If OpenReef does something you did not expect with equipment, **deal with the
tank first** and report it afterwards. There is a "Something unsafe" option in
the feedback button that goes straight to the top of the pile.

## 3. No warranty

The beta software is provided **as is** and **as available**, without warranty
of any kind — express, implied or statutory — including any implied warranties
of merchantability, fitness for a particular purpose, accuracy, or
uninterrupted operation.

We do not warrant that the software will be error-free, that it will protect
your livestock, or that any defect will be corrected.

## 4. Liability

To the fullest extent permitted by law, we are not liable for any loss or
damage arising from your use of the beta — including loss of livestock, loss of
equipment, property damage, loss of data, or any indirect or consequential
loss.

**Nothing in this agreement limits or excludes liability for death or personal
injury caused by negligence, for fraud or fraudulent misrepresentation, or for
anything else that cannot lawfully be limited or excluded.** If you are a
consumer, your statutory rights are unaffected.

Because the software is provided free of charge and its source is public, you
are able — and encouraged — to inspect exactly what it does before you let it
touch a socket.

## 5. Your feedback

When you send feedback you give us permission to use it to improve OpenReef,
including in public release notes, documentation and the website — but **never
attributed to you by name without asking first**, and never including your
support summary or log contents.

You keep ownership of anything you write. You are not obliged to send feedback
at all, and you can ask for anything you've sent to be deleted (see the
[privacy notice](/privacy)).

## 6. Confidentiality — there isn't any

OpenReef is open source and developed in public. **You are free to talk about
the beta**, post screenshots, write about it, and show it to people. There is no
NDA and no embargo.

The only ask: if you're going to write publicly about something being broken,
consider telling us first so the fix and the post can land together.

## 7. Data

What we collect, why, and how to get rid of it is in the
[privacy notice](/privacy). The short version: your feedback, your versions,
and — only if you leave the toggles on — your support summary and the OpenReef
lines from your Home Assistant log. No sensor readings, no camera images, no
continuous monitoring of your tank.

## 8. Ending it

**You can leave at any time**, for any reason, without explaining. In the panel:
**Ask Reece → Sharing → Leave the beta**. That stops all sending immediately.

We can also end your participation at any time — most likely because the beta
itself has ended.

Removing the integration removes it entirely; nothing is left running.

## 9. Changes

This agreement will change as the beta does. The version is at the top. If it
changes materially you will be asked to accept the new version before sending
anything further.

## 10. Governing law

England and Wales.

---

## Before publishing — Reece's checklist

- [ ] Decide the legal entity: sole trader vs limited company, and put the real
      name and contact details in the placeholder above.
- [ ] Confirm the liability wording is proportionate for **free** software with
      public source, ideally with someone qualified. The livestock-loss scenario
      is the one to ask about specifically.
- [ ] Confirm the consumer-rights carve-out in §4 is worded correctly for UK
      consumer law.
- [ ] Decide whether kit/hardware testers need different terms — physical goods
      change the picture significantly.
- [ ] Cross-check §2 against the current `OPENREEF_BETA_LIMITATIONS.md` so the
      two never contradict each other.
- [ ] Set the version string convention and stick to it, so acceptance records
      remain meaningful.
