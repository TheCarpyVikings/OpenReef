"""Guardian (Lagertha) — pure engine + websocket orchestration tests.

The engine (custom_components/openreef/guardian.py) is pure stdlib, so the
persona/tool/folding logic tests run with no Home Assistant at all. The
orchestration tests drive the real websocket handlers through the fake-HA
harness, with the Anthropic client and OpenAI HTTP calls replaced at the
module seams (integration._guardian_anthropic_client & friends) — no network.

What we pin down:
  * secrets never leak: keys_status()/guardian_status only ever carry
    set/unset + a 4-char hint; the full key travels only through the
    admin-only simli-session command.
  * the read ring is total: every advertised tool has an implementation and
    a corrupt/missing snapshot section degrades to "unavailable", never a
    raise (a broken config section must not take Lagertha down).
  * the tool loop terminates and threads results: tool_use -> tool_result
    (matching ids) -> final text.
  * history folding clamps hostile payloads and never starts with an
    assistant turn (the API rejects that).

Run standalone:  python3 tests/test_guardian.py
"""

from __future__ import annotations

import base64
import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402
from openreef import guardian  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
CONF_GUARDIAN_KEYS = integration.CONF_GUARDIAN_KEYS


# --- keys -------------------------------------------------------------------

def test_keys_status_masks_secrets():
    status = guardian.keys_status(
        {"anthropic": "sk-ant-secret-1234", "openai": "sk-oa-secret-5678"}
    )
    blob = str(status)
    assert "secret" not in blob
    assert status["anthropic"] == {"set": True, "hint": "1234"}
    assert status["openai"]["set"] and status["openai"]["hint"] == "5678"
    assert status["ready"] is True
    # No Simli key -> voice-only mode: ready but not faceReady.
    assert status["simli"]["set"] is False
    assert status["faceReady"] is False


def test_keys_status_face_ready_needs_key_and_face():
    base = {"anthropic": "sk-ant-secret-1234", "openai": "sk-oa-secret-5678"}
    assert guardian.keys_status({**base, "simli": "simli-key-9999"})["faceReady"] is False
    full = guardian.keys_status(
        {**base, "simli": "simli-key-9999", "simliFaceId": "face-1"}
    )
    assert full["faceReady"] is True
    assert full["simliFaceId"] == "face-1"


def test_keys_status_short_or_garbage_is_unset():
    status = guardian.keys_status({"anthropic": "short", "openai": 42})
    assert status["anthropic"]["set"] is False
    assert status["openai"] == {"set": False, "hint": ""}
    assert guardian.keys_status(None)["ready"] is False


def test_clean_keys_merge_semantics():
    current = {"anthropic": "sk-ant-old-1234", "openai": "sk-oa-old-5678"}
    # missing field = unchanged, empty string = clear, unknown fields dropped
    merged = guardian.clean_keys(
        current, {"openai": "", "simli": " simli-new ", "evil": "x"}
    )
    assert merged["anthropic"] == "sk-ant-old-1234"
    assert "openai" not in merged
    assert merged["simli"] == "simli-new"
    assert "evil" not in merged
    # length cap
    long = guardian.clean_keys({}, {"anthropic": "x" * 999})
    assert len(long["anthropic"]) == 256


# --- persona ----------------------------------------------------------------

def _cfg(**over):
    cfg = {
        "tank": {"name": "Ragnar's Reef", "owner": "Reece", "profile": "mixed_reef"},
        "guardian": {"enabled": True, "tone": "cheeky", "effort": "low", "voice": "shimmer"},
    }
    cfg.update(over)
    return cfg


def test_persona_prompt_identity_and_stability():
    prompt = guardian.persona_prompt(_cfg())
    assert "Lagertha" in prompt
    assert "Ragnar's Reef" in prompt
    assert "Reece" in prompt
    # byte-stable across calls — required for Anthropic prompt-cache hits
    assert prompt == guardian.persona_prompt(_cfg())


def test_persona_prompt_tone_and_safety():
    cheeky = guardian.persona_prompt(_cfg())
    assert "SAFETY VOICE" in cheeky
    assert "humour" in cheeky
    pro = guardian.persona_prompt(
        _cfg(guardian={"tone": "pro"})
    )
    assert "SAFETY VOICE" in pro  # the safety law survives every tone
    assert "irreverent" not in pro


def test_persona_prompt_survives_garbage_config():
    assert "Lagertha" in guardian.persona_prompt(None)
    assert "Lagertha" in guardian.persona_prompt({"tank": "nope", "guardian": []})


# --- tools ------------------------------------------------------------------

