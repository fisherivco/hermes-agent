"""Current-base regression coverage for typed exact gateway delivery."""

from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import ExactDeliveryReply, MessageEvent, MessageType
from gateway.session import SessionEntry, SessionSource, build_session_key
from plugins.platforms.discord.adapter import DiscordAdapter


SESSION_KEY = "agent:main:discord:channel:42:u-1"


def _source() -> SessionSource:
    return SessionSource(
        platform=Platform.DISCORD,
        chat_id="42",
        chat_type="channel",
        user_id="u-1",
    )


def _event() -> MessageEvent:
    return MessageEvent(
        text="/ingest https://example.test/source",
        source=_source(),
        message_id="m-1",
    )


def _runner(monkeypatch: pytest.MonkeyPatch, tmp_path) -> gateway_run.GatewayRunner:
    runner = gateway_run.GatewayRunner(GatewayConfig())
    runner.adapters = {}
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._handle_active_session_busy_message = AsyncMock(return_value=False)
    runner._session_db = MagicMock()
    runner._cache_session_source = lambda _key, _source: None
    runner._is_session_run_current = lambda _key, _generation: True
    runner._reply_anchor_for_event = lambda _event: None
    runner._get_guild_id = lambda _event: None
    runner._should_send_voice_reply = lambda *_args, **_kwargs: False
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()

    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = SessionEntry(
        session_key=SESSION_KEY,
        session_id="session-current-base-red",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.DISCORD,
        chat_type="channel",
    )
    runner.session_store.load_transcript.return_value = []
    runner.session_store.append_to_transcript = MagicMock()
    runner.session_store.update_session = MagicMock()

    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {"api_key": "fake"},
    )
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": True}},
    )
    monkeypatch.setattr(
        "agent.model_metadata.get_model_context_length",
        lambda *_args, **_kwargs: 100_000,
    )
    return runner


def test_first_value_checkpoint_uses_exact_ack_rail(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": True}},
    )
    message = "Source Note Draft ready\nSummary: grounded first value"
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    adapter = SimpleNamespace(
        platform=Platform.DISCORD,
        send=AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                raw_response={
                    "returned_content": message,
                    "returned_content_sha256": digest,
                },
            )
        ),
    )

    delivered = asyncio.run(
        gateway_run._deliver_first_value_checkpoint_exact(
            adapter=adapter,
            chat_id="42",
            message=message,
            digest=digest,
            metadata={"thread_id": "thread-1"},
        )
    )

    assert delivered is True
    adapter.send.assert_awaited_once_with(
        "42",
        message,
        metadata={
            "thread_id": "thread-1",
            "exact_delivery": True,
            "exact_delivery_sha256": digest,
        },
    )


def test_first_value_checkpoint_rejects_mismatched_ack(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": True}},
    )
    message = "Source Note Draft ready"
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    adapter = SimpleNamespace(
        platform=Platform.DISCORD,
        send=AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                raw_response={
                    "returned_content": message + " altered",
                    "returned_content_sha256": digest,
                },
            )
        ),
    )

    delivered = asyncio.run(
        gateway_run._deliver_first_value_checkpoint_exact(
            adapter=adapter,
            chat_id="42",
            message=message,
            digest=digest,
            metadata=None,
        )
    )

    assert delivered is False


