"""Executable S7S transport-boundary regression tests.

These tests intentionally exercise the BasePlatformAdapter and DiscordAdapter
send paths with fake wire objects.  They must not be replaced with source-text
or helper-only assertions: the purpose is to keep the repaired boundaries
ratcheted against future Hermes updates.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import ExactDeliveryReply, MessageEvent, MessageType
from gateway.session import SessionSource, build_session_key
from plugins.platforms.discord.adapter import DiscordAdapter


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

    async def wire_send(*, content, reference=None):
        sent.append(content)
        return SimpleNamespace(id=str(len(sent)))

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

    async def fail_wire(*, content, reference=None):
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
