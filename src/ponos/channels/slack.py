"""Slack: the same conversation, where the team already is.

Read by polling, like Telegram, and for the same reason: `conversations.history`
is a GET. Slack's other two ways in — the Events API and Socket Mode — want a
public HTTPS endpoint or a websocket held open by a daemon, and a runner that
wakes every thirty minutes has neither. Polling costs one call per run, two
when a question is outstanding.

A question is posted to the channel, and its **thread** is where the answer is
expected: that is how two tickets can be waiting at once without their answers
being confused. A message typed in the channel itself still counts — it answers
the last question asked — because that is what people do.

Anybody in the channel can answer, unless `allowed_users` names who may: a
reply becomes a comment, and a comment wakes a ticket whose session runs with
`bypassPermissions`. In a channel a whole team reads, that list is what keeps
"can post in #general" from meaning "can run commands on the runner's machine".

The bot needs `chat:write` to speak, and the history scope matching where you
put it: `channels:history` for a public channel, `groups:history` for a private
one, `im:history` for a direct message. And it has to be *in* the channel:
`/invite @your-bot`, which is the step everyone forgets.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from . import Ask, Channel, ChannelError, Incoming, Reply, _memory, _remember, request

API = "https://slack.com/api"

# Slack renders anything longer as a file, which nobody opens on a phone.
LIMIT = 3000

HINTS = {
    "not_in_channel": "the bot is not in that channel — /invite @your-bot",
    "channel_not_found": "no such channel id, or the bot cannot see it",
    "missing_scope": "the token lacks a scope — chat:write, and channels:history to read replies"
    " (channels:read to find a channel by its name)",
    "invalid_auth": "the bot token was refused — it starts with xoxb-",
}


class Slack(Channel):
    name = "slack"
    # A channel has other conversations in it, and a colleague's "ok" is not an
    # approval of anything. The thread of the question is what makes an answer
    # an answer here — or the ticket, named in the message.
    fallback = False

    def __init__(
        self,
        token: str,
        channel: str,
        allowed: frozenset[str] = frozenset(),
        default_project: str = "",
    ) -> None:
        self._token = token
        self._channel = str(channel).strip()
        self._id = ""
        self.allowed = frozenset(allowed)
        self.default_project = default_project

    def _headers(self) -> dict[str, Any]:
        return {"Authorization": f"Bearer {self._token}"}

    def _call(
        self, method: str, payload: dict[str, Any] | None = None, **query: str
    ) -> dict[str, Any]:
        url = f"{API}/{method}"
        if query:
            url = f"{url}?{urllib.parse.urlencode({k: v for k, v in query.items() if v})}"
        body = request(url, payload, headers=self._headers())
        if not body.get("ok"):
            code = str(body.get("error", "refused"))
            hint = HINTS.get(code, "")
            raise ChannelError(f"{code}{f' — {hint}' if hint else ''}")
        return body

    def _where(self) -> str:
        """The channel's ID, even when the configuration gave its name.

        Every call wants the ID, and `infra` or `#infra` is what people type: Slack
        answers a name with `channel_not_found`, which reads as a missing invitation
        rather than a spelling. So a name is looked up once in `conversations.list`
        and its ID remembered with the cursor — an ID does not change when the
        channel is renamed, and one call a pass every ten seconds would. A name
        no channel has is said as such.
        """
        if self._id:
            return self._id
        if re.fullmatch(r"[CGD][A-Z0-9]+", self._channel):
            self._id = self._channel
            return self._id
        name = self._channel.lstrip("#").strip().lower()
        known = dict(_memory().get(self.name, {}).get("ids", {}))
        if name not in known:
            cursor = ""
            while True:
                body = self._call(
                    "conversations.list",
                    types="public_channel,private_channel",
                    exclude_archived="true",
                    limit="1000",
                    cursor=cursor,
                )
                for channel in body.get("channels", []):
                    if str(channel.get("name", "")).lower() == name and channel.get("id"):
                        known[name] = str(channel["id"])
                cursor = str((body.get("response_metadata") or {}).get("next_cursor") or "")
                if name in known or not cursor:
                    break
            if name not in known:
                raise ChannelError(
                    f"channel_not_found — no channel named #{name} that the bot can see:"
                    " put its channel ID (C…) in channel, or /invite the bot if it is private"
                )
            _remember(self.name, {"ids": known})
        self._id = known[name]
        return self._id

    # -- outbound ------------------------------------------------------------

    def _thread_of(self, reply: Reply) -> str:
        """A thread is counted from its first message, not from the last one."""
        return reply.thread or reply.ref

    def _post(self, text: str, thread: str = "") -> str:
        payload: dict[str, Any] = {
            "channel": self._where(),
            "text": text[:LIMIT],
            "unfurl_links": False,
        }
        if thread:
            payload["thread_ts"] = thread
        body = self._call("chat.postMessage", payload)
        return str(body.get("ts", ""))

    # -- inbound -------------------------------------------------------------

    def _fetch(self, cursor: str, asks: list[Ask]) -> tuple[list[Incoming], str]:
        """What was said in the channel, and under the questions still open.

        Two shapes, because Slack has two: a message in the channel appears in
        `conversations.history`, a message in a thread does not — it only shows
        up under its parent. So the history is read once, then the replies of
        each question we are still waiting on. Bounded by the questions the
        channel remembers, which is why that list is short.

        A Slack timestamp sorts like a number, so the newest one seen is the
        cursor for both calls at once.
        """
        latest = cursor
        incoming: list[Incoming] = []

        for message in self._call(
            "conversations.history", channel=self._where(), oldest=cursor, limit="50"
        ).get("messages", []):
            found = self._read(message, cursor)
            if found:
                incoming.append(found)
                latest = max(latest, found.ref)

        for ask in asks:
            if not ask.ref:
                continue
            try:
                replies = self._call(
                    "conversations.replies",
                    channel=self._where(),
                    ts=ask.ref,
                    oldest=cursor,
                    limit="50",
                ).get("messages", [])
            except ChannelError:
                # A thread whose parent was deleted is not a reason to lose the
                # rest of the run's answers.
                continue
            for message in replies:
                found = self._read(message, cursor)
                if not found or found.ref == ask.ref:
                    continue
                found.thread = ask.ref
                incoming.append(found)
                latest = max(latest, found.ref)

        incoming.sort(key=lambda message: message.ref)
        return incoming, latest

    def _read(self, message: dict[str, Any], cursor: str) -> Incoming | None:
        """One raw Slack message, or None when it is not somebody talking.

        Our own posts carry a `bot_id`, and joins, pins and file comments carry
        a `subtype`: neither is an answer, and a bot reading its own messages
        back is how a loop starts.
        """
        if message.get("bot_id") or message.get("subtype") or not message.get("user"):
            return None
        if self.allowed and str(message.get("user")) not in self.allowed:
            return None  # somebody in the channel, not somebody allowed to answer
        stamp = str(message.get("ts", ""))
        if not stamp or (cursor and stamp <= cursor):
            return None
        thread = str(message.get("thread_ts", ""))
        return Incoming(
            ref=stamp,
            thread=thread if thread and thread != stamp else "",
            text=message.get("text") or "",
            who="",
        )

    # -- diagnostics ---------------------------------------------------------

    def check(self) -> str:
        me = self._call("auth.test")
        channel = self._call("conversations.info", channel=self._where()).get("channel", {})
        name = channel.get("name") or self._channel
        if channel.get("is_channel") and not channel.get("is_member"):
            raise ChannelError(f"not in #{name} — /invite @{me.get('user', 'your-bot')}")
        return f"{me.get('user', 'bot')} on {me.get('team', 'your workspace')} → #{name}"
