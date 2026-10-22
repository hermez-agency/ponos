"""`notify.py` and `channels/`: being told, and answering, from a phone."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from support import (
    ROOT,
    TICKET,
    _answering,
    _config,
    _http_answering,
    _state,
    _state_home,
    case,
)

from ponos import channels, db, notify, notion, voice
from ponos import config as C
from ponos.channels import slack as slack_channel
from ponos.channels import telegram as telegram_channel
from ponos.runner import Runner

# -- being told, and answering ------------------------------------------------


@contextmanager
def _api(module, answers: dict):
    """Replace one channel's HTTP call with a table of canned answers."""
    calls: list[tuple[str, dict | None]] = []

    def fake(url, payload=None, headers=None):
        calls.append((url, payload))
        for fragment, body in answers.items():
            if fragment in url:
                return body
        return {"ok": True, "result": {}}

    original = module.request
    module.request = fake
    try:
        yield calls
    finally:
        module.request = original


@case
def a_word_is_a_verdict_only_when_it_opens_the_sentence():
    assert channels.decide("oui") == "yes"
    assert channels.decide("Yes, and rename the column while you are there") == "yes"
    assert channels.decide("👍") == "yes"
    assert channels.decide("non") == "no"
    assert channels.decide("No — that column stays") == "no"
    assert channels.decide("aucune idée, demande à Marie") == "", "not every sentence is a verdict"
    assert channels.decide("I have no idea") == "", "a no in the middle is not an answer"
    assert channels.decide("   ") == ""


@case
def a_bare_yes_reaches_the_agent_as_a_sentence():
    """ "oui" means nothing to a session that never saw the notification."""
    written = channels.answer(channels.Reply(channel="telegram", text="oui", who="Salvador"))
    assert "Salvador" in written
    assert "go ahead" in written
    assert written.count("oui") == 0, "the word itself adds nothing once it is spelled out"

    kept = channels.answer(channels.Reply(channel="slack", text="oui, et renomme la colonne aussi"))
    assert "go ahead" in kept
    assert "renomme la colonne" in kept, "what was said around the word is the instruction"

    free = channels.answer(channels.Reply(channel="telegram", text="celui du dashboard"))
    assert "celui du dashboard" in free
    assert "go ahead" not in free and "do not" not in free


OTHER = "3ca451680af480beb02ac9d2cb79078c"


def _asks() -> list[channels.Ask]:
    return [
        channels.Ask(ref="10", ticket=OTHER, title="Le footer"),
        channels.Ask(ref="11", ticket=TICKET, title="Le header"),
    ]


@case
def an_answer_finds_its_ticket_by_thread_first_then_by_name():
    channel = telegram_channel.Telegram("token", "42")
    replied = channel._route(channels.Incoming(ref="12", thread="10", text="oui"), _asks())
    assert replied.ticket == OTHER, "a reply to a message answers that message"

    named = channel._route(
        channels.Incoming(ref="12", text="oui pour 3ca45168-0af4-80be-b02a-c9d2cb79078c"),
        _asks(),
    )
    assert named.ticket == OTHER, "a ticket named in the text is not a guess either"

    last = channel._route(channels.Incoming(ref="12", text="oui"), _asks())
    assert last.ticket == TICKET, "a bare yes answers the question just asked"
    assert channel._route(channels.Incoming(ref="12", text="oui"), []) is None


@case
def a_channel_says_what_telegram_said_and_waits_when_asked_to():
    """A 4xx is Telegram's sentence ("chat not found"), not a number; and a
    429 — Telegram's "too many requests" — is a pause, not a lost message."""
    script = [
        httpx.Response(429, headers={"Retry-After": "3"}, json={"ok": False}),
        httpx.Response(200, json={"ok": True}),
        httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"}),
    ]
    sent: list[bytes] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return script.pop(0)

    with _http_answering(answer) as pauses:
        assert channels.request("https://api.telegram.test/send", {"text": "a"}) == {"ok": True}
        assert pauses == [3.0] and len(sent) == 2, (pauses, sent)
        try:
            channels.request("https://api.telegram.test/send", {"text": "b"})
        except channels.ChannelError as error:
            assert str(error) == "400 Bad Request: chat not found", error
        else:
            raise AssertionError("a refusal was taken for a message sent")


@case
def a_telegram_message_from_anywhere_else_is_not_an_answer():
    """A bot token is a public address: anyone can write to it."""
    channel = telegram_channel.Telegram("token", "42")
    updates = {
        "ok": True,
        "result": [
            {
                "update_id": 7,
                "message": {
                    "message_id": 1,
                    "chat": {"id": 42},
                    "from": {"first_name": "Salvador"},
                    "text": "oui",
                },
            },
            {
                "update_id": 8,
                "message": {
                    "message_id": 2,
                    "chat": {"id": 99},
                    "from": {"first_name": "Someone"},
                    "text": "rm -rf",
                },
            },
            {
                "update_id": 9,
                "message": {
                    "message_id": 3,
                    "chat": {"id": 42},
                    "from": {"is_bot": True},
                    "text": "echo",
                },
            },
        ],
    }
    with _api(telegram_channel, {"getUpdates": updates}) as calls:
        incoming, cursor = channel._fetch("", [])
    assert [message.text for message in incoming] == ["oui"]
    assert incoming[0].who == "Salvador"
    assert cursor == "10", "the offset acknowledges what was read, so it is read once"
    assert calls[0][1]["allowed_updates"] == ["message"]


