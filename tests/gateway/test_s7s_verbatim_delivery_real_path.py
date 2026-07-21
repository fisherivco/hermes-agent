"""Executable S7S transport-boundary regression tests.

These tests intentionally exercise the BasePlatformAdapter and DiscordAdapter
send paths with fake wire objects.  They must not be replaced with source-text
or helper-only assertions: the purpose is to keep the repaired boundaries
ratcheted against future Hermes updates.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import ExactDeliveryReply, MessageEvent, MessageType
from gateway.session import SessionSource, build_session_key
from plugins.platforms.discord.adapter import DiscordAdapter


def test_gateway_typed_bridge_ignores_transcript_only_envelope(monkeypatch):
    import gateway.run as run_module
    monkeypatch.setattr(run_module, "_load_gateway_config", lambda: {"gateway": {"verbatim_delivery_enabled": True}})
    report = "typed exact"
    digest = hashlib.sha256(report.encode()).hexdigest()
    transcript_envelope = {
        "final_report_message": report,
        "final_report_message_sha256": digest,
        "final_report_delivery_contract": {"mode": "exact_verbatim"},
    }
    transcript_only = {"messages": [{"role": "tool", "content": json.dumps(transcript_envelope)}]}
    assert run_module._typed_final_delivery_or_fallback(transcript_only, "normal") == "normal"
    typed = {"final_delivery": {"message": report, "sha256": digest}}
    output = run_module._typed_final_delivery_or_fallback(typed, "normal")
    assert isinstance(output, ExactDeliveryReply)
    assert str(output) == report


@pytest.mark.parametrize("delivery", [
    "not-an-object",
    {"message": "exact", "sha256": "0" * 64},
    {"message": "exact\n", "sha256": hashlib.sha256(b"exact\n").hexdigest()},
])
def test_gateway_typed_bridge_refuses_malformed_present_payload(monkeypatch, delivery):
    import gateway.run as run_module
    monkeypatch.setattr(run_module, "_load_gateway_config", lambda: {"gateway": {"verbatim_delivery_enabled": True}})
    result = run_module._typed_final_delivery_or_fallback(
        {"final_delivery": delivery},
        "model-authored fallback must not escape",
    )
    assert result == run_module._TYPED_FINAL_DELIVERY_REFUSAL
    assert "model-authored" not in result


def test_gateway_typed_bridge_refuses_redaction_mutation(monkeypatch):
    import gateway.run as run_module
    monkeypatch.setattr(run_module, "_load_gateway_config", lambda: {"gateway": {"verbatim_delivery_enabled": True}})
    monkeypatch.setattr(run_module, "_redact_gateway_user_facing_secrets", lambda text: "[REDACTED]")
    message = "secret-shaped exact"
    result = run_module._typed_final_delivery_or_fallback(
        {"final_delivery": {"message": message, "sha256": hashlib.sha256(message.encode()).hexdigest()}},
        "model-authored fallback must not escape",
    )
    assert result == run_module._TYPED_FINAL_DELIVERY_REFUSAL


@pytest.mark.parametrize("agent_result", [
    {},
    {"already_sent": True, "final_delivery": "malformed"},
])
def test_gateway_typed_bridge_preserves_ordinary_fallback_when_not_eligible(monkeypatch, agent_result):
    import gateway.run as run_module
    monkeypatch.setattr(run_module, "_load_gateway_config", lambda: {"gateway": {"verbatim_delivery_enabled": True}})
    assert run_module._typed_final_delivery_or_fallback(agent_result, "ordinary") == "ordinary"


def test_gateway_typed_bridge_preserves_fallback_when_gate_disabled(monkeypatch):
    import gateway.run as run_module
    monkeypatch.setattr(run_module, "_load_gateway_config", lambda: {"gateway": {"verbatim_delivery_enabled": False}})
    assert run_module._typed_final_delivery_or_fallback(
        {"final_delivery": "malformed"}, "ordinary"
    ) == "ordinary"


@pytest.mark.asyncio
async def test_typed_final_delivery_suppresses_prebridge_voice(monkeypatch):
    import gateway.run as run_module
    monkeypatch.setattr(run_module, "_load_gateway_config", lambda: {"gateway": {"verbatim_delivery_enabled": True}})
    message = "voice-free exact"
    digest = hashlib.sha256(message.encode()).hexdigest()
    agent_result = {"final_delivery": {"message": message, "sha256": digest}}
    runner = SimpleNamespace(
        _should_send_voice_reply=MagicMock(return_value=True),
        _send_voice_reply=AsyncMock(),
    )
    await run_module._send_auto_voice_unless_typed(
        runner, object(), "model response", [], agent_result, already_sent=False,
    )
    runner._should_send_voice_reply.assert_not_called()
    runner._send_voice_reply.assert_not_awaited()
    output = run_module._typed_final_delivery_or_fallback(agent_result, "model response")
    assert isinstance(output, ExactDeliveryReply)
    assert str(output) == message


def _adapter(channel):
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="***"))
    adapter._client = SimpleNamespace(
        get_channel=lambda _chat_id: channel,
        fetch_channel=AsyncMock(),
    )
    return adapter


@pytest.mark.asyncio
async def test_base_to_discord_exact_delivery_preserves_5609_bytes():
    sent: list[str] = []

    async def wire_send(*, content, reference=None, allowed_mentions=None):
        sent.append(content)
        assert allowed_mentions is not None
        return SimpleNamespace(id=str(len(sent)), content=content)

    channel = SimpleNamespace(type=0, send=wire_send)
    adapter = _adapter(channel)
    report = (
        "## Knowledge headline\n"
        + "x" * 5000
        + "\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        + "```\nMEDIA: /tmp/example.png\n```"
    )
    report = report[:5599] + " " * (5609 - len(report))
    assert len(report) == 5609

    async def handler(_event):
        return ExactDeliveryReply(report, hashlib.sha256(report.encode()).hexdigest())

    adapter.set_message_handler(handler)
    event = MessageEvent(
        text="ingest https://example.test/source",
        message_id="m-1",
        source=SessionSource(platform=Platform.DISCORD, chat_id="42", user_id="u-1"),
        message_type=MessageType.TEXT,
    )
    await adapter._process_message_background(event, build_session_key(event.source))

    assert "".join(sent) == report
    assert hashlib.sha256("".join(sent).encode()).hexdigest() == hashlib.sha256(report.encode()).hexdigest()
    assert len(sent) == 3


@pytest.mark.asyncio
async def test_forum_exact_delivery_fails_before_thread_creation():
    forum = SimpleNamespace(type=15, id=999, create_thread=AsyncMock())
    adapter = _adapter(forum)
    report = "| a | b |\n|---|---|\n| 1 | 2 |"
    result = await adapter.send(
        "999",
        report,
        metadata={"exact_delivery": True, "exact_delivery_sha256": hashlib.sha256(report.encode()).hexdigest()},
    )
    assert result.success is False
    assert forum.create_thread.await_count == 0


@pytest.mark.asyncio
async def test_exact_delivery_missing_sha_fails_before_wire_send():
    wire = AsyncMock(return_value=SimpleNamespace(id="m-1"))
    adapter = _adapter(SimpleNamespace(type=0, send=wire))
    result = await adapter.send("42", "exact", metadata={"exact_delivery": True})
    assert result.success is False
    assert wire.await_count == 0


@pytest.mark.asyncio
async def test_exact_delivery_wrong_sha_fails_before_wire_send():
    wire = AsyncMock(return_value=SimpleNamespace(id="m-1"))
    adapter = _adapter(SimpleNamespace(type=0, send=wire))
    result = await adapter.send(
        "42",
        "exact",
        metadata={"exact_delivery": True, "exact_delivery_sha256": "0" * 64},
    )
    assert result.success is False
    assert wire.await_count == 0


@pytest.mark.asyncio
async def test_exact_retry_never_reports_altered_fallback_success():
    wire_payloads: list[str] = []

    async def fail_wire(*, content, reference=None, allowed_mentions=None):
        wire_payloads.append(content)
        raise RuntimeError("400 formatting failure")

    adapter = _adapter(SimpleNamespace(type=0, send=fail_wire))
    report = "## Exact\n" + "x" * 200
    result = await adapter._send_with_retry(
        "42",
        report,
        metadata={"exact_delivery": True, "exact_delivery_sha256": hashlib.sha256(report.encode()).hexdigest()},
        max_retries=0,
    )
    assert result.success is False
    assert wire_payloads == [report]


@pytest.mark.asyncio
async def test_exact_delivery_disables_all_mentions(monkeypatch):
    captured = []

    class FakeAllowedMentions:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(
        "plugins.platforms.discord.adapter.discord.AllowedMentions",
        FakeAllowedMentions,
    )

    async def wire_send(*, content, reference=None, allowed_mentions=None):
        assert isinstance(allowed_mentions, FakeAllowedMentions)
        return SimpleNamespace(id="m-1", content=content)

    adapter = _adapter(SimpleNamespace(type=0, send=wire_send))
    report = "mention-safe"
    result = await adapter.send(
        "42", report,
        metadata={"exact_delivery": True, "exact_delivery_sha256": hashlib.sha256(report.encode()).hexdigest()},
    )
    assert result.success is True
    assert captured == [{"everyone": False, "users": False, "roles": False, "replied_user": False}]


@pytest.mark.asyncio
async def test_exact_delivery_rejects_altered_returned_content():
    calls = 0

    async def altered_wire(*, content, reference=None, allowed_mentions=None):
        nonlocal calls
        calls += 1
        returned = content if calls == 1 else content + " altered"
        return SimpleNamespace(id=f"m-{calls}", content=returned)

    adapter = _adapter(SimpleNamespace(type=0, send=altered_wire))
    report = "x" * 2001
    result = await adapter.send(
        "42",
        report,
        metadata={"exact_delivery": True, "exact_delivery_sha256": hashlib.sha256(report.encode()).hexdigest()},
    )
    assert result.success is False
    assert "returned content mismatch" in result.error


@pytest.mark.asyncio
async def test_exact_delivery_returns_ordered_ack_identity():
    async def wire_send(*, content, reference=None, allowed_mentions=None):
        return SimpleNamespace(id=str(len(content)), content=content)

    adapter = _adapter(SimpleNamespace(type=0, send=wire_send))
    report = "y" * 2001
    digest = hashlib.sha256(report.encode()).hexdigest()
    result = await adapter.send(
        "42", report,
        metadata={"exact_delivery": True, "exact_delivery_sha256": digest},
    )
    assert result.success is True
    assert result.raw_response["returned_content"] == report
    assert result.raw_response["returned_content_sha256"] == digest


@pytest.mark.asyncio
async def test_default_discord_path_still_formats_without_exact_metadata():
    sent: list[str] = []

    async def wire_send(*, content, reference=None):
        sent.append(content)
        return SimpleNamespace(id="m-1")

    adapter = _adapter(SimpleNamespace(type=0, send=wire_send))
    source = "| a | b |\n|---|---|\n| 1 | 2 |"
    result = await adapter.send("42", source)
    assert result.success is True
    assert sent and sent[0] != source
    assert "•" in sent[0]
