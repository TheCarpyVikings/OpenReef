# OpenReef DIY Manual

Welcome. This manual takes you from a blank starting point to a safe first
OpenReef setup, one calm step at a time. It is written for reef keepers who may
be completely new to Home Assistant, so no prior experience is assumed.

OpenReef runs inside Home Assistant. So the order is simple: get Home Assistant
running, install OpenReef, then point OpenReef at the reef sensors and equipment
that Home Assistant already knows about.

You do not need to finish this in one sitting, and you cannot break your tank by
reading data. Take your time, and stop whenever you like.

## What You Are Building

OpenReef is a Home Assistant-native reef controller and monitoring layer. Instead
of new proprietary hardware, it reuses things Home Assistant already sees —
sensors, switches, smart plugs, cameras, Apex/Trident entities, ESPHome devices,
and more.

The safest way to begin is read-only, and that is exactly where we start:

1. Install Home Assistant.
2. Install OpenReef.
3. Map sensors first.
4. Run Trust Check.
5. Add equipment control later, once you understand what each switch does.

There is no rush to automate anything. Please do not start by handing OpenReef
control of heaters, ATO pumps, return pumps, or wavemakers. Get comfortable
watching your tank first — control can always come later.

## Safety Rules

These keep your tank and your data safe. They are worth reading twice.

- Never paste Home Assistant tokens, passwords, API keys, or private network
  details into OpenReef.
- Only arm equipment you are happy for OpenReef to switch.
- Start with sensors before controls.
- Test every switch manually in Home Assistant before mapping it in OpenReef.
- Do not mark edge failsafes as reviewed until the actual relay/probe behaviour
  has been bench-tested.
- If anything feels confusing, leave the equipment disarmed. Disarmed is the safe
  default, and there is no penalty for staying there.

## The Short Version

Already have Home Assistant running and feeling confident? Here is the whole flow
at a glance:

1. Install HACS if it is not installed yet.
2. Add the OpenReef GitHub repository to HACS as a custom integration:
   `https://github.com/TheCarpyVikings/OpenReef`
3. Download OpenReef in HACS.
4. Restart Home Assistant.
5. Add OpenReef in **Settings -> Devices & services -> Add integration**.
6. Open **OpenReef** from the sidebar.
7. Complete setup using sensors first.
8. Run **Settings -> System Check -> Trust Check** inside OpenReef.

If you do not have Home Assistant yet, no problem — the next section walks you
through it.

## Choose Your Home Assistant Route

Home Assistant lists Home Assistant Operating System as the recommended
installation type for most users. It is the simplest route for OpenReef because
it supports managed updates, backups, add-ons, HACS, and the normal Home
Assistant UI.

Pick the row that sounds most like you. None of these choices are permanent — you
can change your mind later.

| Route | Best for | Pros | Watch-outs |
| --- | --- | --- | --- |
| Home Assistant OS in a VM | First test, cheapest start, existing PC/laptop | No new hardware needed, easy to reset, good for learning | The host computer must stay on; disable sleep |
| Home Assistant Green | Easiest dedicated appliance | Simple, quiet, low-admin | Costs more than using an existing computer |
| Raspberry Pi | Small dedicated DIY setup | Popular, compact, widely documented | Needs a good power supply and reliable storage |
| Mini PC / generic x86-64 | Strong long-term DIY controller | Reliable, fast, good for always-on use | Requires installing HA OS to dedicated hardware |
| Existing Home Assistant | Reef keeper already using HA | Fastest path to OpenReef | Make a backup before adding custom integrations |

For a first try, a Home Assistant OS VM is usually the easiest route, because you
can spin up a clean Home Assistant instance without touching your existing reef
setup.

Source links:

- Home Assistant installation overview:
  <https://www.home-assistant.io/installation/>
- Home Assistant OS on Linux VM:
  <https://www.home-assistant.io/installation/linux/>
- Home Assistant OS on Windows VM:
  <https://www.home-assistant.io/installation/windows/>
- Home Assistant OS on generic x86-64 hardware:
  <https://www.home-assistant.io/installation/generic-x86-64/>

> Screenshot to add: Home Assistant installation page with the route choices.
> Planned file: `docs/manual/screenshots/01-home-assistant-install-routes.png`

## Route A: Install Home Assistant OS In A VM

Choose this if you want the cheapest clean test and already have a computer you
can leave running.

Use the official Home Assistant VM guide for your operating system:

- Windows users: <https://www.home-assistant.io/installation/windows/>
- Linux users: <https://www.home-assistant.io/installation/linux/>