@case
def in_a_group_only_the_people_named_may_answer():
    """An answer becomes a comment, and a comment wakes a ticket whose session
    runs with `bypassPermissions`. In a group, "can write here" was "can run
    commands on the machine"; `allowed_users` names who may."""
    group = {
        "ok": True,
        "result": [
            {
                "update_id": 7,
                "message": {
                    "message_id": 1,
                    "chat": {"id": -42},
                    "from": {"id": 1001, "first_name": "Salvador"},
                    "text": "oui",
                },
            },
            {
                "update_id": 8,
                "message": {
                    "message_id": 2,
                    "chat": {"id": -42},
                    "from": {"id": 2002, "first_name": "Someone"},
                    "text": "et supprime la base",
                },
            },
        ],
    }
    with _api(telegram_channel, {"getUpdates": group}):
        everybody, _ = telegram_channel.Telegram("token", "-42")._fetch("", [])
    assert [message.text for message in everybody] == ["oui", "et supprime la base"], (
        "nobody named is the old behaviour, kept"
    )
    with _api(telegram_channel, {"getUpdates": group}):
        named, cursor = telegram_channel.Telegram("token", "-42", frozenset({"1001"}))._fetch(
            "", []
        )
    assert [message.who for message in named] == ["Salvador"], named
    assert cursor == "9", "what was dropped is still acknowledged, so it is never read again"

    channel = slack_channel.Slack("xoxb-token", "C1", frozenset({"U1"}))
    assert channel._read({"ts": "2", "user": "U1", "text": "oui"}, "1").text == "oui"
    assert channel._read({"ts": "3", "user": "U2", "text": "rm -rf"}, "1") is None
    assert slack_channel.Slack("xoxb", "C1")._read({"ts": "3", "user": "U2", "text": "ok"}, "1")

    config = _config(
        '[notify.telegram]\ntoken = "123:abc"\nchat = "-42"\nallowed_users = [1001, 1002]\n'
        '[notify.slack]\ntoken = "xoxb-1"\nchannel = "C1"\nallowed_users = "U1, U2"\n'
    )
    opened = {channel.name: channel.allowed for channel in channels.open(config.notify)}
    assert opened == {"telegram": {"1001", "1002"}, "slack": {"U1", "U2"}}, opened
    assert channels.allowed_users("") == frozenset()


def _update(identifier: int, message: int, text: str) -> dict:
    return {
        "update_id": identifier,
        "message": {
            "message_id": message,
            "chat": {"id": 42},
            "from": {"first_name": "Salvador"},
            "text": text,
        },
    }


SENT = {"sendMessage": {"ok": True, "result": {"message_id": 5}}}


@case
def nothing_said_before_the_runner_was_listening_is_an_answer():
    """Telegram keeps a day of updates; Slack keeps everything ever said."""
    channel = telegram_channel.Telegram("token", "42")
    backlog = {"ok": True, "result": [_update(7, 1, "oui"), _update(8, 2, "et le footer ?")]}
    with _state():
        with _api(telegram_channel, {"getUpdates": backlog, **SENT}):
            channel.send("?", ticket=TICKET, title="Le header", ask=True)
            assert channel.collect() == [], "a backlog is a conversation, not a queue"
        with _api(
            telegram_channel, {"getUpdates": {"ok": True, "result": [_update(9, 3, "oui")]}}
        ) as calls:
            assert [reply.text for reply in channel.collect()] == ["oui"]
            assert calls[0][1]["offset"] == 9, "the first poll only settled where now is"


@case
def what_a_channel_reads_once_it_never_reads_again():
    channel = telegram_channel.Telegram("token", "42")
    with _state():
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": []}, **SENT}):
            channel.send("Blocked · le header ?", ticket=TICKET, title="Le header", ask=True)
            assert channel.collect() == []
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": [_update(7, 1, "oui")]}}):
            first = channel.collect()
        assert [reply.ticket for reply in first] == [TICKET]
        assert first[0].title == "Le header", "the question remembers what it was about"
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": []}}) as calls:
            assert channel.collect() == []
            assert calls[0][1]["offset"] == 8, "resumed where the last run stopped"


@case
def a_room_shared_with_other_people_never_guesses():
    """In Slack the message beside yours belongs to somebody else's thread."""
    ask = [channels.Ask(ref="100.0", ticket=TICKET, title="Le header")]
    loose = channels.Incoming(ref="100.4", text="ok")
    assert slack_channel.Slack("xoxb", "C1")._route(loose, ask) is None
    assert telegram_channel.Telegram("token", "42")._route(loose, ask).ticket == TICKET
    threaded = channels.Incoming(ref="100.4", thread="100.0", text="ok")
    assert slack_channel.Slack("xoxb", "C1")._route(threaded, ask).ticket == TICKET
    named = channels.Incoming(ref="100.4", text=f"ok pour {TICKET}")
    assert slack_channel.Slack("xoxb", "C1")._route(named, ask).ticket == TICKET