def _snapshot():
    return {
        "tank": {"name": "Ragnar's Reef", "profile": "mixed_reef", "volumeLitres": 250.0},
        "sensors": [
            {
                "id": "temp",
                "label": "Display Tank Temperature",
                "value": 25.9,
                "unit": "°C",
                "min": 24.5,
                "max": 27.5,
                "available": True,
            }
        ],
        "manualReadings": [{"parameter": "alkalinity", "value": 8.2, "unit": "dKH"}],
        "dosing": {
            "enabled": True,
            "channels": {"ch1": {"chemical": "alkalinity", "enabled": True, "dailyMl": 42}},
        },
        "awc": {"enabled": True, "method": "batch_sequential", "schedule": {"mode": "weekly"}},
        "awcTankLitres": 250.0,
        "maintenanceDue": [
            {"id": "filter", "label": "Rinse filter socks", "severity": "warning", "message": "Due today"}
        ],
        "icpReports": [
            {
                "vendor": "Triton",
                "testedAt": "2026-07-01",
                "values": {
                    "iodine": {"element": "I", "value": 20, "unit": "µg/L", "status": "low"},
                    "calcium": {"element": "Ca", "value": 420, "unit": "mg/L", "status": "ok"},
                },
            }
        ],
        "visionSummary": {"lastSeen": {"clownfish": 1000.0}, "fishCount": 5, "feeding": False},
        "alertHistory": [{"title": "pH low", "severity": "warning"}],
    }


def test_every_advertised_tool_has_an_implementation():
    names = [tool["name"] for tool in guardian.build_tools()]
    assert len(names) == len(set(names))
    snapshot = _snapshot()
    for name in names:
        result = guardian.run_tool(name, {}, snapshot)
        assert isinstance(result, dict) and result, name
        assert "error" not in result, name


def test_tool_schemas_are_anthropic_shaped():
    for tool in guardian.build_tools():
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"


def test_tank_status_formats_readings():
    result = guardian.run_tool("get_tank_status", {}, _snapshot())
    assert result["tank"]["name"] == "Ragnar's Reef"
    assert result["tank"]["volumeLitres"] == 250.0
    row = result["sensors"][0]
    assert row["value"] == 25.9 and row["min"] == 24.5 and row["available"] is True


def test_icp_report_extracts_flagged_elements():
    result = guardian.run_tool("get_icp_report", {}, _snapshot())
    assert result["available"] is True
    assert result["vendor"] == "Triton"
    assert [f["element"] for f in result["flagged"]] == ["I"]
    assert result["inRangeCount"] == 1


def test_tools_degrade_on_missing_or_corrupt_sections():
    # Every tool must answer from an EMPTY snapshot without raising.
    for tool in guardian.build_tools():
        result = guardian.run_tool(tool["name"], {}, {})
        assert isinstance(result, dict), tool["name"]
    # ...and from actively hostile shapes.
    hostile = {key: object() for key in _snapshot()}
    for tool in guardian.build_tools():
        result = guardian.run_tool(tool["name"], {}, hostile)
        assert isinstance(result, dict), tool["name"]
    assert "error" in guardian.run_tool("rm_rf_tank", {}, {})


def test_tool_lists_are_capped():
    snapshot = _snapshot()
    snapshot["sensors"] = [
        {"label": f"s{i}", "value": i, "available": True} for i in range(50)
    ]
    snapshot["alertHistory"] = [{"title": f"a{i}"} for i in range(200)]
    assert len(guardian.run_tool("get_tank_status", {}, snapshot)["sensors"]) == guardian.MAX_LIST_ITEMS
    assert len(guardian.run_tool("get_recent_alerts", {}, snapshot)["alerts"]) == guardian.MAX_LIST_ITEMS


# --- history folding --------------------------------------------------------

def test_fold_history_clamps_and_validates():
    history = (
        [{"role": "assistant", "content": "orphan lead-in"}]
        + [{"role": "user", "content": f"turn {i}"} for i in range(50)]
        + [
            {"role": "tool", "content": "nope"},
            {"role": "user", "content": 42},
            "garbage",
            {"role": "user", "content": "  "},
            {"role": "user", "content": "x" * 10_000},
        ]
    )
    folded = guardian.fold_history(history)
    assert len(folded) <= guardian.MAX_HISTORY_TURNS
    assert folded[0]["role"] == "user"          # never assistant-first
    assert all(f["role"] in ("user", "assistant") for f in folded)
    assert len(folded[-1]["content"]) == guardian.MAX_TURN_CHARS
    assert guardian.fold_history(None) == []
    assert guardian.fold_history([{"role": "assistant", "content": "hi"}]) == []