Home Assistant's Linux VM guide uses at least 2 vCPU and 2 GB RAM. For a smoother
OpenReef test, this is a comfortable starting point:

- 2 vCPU
- 4 GB RAM if your computer can spare it
- 32 GB disk or more
- Bridged network if available
- Sleep disabled on the host computer

After the VM boots, open Home Assistant in a browser. It is usually available at
one of these addresses:

- `http://homeassistant.local:8123`
- `http://<your-vm-ip-address>:8123`

Create your Home Assistant owner account and finish the first-run setup. That is
the hardest part done.

![First successful Home Assistant dashboard](docs/manual/screenshots/02-home-assistant-first-run.png)

## Route B: Use Home Assistant Green

Choose this if you want the simplest dedicated Home Assistant box.

Follow the Home Assistant Green setup instructions from Home Assistant. Once the
device is online, open Home Assistant in your browser, create your owner account,
and finish the first-run setup.

This route is a great fit for reef keepers who would rather not maintain a VM or
leave a normal computer running.

## Route C: Use A Raspberry Pi

Choose this if you want a small DIY Home Assistant device.

Use the official Home Assistant Raspberry Pi installation route from the
installation overview:

<https://www.home-assistant.io/installation/>

For a reef controller, use reliable power and storage. A weak power supply or
poor storage can cause odd behaviour that looks like software trouble but is not.

## Route D: Use A Mini PC Or Generic x86-64 Machine

Choose this if you want a stronger dedicated Home Assistant controller.

Use the official generic x86-64 guide:

<https://www.home-assistant.io/installation/generic-x86-64/>

This route is a solid choice for a permanent reef-control setup, especially if
you expect to add cameras, history, automations, and other Home Assistant
integrations later.

## Before Installing OpenReef

OpenReef shows its best self once Home Assistant already knows about your sensors
and equipment. So a little groundwork here pays off.

Examples of what Home Assistant might already see:

- A temperature probe shown as a Home Assistant sensor.
- pH, salinity, alkalinity, nitrate, phosphate, or other reef readings shown as
  Home Assistant sensors.
- Smart plugs or relays shown as Home Assistant switches.
- Cameras shown as Home Assistant cameras.
- Apex/Trident/HYDROS data shown in Home Assistant, if you already use those
  systems.

You do not need every sensor on day one. Starting small is genuinely the better
choice.

A good first setup is:

- Tank temperature sensor.
- Optional pH or salinity sensor.
- Optional camera.
- No equipment control yet.

If you already have Apex or Trident entities in Home Assistant, finish this
manual first, then continue with the
[Apex Beta Tester Guide](APEX_BETA_TESTER_GUIDE.md).

## Install HACS

During the private beta, OpenReef is installed through HACS.

HACS is the Home Assistant Community Store. It manages custom integrations and
community extensions — think of it as the place Home Assistant gets add-ons like
OpenReef.

Use the official HACS installation instructions:

<https://hacs.dev/docs/use/download/download/>

Follow the route for your Home Assistant install type. After the HACS files are
downloaded, restart Home Assistant.

Then finish setting up HACS inside Home Assistant:

1. Go to **Settings -> Devices & services**.
2. Select **Add integration**.
3. Search for **HACS**.
4. Select **HACS**.
5. Read and acknowledge the HACS warnings.
6. Follow the GitHub device-code login shown by Home Assistant.
7. Authorize HACS in GitHub.
8. Return to Home Assistant and finish the HACS setup.

HACS uses GitHub to download and update community repositories. If you do not
already have a GitHub account, you will need one for this step.

![HACS appearing in Home Assistant Add integration search](docs/manual/screenshots/03-hacs-installed.png)

## Add OpenReef To HACS

1. Open Home Assistant.
2. Open **HACS**.
3. Open the top-right menu.
4. Choose **Custom repositories**.
5. Paste this repository URL:
   `https://github.com/TheCarpyVikings/OpenReef`
6. Choose repository type **Integration**.
7. Select **Add**.
8. Search for **OpenReef** in HACS.
9. Download OpenReef.
10. Restart Home Assistant.

Official HACS custom repository docs:

<https://hacs.xyz/docs/faq/custom_repositories/>

> Screenshot to add: HACS custom repository dialog with OpenReef URL.
> Planned file: `docs/manual/screenshots/04-hacs-custom-repository.png`

## Add The OpenReef Integration

After Home Assistant restarts:

1. Go to **Settings**.
2. Open **Devices & services**.
3. Select **Add integration**.
4. Search for **OpenReef**.
5. Add OpenReef.
6. Enter your tank name.
7. Add an owner name if you want one.
8. Choose the closest tank type.
9. Finish the integration flow.

OpenReef should now appear in the Home Assistant sidebar. If it does not show up
right away, give Home Assistant a moment to finish starting, then refresh your
browser.

![Home Assistant Add integration search showing OpenReef](docs/manual/screenshots/05-add-openreef-integration.png)

![OpenReef in the Home Assistant sidebar](docs/manual/screenshots/06-openreef-sidebar.png)

## First OpenReef Setup

Open **OpenReef** from the sidebar.

On a fresh setup, OpenReef guides you through its setup screens. The first screen
shows the same basic tank details you entered when adding the integration, so you
can confirm or change them before continuing.

There are sensor presets to start from:

- **Temperature only** for the safest basic install.
- **Everything available** if you want to enable all reef, chemistry, water,
  safety, flow, lighting, sump, and room sensors, then turn off what you do not
  own.
- **No Apex / OpenReef sensors** for normal Home Assistant reef sensors such as
  display temperature, pH, and salinity.
- **Apex controller**, **Apex + Trident**, **Apex + Trident NP**,
  **Apex + FMM**, or **Apex full ecosystem** if those Neptune entities are
  already visible in Home Assistant.

The safe beginner approach:

1. Confirm your tank name, optional owner name, and tank type.
2. Choose **Temperature only** or the closest sensor preset.
3. Enable only the sensors you actually have.
4. Use **Find matches** for each enabled sensor.
5. Pick the Home Assistant entity that matches the real sensor.
6. Leave equipment control empty or disarmed for the first pass.
7. Review safety settings.
8. Save setup.

Do not worry if you only map temperature at first. A small, correct setup beats a
large, confusing one every time — and you can add more whenever you are ready.

![OpenReef setup start screen](docs/manual/screenshots/07-openreef-setup-start.png)

![OpenReef sensor mapping with Find matches](docs/manual/screenshots/08-sensor-mapping-find-matches.png)

## Understanding Entities

Home Assistant calls each device reading or control an entity. Once this clicks,
the rest of OpenReef makes a lot more sense.

Examples:

- `sensor.display_tank_temperature`
- `sensor.ph`
- `sensor.alkalinity`
- `switch.return_pump`
- `switch.heater`
- `camera.reef_tank`

OpenReef does not need to know how a sensor is wired. It only needs the Home
Assistant entity.

If **Find matches** does not surface the right entity, copy the entity ID from
Home Assistant and paste it into OpenReef. Both ways work.

## Equipment Control

Equipment control is completely optional, and it stays off until you choose
otherwise.

OpenReef uses three layers of safety:

- **Mapped** means OpenReef knows which Home Assistant switch belongs to the
  equipment.
- **Armed** means you allow OpenReef to control that equipment.
- **Disarmed** means OpenReef keeps the control locked.

For a first setup, leave equipment disarmed. There is no downside to waiting.

When you are ready to add equipment:

1. Test the switch directly in Home Assistant first.
2. Confirm the real device turns on and off as expected.
3. Map it in OpenReef.
4. Leave it disarmed until you are ready.
5. Arm only one safe device at a time.

Take extra care with:

- Heaters.
- ATO pumps.
- Return pumps.
- Display wavemakers.

These can affect livestock quickly, so go slowly and confirm each one behaves as
expected.

When you are ready to review on-device safety for heaters, ATO pumps, or return
pumps, use the [OpenReef ESPHome Edge Failsafe Recipes](docs/OPENREEF_EDGE_FAILSAFE_RECIPES.md).

![OpenReef equipment shown as disarmed](docs/manual/screenshots/09-equipment-locked.png)

## First Trust Check

Trust Check is OpenReef's readiness scan. It is a friendly way to see what
OpenReef can confirm and what still needs your attention.

After setup, open:

**OpenReef -> Settings -> System Check**

Then:

1. Press **Refresh checks**.
2. Open **Trust Check** and press **Refresh**.
3. Press **Test notification**.
4. Press **Copy support summary**.

Trust Check tells you what OpenReef can verify and what still needs review.
Unknown is not failure — unknown simply means OpenReef is refusing to pretend
something has been proven. That honesty is the point.

Common first-run Trust Check notes:

- No backup review recorded yet.
- No camera mapped yet.
- No notification test recorded yet.
- Edge failsafes not reviewed.
- Some enabled sensors are not mapped.