@case
def an_acknowledgement_hangs_where_each_service_counts_threads_from():
    """Slack threads from the first message; Telegram quotes the last one."""
    reply = channels.Reply(channel="", text="oui", ref="100.4", thread="100.0")
    assert slack_channel.Slack("xoxb", "C1")._thread_of(reply) == "100.0"
    assert telegram_channel.Telegram("token", "42")._thread_of(reply) == "100.4"


@case
def slack_reads_the_thread_the_question_opened():
    """A message in a thread never appears in the channel's history."""
    channel = slack_channel.Slack("xoxb-token", "C1")
    answers = {
        "conversations.history": {
            "ok": True,
            "messages": [
                {"ts": "100.2", "user": "U1", "text": "et le footer ?"},
                {"ts": "100.1", "bot_id": "B1", "text": "🙋 Blocked · le header"},
                {"ts": "099.9", "user": "U1", "text": "déjà lu"},
            ],
        },
        "conversations.replies": {
            "ok": True,
            "messages": [
                {"ts": "100.0", "bot_id": "B1", "text": "🙋 Blocked · le header"},
                {"ts": "100.3", "user": "U1", "thread_ts": "100.0", "text": "oui"},
            ],
        },
    }
    with _api(slack_channel, answers):
        incoming, cursor = channel._fetch("100.0", [channels.Ask(ref="100.0", ticket=TICKET)])
    said = [(message.text, message.thread) for message in incoming]
    assert said == [("et le footer ?", ""), ("oui", "100.0")], said
    assert cursor == "100.3", "the newest timestamp seen, whichever call saw it"


@case
def slack_never_reads_its_own_voice_back():
    channel = slack_channel.Slack("xoxb-token", "C1")
    assert channel._read({"ts": "2", "bot_id": "B1", "text": "posted by us"}, "1") is None
    assert channel._read({"ts": "2", "subtype": "channel_join", "user": "U1"}, "1") is None
    assert channel._read({"ts": "1", "user": "U1", "text": "old"}, "1") is None
    assert channel._read({"ts": "2", "user": "U1", "text": "oui"}, "1").text == "oui"


@case
def a_question_outlives_the_run_that_asked_it():
    """An answer typed tomorrow morning still knows which ticket it settles."""
    channel = telegram_channel.Telegram("token", "42")
    with _state():
        with _api(telegram_channel, {"sendMessage": {"ok": True, "result": {"message_id": 1}}}):
            for index in range(channels.ASKS + 3):
                channel.send("?", ticket=f"{index:032d}", title=f"ticket {index}", ask=True)
        remembered = channels._memory()["telegram"]["asks"]
    assert len(remembered) == channels.ASKS, "a bounded memory, not a growing file"
    assert remembered[-1]["title"] == f"ticket {channels.ASKS + 2}"


@case
def a_channel_exists_only_once_both_of_its_values_are_there():
    half = _config('[notify.telegram]\ntoken = "123:abc"\n')
    assert not half.notify.remote and channels.open(half.notify) == []

    whole = _config('[notify.telegram]\ntoken = "123:abc"\nchat = 4242\n')
    assert whole.notify.remote
    assert whole.notify.telegram["chat"] == "4242", "a chat id is compared to JSON, so it is text"
    assert [channel.name for channel in channels.open(whole.notify)] == ["telegram"]

    both = _config(
        '[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
        '[notify.slack]\ntoken = "xoxb"\nchannel = "C1"\n'
    )
    assert [channel.name for channel in channels.open(both.notify)] == ["telegram", "slack"]


@case
def the_switch_that_came_first_still_means_what_it_said():
    """`runner.notify` was the desktop notification, and stays it."""
    assert _config("").notify.desktop is True
    assert _config("[runner]\nnotify = false\n").notify.desktop is False
    assert _config("[runner]\nnotify = false\n\n[notify]\ndesktop = true\n").notify.desktop is True


@case
def a_moment_nobody_named_is_dropped_rather_than_never_sent():
    every = _config("")
    assert every.notify.wants("blocked") and every.notify.wants("done")
    only = _config('[notify]\nevents = ["blocked", "Failed", "merged"]\n')
    assert only.notify.events == ("blocked", "failed"), only.notify.events
    assert not only.notify.wants("done")
    assert not only.notify.wants("merged"), "a typo is not a moment"


@case
def a_value_can_be_written_into_a_table_that_has_a_dot_in_its_name():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n')
    assert C.write_value(path, "notify.telegram", "chat", "4242") is True
    assert C.write_value(path, "notify.telegram", "chat", "4242") is False, "already says that"
    assert C.load(path).notify.telegram["chat"] == "4242"
    assert 'token = "ntn_real"' in path.read_text(), "the rest of the file is untouched"


@case
def an_answer_from_a_phone_becomes_the_comment_that_wakes_the_ticket():
    """One path, not two: the reply is a comment, and comments already wake."""
    runner, stub = _answering(
        [channels.Reply(channel="telegram", text="oui", ticket=TICKET, title="Le header")]
    )
    assert len(runner.client.written) == 1
    page, text = runner.client.written[0]
    assert page == TICKET
    assert "go ahead" in text
    assert not text.startswith("ponos@"), (
        "signed as ours, the answer would close the ticket instead of waking it"
    )
    assert stub.said and "Le header" in stub.said[0], "an answer nobody confirms is a phone call"