def test_sanitize_guardian_cfg_defaults_and_clamps():
    assert guardian.sanitize_guardian_cfg(None) == {
        "enabled": True, "tone": "cheeky", "effort": "low", "voice": "shimmer",
    }
    cfg = guardian.sanitize_guardian_cfg(
        {"enabled": 0, "tone": "sarcastic", "effort": "ultra", "voice": "  onyx  "}
    )
    assert cfg == {"enabled": False, "tone": "cheeky", "effort": "low", "voice": "onyx"}


# --- orchestration: snapshot ------------------------------------------------

def _entry(settings=None, keys=None):
    options = {CONF_SETTINGS: settings or {}}
    if keys is not None:
        options[CONF_GUARDIAN_KEYS] = keys
    return FakeEntry(options=options)


_KEYS = {
    "anthropic": "sk-ant-test-1234",
    "openai": "sk-oa-test-5678",
    "simli": "simli-test-9012",
    "simliFaceId": "face-lagertha",
}


def test_snapshot_reads_enabled_mapped_sensors():
    entry = _entry(
        settings={
            "sensors": {
                "temp": {"enabled": True, "entity_id": "sensor.tank_temp"},
                "ph": {"enabled": True, "entity_id": "sensor.tank_ph"},
                "salinity": {"enabled": False, "entity_id": "sensor.salinity"},
            }
        }
    )
    hass = FakeHass(
        states={"sensor.tank_temp": "25.9", "sensor.tank_ph": "unavailable"},
        entries=[entry],
    )
    config = integration._config_from_entry(entry)
    snapshot = integration._guardian_snapshot(hass, config)
    rows = {row["id"]: row for row in snapshot["sensors"]}
    assert rows["temp"]["value"] == 25.9 and rows["temp"]["available"] is True
    assert rows["ph"]["available"] is False and rows["ph"]["value"] is None
    assert "salinity" not in rows  # disabled sensors stay invisible to the model
    assert snapshot["tank"]["name"]
    assert isinstance(snapshot["maintenanceDue"], list)


# --- orchestration: websocket handlers --------------------------------------

def test_guardian_status_reports_masked_keys():
    entry = _entry(keys=_KEYS)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_guardian_status(hass, conn, {"id": 1}))
    payload = conn.results[0].payload
    assert "sk-ant" not in str(payload)
    assert payload["keys"]["ready"] is True
    assert payload["settings"]["tone"] == "cheeky"
    assert payload["model"] == integration.GUARDIAN_MODEL


def test_guardian_set_keys_stores_and_masks(monkeypatch=None):
    entry = _entry()
    hass = FakeHass(entries=[entry])

    async def _no_validation(hass_, keys_, changed_):
        return {}

    original = integration._async_guardian_validate_keys
    integration._async_guardian_validate_keys = _no_validation
    try:
        conn = FakeConnection()
        run(
            integration.websocket_guardian_set_keys(
                hass,
                conn,
                {"id": 1, "anthropic": "sk-ant-test-1234", "openai": "sk-oa-test-5678"},
            )
        )
    finally:
        integration._async_guardian_validate_keys = original
    stored = entry.options[CONF_GUARDIAN_KEYS]
    assert stored["anthropic"] == "sk-ant-test-1234"
    payload = conn.results[0].payload
    assert "sk-ant-test" not in str(payload)      # response is masked
    assert payload["keys"]["anthropic"]["hint"] == "1234"


class _FakeAnthropicMessages:
    """Scripted messages.create: first a tool_use turn, then a text turn."""

    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(type="text", text="Checking the tank."),
                    SimpleNamespace(
                        type="tool_use", id="tool-1", name="get_tank_status", input={}
                    ),
                ],
            )
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="All calm on the reef, keeper.")],
        )


def _fake_claude(fake_messages):
    def factory(api_key):
        assert api_key == "sk-ant-test-1234"
        return SimpleNamespace(messages=fake_messages)

    return factory


