"""Zulip: the `ZulipAdmin` protocol, its httpx client and its in memory fake."""

from tessaro_clients.zulip.client import HttpZulipAdmin, zulip_http
from tessaro_clients.zulip.fake import FakeZulipAdmin
from tessaro_clients.zulip.models import Channel, ChatUser, NewChatUser
from tessaro_clients.zulip.protocol import ZulipAdmin

__all__ = [
    "Channel",
    "ChatUser",
    "FakeZulipAdmin",
    "HttpZulipAdmin",
    "NewChatUser",
    "ZulipAdmin",
    "zulip_http",
]
