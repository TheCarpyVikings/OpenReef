# Lagertha — Live AI Guardian Avatar (Brainstorm / Design v0)

**Date:** 2026-07-17
**Status:** Stage A BUILT (2026-07-17) — see §10; Stages B–D pending
**Codename:** Guardian (panel tab) / Lagertha (the character)

**Pinned stack (final):** brain `claude-sonnet-5` via the official `anthropic`
SDK (lazy import, manifest requirement) · STT `gpt-4o-transcribe` · TTS
`gpt-4o-mini-tts` (mp3 for direct playback, 24 kHz pcm → 16 kHz for Simli
lip-sync) · face Simli (vendored `simli-client.mjs` ESM bundle, livekit
inlined) · no LiveKit/Pipecat server — plain async loop in the integration.
**Ease-of-setup is a hard requirement:** all keys are pasted in the panel's
Guardian tab (no HA options-flow digging), each key is live-validated at save,
and every degradation is graceful (no Simli → voice-only; no keys → the tab
explains exactly which two keys to get and where from).

---

## 1. Vision

A live, talking AI avatar — **Lagertha, the shield-maiden** (same Simli face used in
Lagertha_OS) — living in an on-demand **Guardian tab** of the OpenReef panel. She is
the face of the "intelligence layer for reefing": she can read everything the
controller knows (params, trends, dosing, AWC, ICP, maintenance, camera events),
explain it conversationally in a reef-expert voice, and act on the tank — but only
with explicit confirmation.

No competitor has this. Apex Fusion is a dashboard; this is a crew member.

## 2. Decisions locked (2026-07-17)

| Axis | Decision |
|---|---|
| Placement | **HA panel tab, on-demand.** Avatar session starts when the tab opens, closes on leave. Alerts/reminders still surface as normal when she's off. |
| Face | **Reuse the Lagertha Simli face ID** from Lagertha_OS (free tier last time). Prior art: `Lagertha_OS/src/hooks/useSimli.ts`, `SimliAvatar.tsx`; labs copy already in this repo at `src/components/avatar/SimliAvatar.tsx`. |
| Authority | **Tiered: read freely, confirm to act.** Any state change requires explicit confirmation. Safety-critical overrides (dosing volume limits, AWC safety layers) are *not exposed at all*. |
| Voice stack | **Chained: Whisper (STT) → Claude (brain + tools) → OpenAI TTS (PCM) → Simli.** Claude chosen for reasoning quality on pattern analysis and disciplined tool use. |
| Economics | **BYO keys for beta** (Anthropic + OpenAI + Simli keys in OpenReef settings), **hosted/bundled tier later** as the monetization story. |
| Knowledge | **Persona prompt + live tank data via tools + curated RAG** over trusted sources (Rich Ross spawning guide, dosing methodology, OpenReef manual). Answers grounded in *your* tank and *cited* sources — Trust Moat, not vibes. No fine-tuning. |
| Smart features v1 | All four: **pattern/anomaly narration, conversational ICP analysis, proactive daily briefing, camera vision Q&A.** |

## 3. Architecture

```
Browser (Guardian tab in openreef-panel)
  ├─ Simli client (WebRTC face, vendored JS) ← PCM 16k audio
  ├─ Mic capture (push-to-talk, MediaRecorder)
  └─ HA WebSocket ↕ (base64 audio chunks + JSON events)

HA custom component (custom_components/openreef/guardian.py)
  ├─ STT: OpenAI Whisper API (utterance at a time — PTT keeps this simple)
  ├─ Brain: Claude (Anthropic API) with OpenReef tool definitions
  │    ├─ read tools  → recorder/trends, dosing, awc, icp, spawning,
  │    │                maintenance, vision events, tank profile
  │    ├─ act tools   → return pending_confirmation tokens (never direct)
  │    └─ RAG tool    → local BM25 retrieval over docs/knowledge corpus
  ├─ TTS: OpenAI tts (pcm) → stream back to browser → simli.sendAudioData()
  └─ llm.py (async_get_tools) → same read tools exposed to stock HA Assist
```

Key points:

- **Push-to-talk first.** Tap/hold mic, one utterance, one Whisper call. No
  streaming STT, no wake word, no VAD in v1. Latency ~1.5–2.5s is acceptable for a
  "consult the guardian" interaction; wake word ("Hey Lagertha") is a later stage.
- **Audio transport:** base64 chunks over the existing OpenReef WS command surface
  (same registration pattern as dosing/AWC WS handlers, so the fake-HA test harness
  covers it). Avoids fighting HA's binary-stream plumbing in v1.