@case
def a_message_that_answers_nothing_is_never_written_to_a_ticket():
    runner, stub = _answering([channels.Reply(channel="telegram", text="tiens, une idée")])
    assert runner.client.written == []
    assert stub.said == [], "a bot that answers ordinary talk is a bot nobody keeps"

    runner, stub = _answering([channels.Reply(channel="telegram", text="oui")])
    assert runner.client.written == []
    assert stub.said, "a yes that landed nowhere was meant for us, and is told it missed"


@case
def a_notion_that_refuses_the_answer_says_so_where_it_was_typed():
    runner, stub = _answering(
        [channels.Reply(channel="telegram", text="oui", ticket=TICKET, title="Le header")],
        error="403 API token does not have access",
    )
    assert runner.client.written == []
    assert "403" in stub.said[0]


@case
def a_blocked_ticket_travels_with_its_question_and_its_link():
    sent: list[dict] = []
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config(
        '[notify]\ndesktop = false\n\n[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
    )
    runner.dry_run = False
    runner.quiet = True
    ticket = type(
        "T",
        (),
        {
            "page": notion.Page(id=TICKET, url="https://notion.so/t", title="Le header"),
            "id": TICKET,
            "title": "Le header",
            "url": "https://notion.so/t",
        },
    )()

    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append({"text": text, **rest})
    try:
        with _state_home():
            runner._tell(
                "blocked",
                ticket,
                "blocked",
                "Which header — the dashboard one or the public site?",
                ask=True,
            )
    finally:
        channels.announce = original

    assert len(sent) == 1
    message = sent[0]
    assert message["text"].startswith("🙋 Stuck · Le header"), "the comment's own verdict"
    assert "Which header" in message["text"], "the agent's question, not the runner's summary"
    assert "https://notion.so/t" in message["text"], "a notification you have to go and find"
    assert "An answer here" not in message["text"], "the question says how to answer it"
    assert message["ask"] is True and message["ticket"] == TICKET


@case
def nothing_is_sent_anywhere_during_a_dry_run():
    sent: list[str] = []
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config('[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n')
    runner.dry_run = True
    runner.quiet = True
    ticket = type(
        "T",
        (),
        {
            "page": notion.Page(id=TICKET, url="u", title="t"),
            "title": "t",
            "url": "u",
        },
    )()
    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append(text)
    try:
        runner._tell("done", ticket, "review", "branch")
    finally:
        channels.announce = original
    assert sent == []


@contextmanager
def _notifying(*, missing: str = ""):
    """The tools a notification uses, replaced by a note of what they were asked.

    One of them can be taken away, because on a real machine one of them is: a
    box with no `gdbus`, a session with no `xdg-open`. None of that is allowed
    to cost the notification itself.
    """
    launched: list[list[str]] = []
    tools = ("notify-send", "gdbus", "dbus-monitor", "xdg-open")
    found = {name: f"/usr/bin/{name}" for name in tools if name != missing}

    def run(command, **rest):
        launched.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    originals = (shutil.which, subprocess.run, subprocess.Popen)
    shutil.which = lambda name: found.get(name)
    subprocess.run = run
    subprocess.Popen = lambda command, **rest: launched.append(command)
    try:
        yield launched
    finally:
        shutil.which, subprocess.run, subprocess.Popen = originals


@case
def a_desktop_notification_takes_you_to_the_ticket_it_names():
    """A line on screen you cannot follow is a title you then go and hunt for."""
    with _notifying() as launched:
        assert notify.send("Blocked · Le header", "Which header?", link="https://notion.so/t")
    assert len(launched) == 1, "the plain notification is not sent on top of the clickable one"
    command = launched[0]
    assert command[1:3] == ["-m", "ponos.notify"], (
        "the click is waited for beside the run, never inside it"
    )
    assert command[3:] == [
        "https://notion.so/t",
        "Blocked · Le header",
        "Which header?",
        "normal",
        "Open the ticket",
        "plain",
    ]

    with _notifying() as launched:
        notify.send(
            "To review · t",
            "PR #42",
            link="https://notion.so/t",
            warning=True,
            buttons=(
                ("See the PR", "https://github.com/o/r/pull/42"),
                ("Open the ticket", "https://notion.so/t"),
            ),
        )
    assert launched[0][8:] == [
        "warning",
        "See the PR",
        "https://github.com/o/r/pull/42",
        "Open the ticket",
        "https://notion.so/t",
    ], "each button travels to the child with where it goes"


@case
def a_notification_with_nowhere_to_go_is_a_notification_all_the_same():
    for tool in ("gdbus", "dbus-monitor", "xdg-open"):
        with _notifying(missing=tool) as launched:
            assert notify.send("Ready to review · t", "branch", link="https://notion.so/t")
        assert launched[0][0] == "/usr/bin/notify-send", f"sent anyway, without {tool}"

    with _notifying() as launched:
        assert notify.send("Ponos updated", "0.4.0")
    assert launched[0][0] == "/usr/bin/notify-send", "nothing to open, so nothing to follow"

    with _notifying(missing="notify-send") as launched:
        assert notify.send("Ponos updated", "0.4.0") is False
    assert launched == []