def test_first_value_checkpoint_gate_off_does_not_send(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": False}},
    )
    message = "Source Note Draft ready"
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    adapter = SimpleNamespace(
        platform=Platform.DISCORD,
        send=AsyncMock(),
    )

    delivered = asyncio.run(
        gateway_run._deliver_first_value_checkpoint_exact(
            adapter=adapter,
            chat_id="42",
            message=message,
            digest=digest,
            metadata=None,
        )
    )

    assert delivered is False
    adapter.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_current_gateway_replaces_model_preamble_with_typed_tool_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Drive the real current gateway response path with the observed failure shape."""
    report = (
        "## Knowledge headline\n"
        "Prototype before writing a large specification.\n\n"
        "## Verification receipt\n"
        "state=VERIFIED; checks=11; errors=0; 摘要完成"
    )
    digest = hashlib.sha256(report.encode("utf-8")).hexdigest()
    fallback = (
        "The workflow completed with `VERIFIED`. The final report contract "
        "requires byte-for-byte delivery.\n\n"
        f"{report}"
    )
    runner = _runner(monkeypatch, tmp_path)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": fallback,
            "final_delivery": {"message": report, "sha256": digest},
            "messages": [
                {"role": "user", "content": "/ingest source"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "terminal",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "name": "terminal",
                    "tool_call_id": "call-1",
                    "content": "tool-owned VERIFIED envelope",
                },
                {"role": "assistant", "content": fallback},
            ],
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "api_calls": 2,
            "failed": False,
        }
    )

    response = await runner._handle_message_with_agent(
        _event(), _source(), SESSION_KEY, 1
    )

    assert response == report
    assert hashlib.sha256(response.encode("utf-8")).hexdigest() == digest


@pytest.mark.parametrize(
    "delivery",
    [
        "not-an-object",
        {"message": "exact", "sha256": "0" * 64},
        {
            "message": "exact\n",
            "sha256": hashlib.sha256(b"exact\n").hexdigest(),
        },
    ],
)
def test_typed_gateway_refuses_malformed_present_payload(
    monkeypatch,
    delivery,
) -> None:
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": True}},
    )

    result = gateway_run._typed_final_delivery_or_fallback(
        {"final_delivery": delivery},
        "model-authored fallback must not escape",
    )

    assert result == gateway_run._TYPED_FINAL_DELIVERY_REFUSAL
    assert "model-authored" not in result


def test_typed_gateway_fails_closed_when_redaction_changes_bytes(
    monkeypatch,
) -> None:
    message = "credential-shaped exact payload"
    digest = hashlib.sha256(message.encode()).hexdigest()
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": True}},
    )
    monkeypatch.setattr(
        gateway_run,
        "_redact_gateway_user_facing_secrets",
        lambda _text: "[REDACTED]",
    )

    result = gateway_run._typed_final_delivery_or_fallback(
        {"final_delivery": {"message": message, "sha256": digest}},
        "fallback",
    )

    assert result == gateway_run._TYPED_FINAL_DELIVERY_REFUSAL


def test_typed_gateway_gate_off_preserves_ordinary_response(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"gateway": {"verbatim_delivery_enabled": False}},
    )

    result = gateway_run._typed_final_delivery_or_fallback(
        {"final_delivery": "malformed"},
        "ordinary",
    )

    assert result == "ordinary"


def _discord_adapter(channel) -> DiscordAdapter:
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="***"))
    adapter._client = SimpleNamespace(
        get_channel=lambda _chat_id: channel,
        fetch_channel=AsyncMock(),
    )
    return adapter


@pytest.mark.asyncio
async def test_base_to_discord_exact_delivery_preserves_ordered_utf8_bytes() -> None:
    sent: list[str] = []

    async def wire_send(*, content, reference=None, allowed_mentions=None):
        assert allowed_mentions is not None
        sent.append(content)
        return SimpleNamespace(id=str(len(sent)), content=content)

    adapter = _discord_adapter(SimpleNamespace(type=0, send=wire_send))
    report = (
        "## Knowledge headline\n"
        + "原型優先，避免重新撰寫。" * 260
        + "\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        + "```\nMEDIA: /tmp/example.png\n```"
    )
    digest = hashlib.sha256(report.encode("utf-8")).hexdigest()

    async def handler(_event):
        return ExactDeliveryReply(report, declared_sha256=digest)

    adapter.set_message_handler(handler)
    event = MessageEvent(
        text="/ingest https://example.test/source",
        message_id="m-exact",
        source=_source(),
        message_type=MessageType.TEXT,
    )

    await adapter._process_message_background(
        event,
        build_session_key(event.source),
    )

    joined = "".join(sent)
    assert joined == report
    assert hashlib.sha256(joined.encode("utf-8")).hexdigest() == digest
    assert len(sent) > 1


@pytest.mark.asyncio
async def test_discord_exact_delivery_rejects_wrong_sha_before_wire_send() -> None:
    wire_send = AsyncMock(return_value=SimpleNamespace(id="m-1", content="exact"))
    adapter = _discord_adapter(SimpleNamespace(type=0, send=wire_send))

    result = await adapter.send(
        "42",
        "exact",
        metadata={"exact_delivery": True, "exact_delivery_sha256": "0" * 64},
    )

    assert result.success is False
    assert wire_send.await_count == 0


@pytest.mark.asyncio
async def test_discord_exact_delivery_returns_ordered_ack_identity() -> None:
    async def wire_send(*, content, reference=None, allowed_mentions=None):
        return SimpleNamespace(id=str(len(content)), content=content)

    adapter = _discord_adapter(SimpleNamespace(type=0, send=wire_send))
    report = "摘要" * 1100
    digest = hashlib.sha256(report.encode("utf-8")).hexdigest()

    result = await adapter.send(
        "42",
        report,
        metadata={"exact_delivery": True, "exact_delivery_sha256": digest},
    )

    assert result.success is True
    assert result.raw_response["returned_content"] == report
    assert result.raw_response["returned_content_sha256"] == digest


@pytest.mark.asyncio
async def test_discord_exact_delivery_avoids_normalized_whitespace_boundaries() -> None:
    sent: list[str] = []

    async def wire_send(*, content, reference=None, allowed_mentions=None):
        # Discord normalizes whitespace at an individual message boundary.
        # The ACK must therefore split inside a non-whitespace run so joining
        # the returned chunks still reproduces the runner-owned bytes.
        returned = content.strip()
        sent.append(returned)
        return SimpleNamespace(id=f"m-{len(sent)}", content=returned)

    adapter = _discord_adapter(SimpleNamespace(type=0, send=wire_send))
    report = "FIRST_VALUE_READY\nQuick Summary:\n" + ("agent workflow " * 180) + "done"
    digest = hashlib.sha256(report.encode("utf-8")).hexdigest()

    result = await adapter.send(
        "42",
        report,
        metadata={"exact_delivery": True, "exact_delivery_sha256": digest},
    )

    assert len(sent) > 1
    assert all(chunk == chunk.strip() for chunk in sent)
    assert "".join(sent) == report
    assert result.success is True
    assert result.raw_response["returned_content"] == report
    assert result.raw_response["returned_content_sha256"] == digest


@pytest.mark.asyncio
async def test_discord_exact_delivery_rejects_altered_returned_chunk() -> None:
    calls = 0

    async def wire_send(*, content, reference=None, allowed_mentions=None):
        nonlocal calls
        calls += 1
        returned = content if calls == 1 else content + " altered"
        return SimpleNamespace(id=f"m-{calls}", content=returned)

    adapter = _discord_adapter(SimpleNamespace(type=0, send=wire_send))
    report = "x" * 2100
    digest = hashlib.sha256(report.encode()).hexdigest()

    result = await adapter.send(
        "42",
        report,
        metadata={"exact_delivery": True, "exact_delivery_sha256": digest},
    )

    assert result.success is False
    assert "returned content mismatch" in result.error


@pytest.mark.asyncio
async def test_exact_partial_send_is_never_retried_as_a_full_duplicate(
    monkeypatch,
) -> None:
    calls = 0

    async def wire_send(*, content, reference=None, allowed_mentions=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ConnectionError("ConnectionError: reset by peer")
        return SimpleNamespace(id=f"m-{calls}", content=content)

    adapter = _discord_adapter(SimpleNamespace(type=0, send=wire_send))
    report = "x" * 2100
    digest = hashlib.sha256(report.encode()).hexdigest()
    monkeypatch.setattr("gateway.platforms.base.asyncio.sleep", AsyncMock())

    result = await adapter._send_with_retry(
        "42",
        report,
        metadata={"exact_delivery": True, "exact_delivery_sha256": digest},
        max_retries=1,
        base_delay=0,
    )

    assert result.success is False
    assert calls == 2


@pytest.mark.asyncio
async def test_discord_exact_delivery_refuses_forum_mutation() -> None:
    forum = SimpleNamespace(type=15, id=999, create_thread=AsyncMock())
    adapter = _discord_adapter(forum)
    report = "| a | b |\n|---|---|\n| 1 | 2 |"

    result = await adapter.send(
        "999",
        report,
        metadata={
            "exact_delivery": True,
            "exact_delivery_sha256": hashlib.sha256(report.encode()).hexdigest(),
        },
    )

    assert result.success is False
    assert forum.create_thread.await_count == 0


@pytest.mark.asyncio
async def test_default_discord_path_still_formats_tables() -> None:
    sent: list[str] = []

    async def wire_send(*, content, reference=None):
        sent.append(content)
        return SimpleNamespace(id="m-1")

    adapter = _discord_adapter(SimpleNamespace(type=0, send=wire_send))
    source = "| a | b |\n|---|---|\n| 1 | 2 |"

    result = await adapter.send("42", source)

    assert result.success is True
    assert sent and sent[0] != source
    assert "•" in sent[0]