- **PCM plumbing is already solved** — Lagertha_OS code downsamples OpenAI 24kHz →
  Simli 16kHz (`useSimli.ts:54-104`). Port that verbatim into the panel JS.
- **`llm.py` is a cheap, strategic bonus:** HA's LLM API discovers
  `openreef/llm.py:async_get_tools`, so every read tool we build for Lagertha also
  works in the user's own Assist pipeline / voice hardware for free. One tool
  surface, two consumers.
- **Vision Q&A rides the same brain:** Claude is multimodal, so "how do the corals
  look?" = grab a camera snapshot (Camera V2 / vision.py) and attach it to the
  conversation. No second vision vendor.

## 4. Authority model (Trust Moat)

Three rings:

1. **Read ring (free):** all sensors, trends, dosing/AWC state, ICP results,
   maintenance due-status, camera events, spawning schedule. Lagertha answers
   anything, any time.
2. **Confirm ring (act with consent):** dose X ml (within existing engine limits),
   start/skip AWC, feed mode, snooze/complete maintenance, acknowledge alerts,
   adjust light scene. Tool call returns `pending_confirmation` + a token; the panel
   renders a confirm chip ("Dose 12 ml Alk now? ✓ / ✗"); only the user's tap/voice
   "confirm" executes it. Tokens expire (~60s). Everything logged to an audit trail.
3. **Forbidden ring (not exposed):** dosing volume/safety-limit overrides, AWC
   safety-layer bypasses, freshness enforcement bypass, HA admin ops. These tools
   simply don't exist in her toolbox — a hallucinated call can't reach them.

Voice/personality rules inherit the existing law: **personality only on calm
states.** Briefings and chat get the cheeky shield-maiden; anything alert- or
safety-adjacent is delivered straight. Cheeky/Pro toggle applies to her too.

## 5. Smart features (the demo headliners)

- **Proactive daily briefing** — on tab open: overnight events, params vs. trend,
  dosing status/drift, maintenance due, feed-watch/camera events, next spawning
  window. Composed server-side (deterministic data gathering), narrated by Claude.