@case
def the_notification_posted_over_dbus_is_the_one_notify_send_would_have_sent():
    posted: list[list[str]] = []
    original = subprocess.run
    subprocess.run = lambda command, **rest: (
        posted.append(command) or subprocess.CompletedProcess(command, 0, "(uint32 42,)\n", "")
    )
    try:
        assert notify._post("Blocked · t", '42 "why"', urgent=True, warning=True) == "42"
        assert (
            notify._post(
                "To review · t",
                "PR #42",
                urgent=False,
                buttons=(("See the PR", "https://github.com/o/r/pull/42"),),
            )
            == "42"
        )
    finally:
        subprocess.run = original
    command = posted[0]
    assert "--" in command, "`-1` is an expiry, and gdbus would read it as an option"
    assert command[command.index("--") + 1 :] == [
        '"Ponos"',
        "0",
        '"dialog-warning"',
        '"Blocked · t"',
        '"42 \\"why\\""',
        '["default", "Open the ticket"]',
        "{'urgency': <byte 2>}",
        "-1",
    ], "a body is a string, even when it reads like a number"
    command = posted[1]
    tail = command[command.index("--") + 1 :]
    assert tail[2] == f'"{notify.ICON}"', "Ponos's own icon, not the information sign"
    assert tail[5] == '["default", "Open the ticket", "open-0", "See the PR"]'
    assert tail[6] == "{'urgency': <byte 1>}"


@case
def the_icon_of_ponos_falls_back_on_the_system_ones():
    assert notify.ICON.is_file(), "the mascot's icon ships with the runner"
    assert notify._icon(False) == str(notify.ICON)
    assert notify._icon(True) == "dialog-warning", "a failure says so by its icon"
    original = notify.ICON
    notify.ICON = original.with_name("missing.png")
    try:
        assert notify._icon(False) == "dialog-information"
    finally:
        notify.ICON = original


@case
def only_a_click_opens_the_page_and_a_dismissal_never_does():
    """`dbus-monitor` says it over several lines, and about every notification."""

    def watching(*lines):
        return type("W", (), {"stdout": iter(lines)})()

    clicked = watching(
        "signal ... interface=org.freedesktop.Notifications; member=ActionInvoked\n",
        "   uint32 7\n",
        '   string "default"\n',
    )
    assert notify._clicked(clicked, "7") == "default"

    button = watching(
        "signal ... interface=org.freedesktop.Notifications; member=ActivationToken\n",
        "   uint32 7\n",
        '   string "token"\n',
        "signal ... interface=org.freedesktop.Notifications; member=ActionInvoked\n",
        "   uint32 7\n",
        '   string "open-0"\n',
    )
    assert notify._clicked(button, "7") == "open-0", "which button, not only that one was"

    dismissed = watching(
        "signal ... interface=org.freedesktop.Notifications; member=NotificationClosed\n",
        "   uint32 7\n",
        "   uint32 2\n",
    )
    assert not notify._clicked(dismissed, "7")

    somebody_else = watching(
        "signal ... interface=org.freedesktop.Notifications; member=ActionInvoked\n",
        "   uint32 9\n",
        '   string "default"\n',
    )
    assert not notify._clicked(somebody_else, "7"), "another application's notification"


@case
def a_ticket_notification_carries_its_page_to_the_screen_too():
    seen: list[dict] = []
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config("")
    runner.dry_run = False
    runner.quiet = True
    ticket = type(
        "T",
        (),
        {
            "page": notion.Page(id=TICKET, url="https://notion.so/t", title="t"),
            "id": TICKET,
            "title": "t",
            "url": "https://notion.so/t",
        },
    )()
    original = notify.send
    notify.send = lambda title, body, **rest: seen.append({"title": title, **rest})
    try:
        with _state_home():
            runner._tell("done", ticket, "review", "branch")
    finally:
        notify.send = original
    assert seen == [
        {
            "title": "To review",
            "urgent": False,
            "warning": False,
            "link": "https://notion.so/t",
            "action": "Open the ticket",
            "buttons": (),
        }
    ]

    seen.clear()
    runner.config.runner.language = "fr"
    notify.send = lambda title, body, **rest: seen.append({"title": title, **rest})
    try:
        with _state_home():
            runner._tell("done", ticket, "review", "branch")
    finally:
        notify.send = original
    assert seen[0]["title"] == "À relire" and seen[0]["action"] == "Ouvrir le ticket"

    seen.clear()
    pull = "https://github.com/o/r/pull/42"
    notify.send = lambda title, body, **rest: seen.append({"title": title, "body": body, **rest})
    try:
        with _state_home():
            runner._tell(
                "done",
                ticket,
                "review",
                f"PR #42 · 3 commits · 4 minutes · 0,82 $\nDone.\n{pull}",
                project="Leadz",
                facts=("PR #42", "3 commits"),
                summary="Done.",
                pull_request=pull,
            )
            runner._tell("blocked", ticket, "blocked", "Which one?", ask=True, summary="Which one?")
            runner._tell("failed", ticket, "failed", "It broke.")
    finally:
        notify.send = original
    review, blocked, failed = seen
    assert review["title"] == "À relire — Leadz"
    assert review["body"] == "t\nDone.", "no address, price, or duration"
    assert review["buttons"] == (("Voir la PR", pull), ("Ouvrir le ticket", "https://notion.so/t"))
    assert blocked["title"] == "Ponos a une question" and blocked["urgent"] is True
    assert blocked["body"] == "t\nWhich one?\nRéponds dans le ticket"
    assert failed["urgent"] is False and failed["warning"] is True, "a failure goes away by itself"
    assert failed["buttons"] == ()


