from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mebot.bus.events import OutboundMessage
from mebot.bus.queue import MessageBus
from mebot.channels.mezon import MezonChannel


def _make_channel(allow_from: list[str]) -> MezonChannel:
    allow_cfg = SimpleNamespace(clan=[], channel=[], user=allow_from)
    config = SimpleNamespace(client_id="bot", token="tok", allow_from=allow_cfg)
    return MezonChannel(config, MessageBus())


def test_is_allowed_requires_exact_match() -> None:
    channel = _make_channel(["allow@email.com"])

    assert channel.is_allowed("allow@email.com") is True
    assert channel.is_allowed("attacker|allow@email.com") is False


def test_should_not_stop_typing_for_progress_messages() -> None:
    msg = OutboundMessage(
        channel="mezon",
        chat_id="123",
        content="processing...",
        metadata={"_progress": True},
    )
    assert MezonChannel._should_stop_typing(msg) is False


def test_should_stop_typing_for_final_messages() -> None:
    msg = OutboundMessage(
        channel="mezon",
        chat_id="123",
        content="final reply",
    )
    assert MezonChannel._should_stop_typing(msg) is True


def test_resolve_typing_mode_fallbacks_to_message_mode() -> None:
    assert MezonChannel._resolve_typing_mode(None, 7) == 7


def test_resolve_typing_mode_defaults_when_invalid() -> None:
    assert MezonChannel._resolve_typing_mode(None, "invalid") == 2


@pytest.mark.asyncio
async def test_on_message_does_not_start_typing_when_not_allowed() -> None:
    channel = _make_channel(["allow@email.com"])
    channel._start_typing = AsyncMock()  # type: ignore[method-assign]
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    message = SimpleNamespace(
        sender_id="not-allowed@email.com",
        channel_id="1840659199483187200",
        clan_id="1779484504377790464",
        channel_type=0,
        mode=2,
        is_public=True,
        content='{"t":"hello"}',
    )

    await channel._on_message(message)

    channel._start_typing.assert_not_called()
    channel._handle_message.assert_not_called()