Seeing these on a first setup is completely normal.

![OpenReef Trust Check panel after first refresh](docs/manual/screenshots/10-trust-check.png)

## Notification Test

OpenReef can create Home Assistant persistent notifications. If you configure a
Home Assistant notify target, it can also send a push notification through Home
Assistant — so an alert can reach your phone.

For the first test:

1. Press **Test notification** in OpenReef System Check.
2. Confirm a Home Assistant notification appears.
3. If phone notifications are configured, confirm the phone receives it.

If the phone does not receive the notification, fix Home Assistant notifications
first. OpenReef relies on Home Assistant's notification system, so getting that
working is worth the effort before you depend on alerts.

## Reef Replay

Reef Replay is OpenReef's incident timeline. It gathers alert history, activity,
camera captures, and feed-watch sessions where available, so you can look back at
what happened around an event.

On a brand-new setup, Reef Replay may be empty. That is expected. It becomes
useful once OpenReef has some alert or activity history to show.

## What To Do After The Manual

When OpenReef opens, setup saves, and Trust Check runs, you are in great shape.
Next, continue with:

[OpenReef Trust Moat Smoke Test](docs/OPENREEF_TRUST_MOAT_SMOKE_TEST.md)

That smoke test checks:

- Fresh install behaviour.
- Trust Check.
- Notification test.
- Heartbeat.
- Probe health.
- Reef Replay.
- Edge-failsafe review wording.
- Restart survival.

## Troubleshooting

Most first-run hiccups are quick to fix. Here are the common ones.

### OpenReef does not appear in HACS

- Check the custom repository URL:
  `https://github.com/TheCarpyVikings/OpenReef`
- Check repository type is **Integration**.
- Refresh HACS.
- Restart Home Assistant after download.

### OpenReef does not appear in Add Integration

- Confirm HACS downloaded OpenReef.
- Restart Home Assistant.
- Clear browser cache or hard refresh.
- Check Home Assistant logs for OpenReef errors.

### OpenReef does not appear in the sidebar

- Wait until Home Assistant has fully restarted.
- Refresh the browser.
- Confirm the OpenReef integration was added in **Settings -> Devices & services**.

### Find matches does not find my sensor

- Open Home Assistant **Settings -> Devices & services -> Entities**.
- Search for the sensor.
- Copy the entity ID.
- Paste it into OpenReef.

### My trend graph is empty

Home Assistant needs recorder history before OpenReef can show useful trends.
Leave the sensor running and check again later — the history builds over time.

### Equipment controls are locked

That is expected unless the equipment is mapped and armed. Locked controls are a
safety feature, not a bug.

### Notification test does not reach my phone

Fix Home Assistant mobile notifications first. OpenReef uses Home Assistant's
notification system, so once Home Assistant can reach your phone, OpenReef can too.

### Trust Check says unknown

Unknown means OpenReef cannot verify that item yet. It is the honest answer, and
better than pretending the setup is safe.

## Glossary

**Home Assistant**  
The home automation system that OpenReef runs inside.

**Home Assistant OS**  
The recommended Home Assistant installation type for most users.

**HACS**  
Home Assistant Community Store. It lets users install custom integrations such
as OpenReef.

**Integration**  
An addition to the main Home Assistant system. OpenReef is a custom integration.

**Entity**  
A Home Assistant sensor, switch, camera, light, or other item that OpenReef can
read or control.

**Mapped**  
OpenReef knows which Home Assistant entity belongs to a reef item.

**Armed**  
OpenReef is allowed to control that equipment.

**Disarmed**  
OpenReef knows about the equipment but keeps it locked.

**Trust Check**  
OpenReef's readiness scan for sensors, notifications, heartbeat, cameras,
incident history, backup review, mappings, and edge-failsafe review.

**Reef Replay**  
OpenReef's incident timeline for alerts and nearby activity.

## Source Links

- Home Assistant installation overview:
  <https://www.home-assistant.io/installation/>
- Home Assistant Linux VM install:
  <https://www.home-assistant.io/installation/linux/>
- Home Assistant Windows VM install:
  <https://www.home-assistant.io/installation/windows/>
- Home Assistant generic x86-64 install:
  <https://www.home-assistant.io/installation/generic-x86-64/>
- HACS download/install:
  <https://hacs.dev/docs/use/download/download/>
- HACS custom repositories:
  <https://hacs.xyz/docs/faq/custom_repositories/>
- HACS integration repository type:
  <https://hacs.xyz/docs/use/repositories/type/integration/>