@case
def a_desktop_notification_says_what_happened_where_and_what_to_do():
    """The comment's words do not fit a desktop: see `Voice.desktop`."""
    said = voice.Voice("fr")
    title, body = said.desktop(
        "review",
        "Leadz — [Audit] Tester l'app en prod via Claude in Chrome (créer, modifier, supprimer)",
        project="Leadz",
        summary="Le formulaire est refait : puces pour la catégorie et le type, bouton désactivé "
        "sans titre, message d'erreur sous chaque champ et focus sur le premier champ fautif.",
    )
    assert title == "À relire — Leadz", "the event and the project, the whole of a lock screen"
    ticket, sentence = body.split("\n")
    assert ticket == "[Audit] Tester l'app en prod via Claude in Chrome (créer…", ticket
    assert len(ticket) <= voice.TITLE + 1, "the title is cut on a word, with an ellipsis"
    assert sentence.endswith("…") and len(sentence) <= voice.GIST + 1, sentence
    assert sentence.startswith("Le formulaire est refait : puces"), "French spacing is kept"
    assert not sentence[:-1].endswith(" "), "cut on a word"

    # Markdown, addresses and markup, none of which a desktop can draw or follow.
    title, body = said.desktop(
        "review",
        "Leadz — Fix `the` form",
        project="Leadz",
        summary="Done in **two** steps, see [the doc](https://x.y/doc) and "
        "https://github.com/o/r/pull/9 — <b>Tom</b> & `snake_case` kept.",
    )
    assert title == "À relire — Leadz"
    assert body == (
        "Fix the form\n"
        "Done in two steps, see the doc and — &lt;b&gt;Tom&lt;/b&gt; &amp; snake_case kept."
    ), body
    assert "http" not in body and "`" not in body and "**" not in body

    # A question, said as one, without the options it cannot be answered with.
    title, body = said.desktop("blocked", "Ponos — Which header?", summary="Quel en-tête ?")
    assert title == "Ponos a une question — Ponos"
    assert body == "Which header?\nQuel en-tête ?\nRéponds dans le ticket"
    assert voice.Voice("en").desktop("blocked", "t", summary="x") == (
        "Ponos has a question",
        "t\nx\nAnswer in the ticket",
    )

    # Never a bare "Ponos" with nothing under it, and a sentence even when the
    # session said none.
    assert said.desktop("failed", "Adam — Corriger le formulaire") == (
        "Ticket en erreur — Adam",
        "Corriger le formulaire\nLe travail s'est arrêté sur une erreur",
    )
    assert said.desktop("review", "Adam — Corriger le formulaire", project="Adam") == (
        "À relire — Adam",
        "Corriger le formulaire\nUne pull request est prête",
    )
    assert said.desktop("merged", "Adam — Une tâche", project="Adam")[0] == "Ticket terminé — Adam"
    assert said.desktop("prepared", "Portfolio — Une tâche")[0] == "À valider — Portfolio"
    assert said.desktop("read", "Résumé", project="Leadz")[0] == "À lire — Leadz"
    # No project to compare to: only a short prefix is taken for one.
    assert said.desktop("failed", "Corriger le bug du formulaire - côté serveur")[0] == (
        "Ticket en erreur"
    )
    assert said.desktop("failed", "Corriger le bug du formulaire - côté serveur")[1].startswith(
        "Corriger le bug du formulaire - côté serveur\n"
    ), "the ticket's name is whole when it fits"


@case
def a_ticket_that_speaks_again_replaces_its_notification_instead_of_stacking(state_home):
    posted: list[list[str]] = []
    original = subprocess.run
    subprocess.run = lambda command, **rest: (
        posted.append(command) or subprocess.CompletedProcess(command, 0, "(uint32 7,)\n", "")
    )
    try:
        assert notify._post("t", "b", urgent=False, replaces="5", key="https://notion.so/t") == "7"
    finally:
        subprocess.run = original
    tail = posted[0][posted[0].index("--") + 1 :]
    assert tail[1] == "5", "posted over the ticket's last one"
    assert tail[6] == (
        "{'urgency': <byte 1>, 'x-canonical-private-synchronous': <\"https://notion.so/t\">}"
    )

    assert notify._remembered("https://notion.so/t") == {}
    notify._remember("https://notion.so/t", "7", {})
    assert notify._remembered("https://notion.so/t")["id"] == "7"
    assert notify._remembered("https://notion.so/other") == {}

    with _notifying() as launched:
        notify.send("t", "b")
    assert "string:x-canonical-private-synchronous:" not in " ".join(launched[0])
    with _notifying(missing="gdbus") as launched:
        notify.send("t", "b", link="https://notion.so/t")
    assert launched[0][launched[0].index("--hint") + 1] == (
        "string:x-canonical-private-synchronous:https://notion.so/t"
    )