- **Pattern / anomaly narration** — a scheduled analysis pass over recorder trends +
  dosing drift + events produces stored "insights" ("Alk consumption up 18% over 10
  days — correlates with the frag additions on the 7th"). Lagertha surfaces them in
  briefings and on demand. Builds directly on health trends + Stage-A drift
  detection.
- **Conversational ICP analysis** — walk through an imported ICP test: flagged
  elements, what they mean, correction plan, follow-up test date. ICP importer v1
  already provides normalized + flagged data; this is a tool + prompt job.
- **Camera vision Q&A** — snapshot-on-demand into the Claude conversation; feed-watch
  events as context ("the wrasse fed normally at 14:02").

## 6. Costs (BYO-key beta, rough)

Per 10-minute session: Simli ~free tier / ≤$0.10 · Whisper ~$0.06/hr of audio ·
Claude ~$0.05–0.15 (tool-heavy turns) · TTS ~$0.15/1M chars ≈ pennies.
**Realistic: well under $0.50 per session.** On-demand placement is what keeps this
sane — an always-on kiosk would be ~$13+/day in avatar minutes alone.

## 7. Staging sketch (mirror the Camera A→D arc)

- **Stage A — Skeleton:** Guardian tab, Simli face live, PTT voice loop
  (Whisper→Claude→TTS→lips), persona prompt, read-only tools for params/status.
  Config flow fields for the three API keys. *Demoable: talk to Lagertha about the tank.*
- **Stage B — Hands:** confirm-to-act ring (tokens, confirm chips, audit log), full
  tool surface across engines, `llm.py` exposure to HA Assist. Harness tests for
  every act-tool's confirmation path.
- **Stage C — Brains:** daily briefing, insight engine (scheduled pattern pass),
  conversational ICP. RAG corpus + local BM25 retrieval with citations.
- **Stage D — Eyes & polish:** camera snapshot Q&A, feed-watch context, wake-word
  entry ("Hey Lagertha" via Assist → opens Guardian), Cheeky/Pro voice variants,
  hosted-tier groundwork.

## 8. Risks / open questions

- **Simli idle artifacts:** 2026 reviews flag unnatural idle state ("the face never
  felt at rest"). Mitigation: on-demand sessions keep idle time short; fallback to
  the static Viking art between utterances if it bothers us. Swappable later
  (Anam ~$0.18/min is the quality leader; bitHuman does *edge/local* avatars —
  interesting for the local-first story).
- **Does the old Simli face ID still exist** on the account / free tier terms in
  2026? Verify before Stage A.
- **Three API keys is real onboarding friction** — config flow must validate each
  key with a live check and degrade gracefully (no Simli key → voice-only mode?).
- **WS base64 audio throughput** on Pi-class HA hosts — measure in Stage A; binary
  handler is the escape hatch.
- **Livestream safety:** never demo the confirm ring live with real dosing until the
  audit path has soaked. (Sunday-stream stability rules apply.)

## 9. Research notes (2026-07)

- Winning industry pattern: avatar as a swappable plugin on a voice-agent framework
  (LiveKit Agents lists 14+ avatar providers). We deliberately skip the framework —
  it would add a server beyond HA — but keep the avatar layer thin so swapping stays
  possible.
- Simli: ~$0.009/min, <300ms, Gaussian-splat 3D, price leader. Anam: most realistic,
  ~$0.18/min. HeyGen LiveAvatar: ~$0.10–0.20/min, most framework-flexible.
  bitHuman: $0.01–0.04/min, edge deployment.
- HA LLM API: integrations ship `<integration>/llm.py` with `async_get_tools(hass,
  llm_context, api_id)`; tools are voluptuous-schema'd, called per-request,
  context-aware. No admin ops permitted — aligns with our forbidden ring.

## 10. Stage A — what shipped (2026-07-17)

- `custom_components/openreef/guardian.py` — pure engine (repo convention:
  stdlib only, dict-in/dict-out): persona prompt (byte-stable for prompt
  caching; personality-only-on-calm encoded), 8 read-ring tool schemas +
  defensive formatters, history folding/clamping, key masking/merging,
  settings sanitizer. Forbidden ring enforced structurally: no act tools exist.
- `__init__.py` — orchestration: `_guardian_snapshot()` (sensors via mappings,
  manual readings, dosing, AWC, maintenance-due via the lockstep evaluator,
  ICP, vision summary, alert history), Claude tool loop (`claude-sonnet-5`,
  adaptive thinking, effort from settings, cache breakpoint on system,
  refusal-handled), OpenAI STT/TTS via aiohttp (lazy imports keep CI
  dependency-free), live key validation, 5 WS commands:
  `guardian_status` / `guardian_set_keys` / `guardian_chat` /
  `guardian_voice` / `guardian_simli_session` (admin-gated key handout).
- Keys stored in entry options under `guardian_keys`, OUTSIDE the exportable
  settings blob — config export/import can never leak them; responses only
  ever carry set/unset + 4-char hint.
- Panel: "Lagertha" tab (gated on `guardian.enabled`, default on) — key setup
  card with per-key status/problems, transcript chat (text + Enter), 🎙
  push-to-talk (MediaRecorder → base64 → `guardian_voice`), mp3 playback with
  speaking-art swap, Simli live face via vendored `simli-client.mjs`
  (persistent detached video/audio nodes survive innerHTML re-renders;
  24→16 kHz PCM downsample for lip-sync), face session ended on tab leave
  (on-demand billing).
- `manifest.json`: `anthropic>=0.116.0` requirement (HA auto-installs).
- Tests: `tests/test_guardian.py` — 24 tests (engine + WS orchestration via
  fake-HA with the Anthropic/OpenAI seams monkeypatched); full suite 553 green.
- NOT yet verified against real APIs/HA — first live smoke test pending
  (Simli face ID from the old account, mic permissions over HTTPS, key flow).

Sources: [Live Avatar Landscape (10-provider eval)](https://medium.com/@ggarciabernardo/the-live-avatar-landscape-apis-transport-and-subjective-evaluation-of-10-leading-providers-5b5b6e8a54dc) ·
[Virtual avatar solutions 2026](https://www.toughtongueai.com/blog/best-virtual-avatar-solutions-2026) ·
[Avatar pricing comparison](https://www.spatius.ai/blog/compare-pricing-leading-ai-avatar-services-2026/) ·
[HeyGen vs Tavus vs Anam vs Simli](https://www.docket.io/blog/heygen-vs-tavus-vs-anam-vs-simli-how-we-chose-dockets-ai-avatar-provider) ·
[HA LLM API dev docs](https://developers.home-assistant.io/docs/core/llm/) ·
[home-llm](https://github.com/acon96/home-llm)
