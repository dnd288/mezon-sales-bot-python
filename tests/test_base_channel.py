from types import SimpleNamespace

from mebot.bus.queue import MessageBus
from mebot.channels.mezon import MezonChannel


def _make_channel(allow_from: list[str]) -> MezonChannel:
    config = SimpleNamespace(client_id="bot", token="tok", allow_from=allow_from)
    return MezonChannel(config, MessageBus())


def test_is_allowed_requires_exact_match() -> None:
    channel = _make_channel(["allow@email.com"])

    assert channel.is_allowed("allow@email.com") is True
    assert channel.is_allowed("attacker|allow@email.com") is False