@case
def the_icon_of_ponos_is_cut_out_in_the_sizes_a_desktop_asks_for():
    """An opaque square is drawn by a desktop as a black one."""
    import struct

    for size in (48, 64, 128, 256):
        data = (notify.ICON.parent / f"ponos-{size}.png").read_bytes()
        width, height, depth, colour = struct.unpack(">IIBB", data[16:26])
        assert (width, height) == (size, size) and colour == 6, "RGBA, so with an alpha channel"
    assert notify.ICON.name == "ponos-256.png"


def _png_pixels(data: bytes) -> list[tuple[int, int, int, int]]:
    """The pixels of an 8-bit RGB or RGBA PNG, unfiltered — enough to read a colour."""
    import struct
    import zlib

    width, height, depth, colour = struct.unpack(">IIBB", data[16:26])
    assert depth == 8 and colour in (2, 6), "an 8-bit RGB or RGBA PNG"
    step = 4 if colour == 6 else 3
    chunks, at = b"", 8
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at : at + 8])
        if kind == b"IDAT":
            chunks += data[at + 8 : at + 8 + length]
        at += 12 + length
    raw, stride, rows, previous = zlib.decompress(chunks), width * step, [], bytearray(width * step)
    for y in range(height):
        kind, line = (
            raw[y * (stride + 1)],
            bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]),
        )
        for x in range(stride):
            left = line[x - step] if x >= step else 0
            up, corner = previous[x], previous[x - step] if x >= step else 0
            if kind == 1:
                line[x] = (line[x] + left) & 255
            elif kind == 2:
                line[x] = (line[x] + up) & 255
            elif kind == 3:
                line[x] = (line[x] + (left + up) // 2) & 255
            elif kind == 4:
                guess = left + up - corner
                near = min(
                    (abs(guess - left), left),
                    (abs(guess - up), up),
                    (abs(guess - corner), corner),
                    key=lambda pair: pair[0],
                )
                line[x] = (line[x] + near[1]) & 255
        rows.append(line)
        previous = line
    return [
        (*row[x : x + 3], row[x + 3] if step == 4 else 255)
        for row in rows
        for x in range(0, stride, step)
    ]


@case
def the_icon_of_a_notification_is_the_orange_mascot_and_the_mascot_script_draws_it():
    """The desktop icons were cut by hand once, and stayed blue when the robot went orange.

    They are the mascot's like the app icons are, so `scripts/mascot.mjs` writes
    them with the rest — and a vivid pixel of the robot is Hermez orange, red
    well above blue, never the blue it used to be.
    """
    for size in (48, 256):
        pixels = _png_pixels((notify.ICON.parent / f"ponos-{size}.png").read_bytes())
        vivid = [(r, g, b) for r, g, b, a in pixels if a > 200 and max(r, g, b) - min(r, g, b) > 80]
        assert vivid, f"ponos-{size}.png has no colour at all"
        orange = sum(1 for r, g, b in vivid if r > b + 60)
        assert orange > len(vivid) * 0.6, (
            f"ponos-{size}.png is not the orange mascot ({orange}/{len(vivid)})"
        )
    script = (ROOT / "scripts/mascot.mjs").read_text(encoding="utf-8")
    assert "'src', 'ponos', 'icons'" in script, "the desktop icons are not written from the mascot"


@case
def the_app_icons_that_may_be_drawn_on_any_ground_are_cut_out_not_black_squares():
    """Chrome drew the installed app on a black square: the "any" icons had a #141414 ground.

    An "any" icon is drawn as it is, so it is RGBA with transparent corners and a
    margin around the robot; the maskable one and the iOS one keep a ground (the
    platform crops or fills them), the brand's, the same for both.
    """
    pwa = ROOT / "frontend/public/pwa"
    manifest = json.loads(
        (ROOT / "frontend/public/manifest.webmanifest").read_text(encoding="utf-8")
    )
    kept = {icon["src"].rsplit("/", 1)[1] for icon in manifest["icons"] if icon["purpose"] == "any"}
    assert kept == {"icon-192.png", "icon-512.png"}, kept
    for name in sorted(kept):
        assert (pwa / name).read_bytes()[25] == 6, f"{name} has no alpha channel"
        pixels = _png_pixels((pwa / name).read_bytes())
        side = int(len(pixels) ** 0.5)
        for x, y in ((0, 0), (side - 1, 0), (0, side - 1), (side - 1, side - 1)):
            assert pixels[y * side + x][3] == 0, f"{name} has an opaque corner at {x},{y}"
        margin = side // 40
        edge = [pixels[y * side + x] for y in (margin,) for x in range(side)]
        assert all(p[3] == 0 for p in edge), f"{name}: the robot touches the top edge"
    grounds = set()
    for name in ("icon-maskable-512.png", "apple-touch-icon.png"):
        pixels = _png_pixels((pwa / name).read_bytes())
        assert all(p[3] == 255 for p in pixels[:64]), f"{name} must keep a plain ground"
        grounds.add(pixels[0])
    assert len(grounds) == 1, f"the maskable and the iOS icon differ in ground: {grounds}"
    colour = "#{:02x}{:02x}{:02x}".format(*grounds.pop()[:3])
    assert colour == manifest["background_color"] == manifest["theme_color"], colour


# -- the bell ----------------------------------------------------------------


@case
def only_the_moments_that_need_you_ring_the_bell():
    from ponos import notifications

    assert notifications.kind_of("review") == "review"
    assert notifications.kind_of("failed") == "failed"
    assert notifications.kind_of("blocked", "session.question") == "question"
    assert notifications.kind_of("blocked", "worktree.interrupted") == "question"
    assert notifications.kind_of("blocked", "merge.checks-failed") == "ci"
    assert notifications.kind_of("blocked", "merge.refused") == "blocked"
    assert notifications.kind_of("blocked") == "question", (
        "a stop with no cause is a question asked"
    )
    for routine in ("published", "merged", "read", "prepared", "waiting", "requeued"):
        assert notifications.kind_of(routine) == "", routine


@case
def the_bell_keeps_what_is_unread_once_and_forgets_what_was_read_after_thirty_days(state_home):
    from ponos import notifications

    notifications.add("question", "a", "Le header")
    notifications.add("question", "a", "Le header")  # asked twice before anyone looked
    notifications.add("review", "a", "Le header")
    notifications.add("routine", "a", "never")
    heard = notifications.recent()
    assert heard["unread"] == 2
    assert [item["kind"] for item in heard["items"]] == ["review", "question"], "newest first"
    assert all(item["read"] is False and item["ticket"] == "a" for item in heard["items"])

    notifications.read(heard["items"][0]["id"])
    assert notifications.recent()["unread"] == 1
    notifications.add("review", "a", "Le header")  # read: a new one may ring
    assert notifications.recent()["unread"] == 2

    notifications.read()
    heard = notifications.recent()
    assert (
        heard["unread"] == 0 and len(heard["items"]) == 3 and all(i["read"] for i in heard["items"])
    )

    old = (datetime.now(UTC) - timedelta(days=31)).isoformat(timespec="seconds")
    with db.transaction() as connection:
        connection.execute(
            "UPDATE notifications SET read_at = ? WHERE id = ?", (old, heard["items"][2]["id"])
        )
    notifications.read()
    assert len(notifications.recent()["items"]) == 2, "read more than thirty days ago: purged"


@case
def the_bell_lets_go_of_a_ticket_that_left_the_column_it_rang_for(state_home):
    """Unblocked, merged, done: what rang for it no longer asks for anything."""
    from ponos import notifications

    notifications.add("question", "answered", "Les caps du moment")
    notifications.add("review", "merged", "Une page Objectifs")
    notifications.add("review", "reading", "Still to read")
    notifications.add("ci", "red", "Still red")
    notifications.add("failed", "shared", "Failed, on a board whose blocked and failed are one")
    notifications.add("blocked", "gone", "Not on the board any more")
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat(timespec="seconds")
    with db.transaction() as connection:
        connection.execute("UPDATE notifications SET at = ?", (old,))
    # Rung a moment ago: the board read may not show the block yet.
    notifications.add("question", "early", "Asked just now")
    # Rung a moment ago too, but the board was edited after it: it is the move.
    notifications.add("question", "quick", "Answered at once")
    later = (datetime.now(UTC) + timedelta(minutes=1)).isoformat(timespec="seconds")

    notifications.settle(
        [
            {"id": "answered", "column": "done", "edited": old},
            {"id": "merged", "column": "done", "edited": old},
            {"id": "reading", "column": "review", "edited": old},
            {"id": "red", "column": "blocked", "edited": old},
            {"id": "shared", "column": "blocked", "edited": old},
            {"id": "early", "column": "running", "edited": old},
            {"id": "quick", "column": "ready", "edited": later.replace("+00:00", "Z")},
        ]
    )
    heard = notifications.recent()
    unread = {item["ticket"] for item in heard["items"] if not item["read"]}
    assert unread == {"reading", "red", "shared", "gone", "early"}, unread
    assert heard["unread"] == 5
    assert len(heard["items"]) == 8, "read, not deleted"


@case
def a_question_a_review_and_a_failure_ring_the_bell_but_a_dry_run_does_not(state_home):
    from ponos import notifications

    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config("")
    # The bell is what is under test: a real notification here would land on the
    # screen of whoever runs the suite, titled "Question · t".
    runner.config.notify.desktop = False
    runner.quiet = True
    ticket = type(
        "T",
        (),
        {
            "page": notion.Page(id=TICKET, url="u", title="t"),
            "id": TICKET,
            "title": "t",
            "url": "u",
        },
    )()
    runner.dry_run = True
    runner._tell("done", ticket, "review", "branch")
    assert notifications.recent()["unread"] == 0
    runner.dry_run = False
    runner._tell("done", ticket, "published", "merged")
    assert notifications.recent()["unread"] == 0, "routine"
    runner._tell("blocked", ticket, "blocked", "Which?", ask=True, code="session.question")
    runner._tell("done", ticket, "review", "branch")
    assert [i["kind"] for i in notifications.recent()["items"]] == ["review", "question"]