def test_guardian_chat_runs_tool_loop():
    entry = _entry(
        settings={"sensors": {"temp": {"enabled": True, "entity_id": "sensor.t"}}},
        keys=_KEYS,
    )
    hass = FakeHass(states={"sensor.t": "26.0"}, entries=[entry])
    fake = _FakeAnthropicMessages()
    original = integration._guardian_anthropic_client
    integration._guardian_anthropic_client = _fake_claude(fake)
    try:
        conn = FakeConnection()
        run(
            integration.websocket_guardian_chat(
                hass, conn, {"id": 7, "history": [{"role": "user", "content": "How's the tank?"}]}
            )
        )
    finally:
        integration._guardian_anthropic_client = original
    assert conn.errors == []
    assert conn.results[0].payload["reply"] == "All calm on the reef, keeper."
    # Round 2 received the tool_result threaded to the tool_use id.
    second_call_messages = fake.calls[1]["messages"]
    tool_result = second_call_messages[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "tool-1"
    assert "26.0" in tool_result["content"] or "26" in tool_result["content"]
    # Persona + tools rode along, with a cache breakpoint on the system block.
    assert fake.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert any(t["name"] == "get_tank_status" for t in fake.calls[0]["tools"])


def test_guardian_chat_requires_key_and_history():
    entry = _entry()  # no keys
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_guardian_chat(hass, conn, {"id": 1, "history": []}))
    assert conn.error_codes == ["guardian_keys"]

    entry2 = _entry(keys=_KEYS)
    hass2 = FakeHass(entries=[entry2])
    conn2 = FakeConnection()
    run(integration.websocket_guardian_chat(hass2, conn2, {"id": 2, "history": []}))
    assert conn2.error_codes == ["guardian_error"]  # nothing to reply to


def test_guardian_voice_full_loop():
    entry = _entry(keys=_KEYS)
    hass = FakeHass(entries=[entry])
    fake = _FakeAnthropicMessages()

    async def _fake_transcribe(hass_, key_, audio, mime):
        assert audio == b"fake-opus-bytes"
        return "How is the tank doing?"

    async def _fake_tts(hass_, key_, cfg_, text, fmt):
        assert text == "All calm on the reef, keeper."
        return base64.b64encode(b"fake-mp3").decode(), "mp3"

    saved = (
        integration._guardian_anthropic_client,
        integration._async_guardian_transcribe,
        integration._async_guardian_tts,
    )
    integration._guardian_anthropic_client = _fake_claude(fake)
    integration._async_guardian_transcribe = _fake_transcribe
    integration._async_guardian_tts = _fake_tts
    try:
        conn = FakeConnection()
        run(
            integration.websocket_guardian_voice(
                hass,
                conn,
                {
                    "id": 3,
                    "audio": base64.b64encode(b"fake-opus-bytes").decode(),
                    "mime": "audio/webm",
                    "history": [],
                    "tts": "mp3",
                },
            )
        )
    finally:
        (
            integration._guardian_anthropic_client,
            integration._async_guardian_transcribe,
            integration._async_guardian_tts,
        ) = saved
    assert conn.errors == []
    payload = conn.results[0].payload
    assert payload["transcript"] == "How is the tank doing?"
    assert payload["reply"] == "All calm on the reef, keeper."
    assert payload["audioFormat"] == "mp3"
    assert base64.b64decode(payload["audio"]) == b"fake-mp3"


def test_guardian_voice_rejects_bad_payloads():
    entry = _entry(keys=_KEYS)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(
        integration.websocket_guardian_voice(
            hass, conn, {"id": 1, "audio": "!!!not-base64!!!", "tts": "none"}
        )
    )
    assert conn.error_codes == ["bad_audio"]

    conn2 = FakeConnection()
    run(
        integration.websocket_guardian_voice(
            FakeHass(entries=[_entry()]), conn2, {"id": 2, "audio": "AAAA", "tts": "none"}
        )
    )
    assert conn2.error_codes == ["guardian_keys"]


def test_simli_session_hands_out_credentials_only_when_face_ready():
    hass = FakeHass(entries=[_entry(keys=_KEYS)])
    conn = FakeConnection()
    run(integration.websocket_guardian_simli_session(hass, conn, {"id": 1}))
    assert conn.results[0].payload == {
        "apiKey": "simli-test-9012",
        "faceId": "face-lagertha",
    }

    partial = {k: v for k, v in _KEYS.items() if k != "simliFaceId"}
    conn2 = FakeConnection()
    run(
        integration.websocket_guardian_simli_session(
            FakeHass(entries=[_entry(keys=partial)]), conn2, {"id": 2}
        )
    )
    assert conn2.error_codes == ["guardian_keys"]


def test_normalise_config_sanitizes_guardian_section():
    entry = _entry(settings={"guardian": {"tone": "sarcastic", "effort": "max"}})
    config = integration._config_from_entry(entry)
    assert config["guardian"] == {
        "enabled": True, "tone": "cheeky", "effort": "low", "voice": "shimmer",
    }


# --- tiny standalone runner (so this works without pytest installed) ---

def _main() -> int:
    tests = sorted(
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001 - report everything
            failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed", "" if not failed else f"— FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
