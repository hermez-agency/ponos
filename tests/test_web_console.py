"""`web/console.py`: a conversation with the workspace, and what a message carries."""

from __future__ import annotations

import http.client
import io
import json
import os
import re
import select
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from email.message import Message
from pathlib import Path
from typing import Any

import httpx
from support import (
    FRONTEND,
    _bare_api,
    _config,
    _http_answering,
    _state_home,
    _TalkClient,
    case,
)

from ponos import openrouter, session
from ponos.__main__ import subcommands
from ponos.web import attachments as web_attachments
from ponos.web import chats as web_chats
from ponos.web import console as web_console

# -- the web console ---------------------------------------------------------


@case
def a_typed_command_is_split_without_a_shell() -> None:
    """No shell means no metacharacter: the words go to execve as they are."""
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    assert commands.parse(">status") == ["status"]
    assert commands.parse("history -n 5") == ["history", "-n", "5"]
    # A quoted argument stays one argument, accents and spaces included.
    assert commands.parse('logs "à faire"') == ["logs", "à faire"]


@case
def a_command_the_cli_does_not_have_is_refused() -> None:
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    for line in ("rm -rf /", "run; rm -rf /", "sh -c whoami", "../../bin/sh"):
        try:
            commands.parse(line)
        except ValueError:
            continue
        raise AssertionError(f"{line!r} should not have been accepted")


@case
def the_commands_that_would_hang_a_browser_are_not_offered() -> None:
    """`config` opens an editor and `service` starts and stops the console itself.

    Both are refused *and* left out of the list the error message offers: naming
    a verb and then refusing it is a small lie told to somebody already lost.
    """
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    for verb in web_console.REFUSED:
        assert verb not in commands.allowed
        try:
            commands.parse(verb)
        except ValueError as error:
            assert verb in str(error)
        else:
            raise AssertionError(f"{verb} should have been refused")
    assert "status" in commands.allowed


@case
def the_console_runs_what_it_lists_and_nothing_the_cli_grows_later() -> None:
    """A list written down, not the parser read back.

    Deriving the verbs from the parser made every new command something a
    browser could start. `run` starts Claude sessions that outlive the command's
    timeout, `update` swaps the code the console runs on, `clean` deletes the
    worktree a session is standing in: none of them is typed into a web page.
    """
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    assert set(commands.allowed) <= set(web_console.OFFERED)
    assert set(commands.allowed) <= set(subcommands()), "never a verb the CLI does not have"
    for verb in ("run", "update", "clean", "service"):
        assert verb not in commands.allowed, verb
        try:
            commands.parse(f"{verb} --force")
        except ValueError as error:
            assert verb in str(error), error
        else:
            raise AssertionError(f"{verb} should have been refused")
    grown = web_console.Commands(lambda *a, **k: None, (*subcommands(), "wipe"))
    assert "wipe" not in grown.allowed, "a verb added to the CLI is not offered by itself"


@case
def a_command_that_runs_too_long_takes_what_it_started_with_it() -> None:
    """The timeout ends the command's process group, not only its leader.

    `process.kill` used to stop the Python the console started and leave its
    children — a Claude session, from `run` — running unowned. The shell below
    starts a child of its own and waits on it; both have to be gone.
    """
    events: list[tuple[str, dict[str, Any]]] = []
    commands = web_console.Commands(lambda kind, **said: events.append((kind, said)), ())
    commands.timeout = 1
    with tempfile.TemporaryDirectory() as directory:
        marker = Path(directory) / "child"
        script = f"sleep 60 & echo $! > {marker}; echo started; wait"
        started = time.monotonic()
        commands._stream(["sh", "-c", script])
        took = time.monotonic() - started
        child = int(marker.read_text().strip())

    assert took < 30, f"the watchdog did not end the command ({took:.0f}s)"
    assert events[-1] == ("command", {"stage": "ended", "code": events[-1][1]["code"]})
    assert events[-1][1]["code"] != 0
    assert any("stopped after" in said.get("text", "") for _, said in events), events
    # SIGKILL is delivered, not instantaneous: on a loaded machine the child may
    # take seconds to be scheduled and die. A pidfd turns readable the moment it
    # has, whatever the load; the bound only keeps a child that was never
    # killed from outliving it — its `sleep 60` is still running past 25s more.
    try:
        handle = os.pidfd_open(child)
    except ProcessLookupError:
        return  # gone entirely
    try:
        ended = select.select([handle], [], [], 25)[0]
    finally:
        os.close(handle)
    assert ended, f"the child is still running: {Path(f'/proc/{child}/stat').read_text()}"


@case
def following_a_log_is_dropped_rather_than_left_to_hang() -> None:
    """`logs -f` never returns, and the live panel already is that feed."""
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    assert commands.parse("logs -f") == ["logs"]
    assert commands.parse("logs abc123 --follow") == ["logs", "abc123"]


# -- what a message to the workspace carries ----------------------------------


class _Chat(web_console.Chat):
    """A conversation that keeps the prompts its session was given and the events it sent."""

    prompts: list[str]
    events: list[tuple[str, dict[str, Any]]]


class _Chats(web_console.Chats):
    """The conversations, each one sharing the same record of prompts and events."""

    prompts: list[str]
    events: list[tuple[str, dict[str, Any]]]

    def _make(self, identifier: str, row: dict[str, Any] | None = None) -> web_console.Chat:
        chat = _Chat(self, identifier, row)
        chat.prompts = self.prompts
        chat.events = self.events
        return chat


def _again(chat: _Chat, identifier: str) -> _Chat:
    """Another conversation of the same console, by its name."""
    found = chat.chats.get(identifier)
    assert isinstance(found, _Chat)
    return found


def _fresh(chat: _Chat, like: str = "") -> _Chat:
    """A new conversation of the same console."""
    found = chat.chats.create(like)
    assert isinstance(found, _Chat)
    return found


@contextmanager
def _chat(body: str = "", **constants: Any) -> Iterator[_Chat]:
    """A Chat whose Claude session is a function, in a throwaway state directory."""
    with _state_home():
        prompts: list[str] = []
        events: list[tuple[str, dict[str, Any]]] = []
        original_run, original_available = session.run, session.available

        def run(prompt: str, **_: Any) -> session.Outcome:
            prompts.append(prompt)
            return session.Outcome(True, False, "sid", "", Path("/dev/null"), answer="seen")

        session.run = run
        session.available = lambda: "/usr/bin/claude"
        try:
            chats = _Chats(
                _config(body, **constants), lambda kind, **said: events.append((kind, said))
            )
            chats.prompts = prompts
            chats.events = events
            chat = chats.create()
            assert isinstance(chat, _Chat)
            yield chat
        finally:
            session.run, session.available = original_run, original_available


def _said_to(chat: _Chat) -> str:
    """The prompt of the last turn, once its thread has answered."""
    for _ in range(200):
        if not chat.busy:
            break
        time.sleep(0.01)
    return chat.prompts[-1]


@case
def a_message_of_words_alone_reaches_the_session_as_it_was_typed() -> None:
    with _chat() as chat:
        chat.send("what is on the board?")
        prompt = _said_to(chat)
        assert prompt.endswith("what is on the board?")
        assert "Attached to this message" not in prompt
        assert chat.history()[0] == {
            **chat.history()[0],
            "role": "you",
            "text": "what is on the board?",
        }
        assert "attachments" not in chat.history()[0], "no files, no empty list"


@case
def an_image_travels_as_a_path_the_session_reads() -> None:
    """Claude Code takes no file in a request: it reads one from the disk."""
    with _chat() as chat:
        png = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        said = chat.attach("capture d'écran.png", io.BytesIO(png), len(png))
        assert said["kind"] == "image" and said["type"] == "image/png" and said["size"] == len(png)
        kept = chat.attachment(said["id"]).path
        assert kept.read_bytes() == png
        assert kept.is_relative_to(web_console.attachments_dir()), (
            "under the state, never a repository"
        )
        chat.send("what is wrong on this screen?", [said["id"]])
        prompt = _said_to(chat)
        assert str(kept) in prompt, "the absolute path is what the session is given"
        assert "Read tool" in prompt
        assert chat.history()[0]["attachments"][0]["id"] == said["id"]
        sent = [said for kind, said in chat.events if said.get("stage") == "sent"][0]
        assert sent["attachments"][0]["name"] == said["name"], "the other tab draws it too"


@case
def a_document_goes_with_or_without_words() -> None:
    with _chat() as chat:
        pdf = b"%PDF-1.7\n" + b"0" * 50
        said = chat.attach("spec.pdf", io.BytesIO(pdf), len(pdf))
        sheet = chat.attach("../../etc/budget.xlsx", io.BytesIO(b"PK" * 10), 20)
        assert sheet["name"] == "budget.xlsx", "only the last component of a name is kept"
        chat.send("", [said["id"], sheet["id"]])
        prompt = _said_to(chat)
        assert "spec.pdf" in prompt and "A PDF" in prompt
        assert "budget.xlsx" in prompt and "Office file" in prompt


@case
def a_video_is_looked_at_through_frames_or_said_to_be_unseen() -> None:
    with _chat() as chat:
        said = chat.attach("clip.mp4", io.BytesIO(b"\x00" * 64), 64)
        video = chat.attachment(said["id"])
        original = web_attachments.ffmpeg
        web_attachments.ffmpeg = lambda: ""
        try:
            unseen = web_attachments.brief([video])
        finally:
            web_attachments.ffmpeg = original
        assert "ffmpeg is not installed" in unseen and "rather than guess" in unseen


@case
def a_file_past_the_limit_or_of_the_wrong_kind_is_refused_with_a_reason() -> None:
    with _chat(web={"attachment_max_mb": 1}) as chat:
        heavy = 2 * 1024 * 1024
        try:
            chat.attach("film.mov", io.BytesIO(b""), heavy)
        except web_attachments.TooLarge as error:
            assert "web.attachment_max_mb" in str(error) and "2 MB" in str(error)
        else:
            raise AssertionError("a file past the limit was kept")
        for name in ("page.html", "logo.svg", "script"):
            try:
                chat.attach(name, io.BytesIO(b"<x>"), 3)
            except ValueError as error:
                assert "not a kind of file" in str(error)
            else:
                raise AssertionError(f"{name} was kept")
        try:
            chat.send("look", ["0123456789ab"])
        except LookupError:
            pass
        else:
            raise AssertionError("a message whose file is gone was sent without it")
        assert not chat.history(), "refused whole"


@case
def a_new_conversation_leaves_the_old_one_its_files_until_it_is_deleted() -> None:
    with _chat() as chat:
        chat.send("look at this")
        _said_to(chat)
        said = chat.attach("a.png", io.BytesIO(b"png"), 3)
        chat.send("and this one")
        _said_to(chat)
        old, folder = chat.id, chat.folder().path
        assert folder.is_dir()
        chat = _fresh(chat)
        assert folder.is_dir(), "the old conversation is still in the list, with its files"
        try:
            chat.attachment(said["id"])
        except LookupError:
            pass
        else:
            raise AssertionError("the new conversation reads the old one's files")
        again = chat.attach("b.png", io.BytesIO(b"png"), 3)
        assert chat.folder().path != folder, "a new conversation, a new folder"
        assert chat.attachment(again["id"]).name == "b.png"
        chat.chats.delete(old)
        assert not folder.exists(), "deleting a conversation takes its files with it"
        assert [item["id"] for item in chat.chats.sessions()] == [], (
            "the new one has said nothing yet"
        )


@case
def conversations_are_listed_reopened_renamed_and_searched() -> None:
    with _chat() as chat:
        chat.send("How do I rotate the console token?\nSecond line")
        _said_to(chat)
        first = chat.id
        chats = chat.chats
        assert chat.title == "How do I rotate the console token?", chat.title
        chat = _fresh(chat)
        assert chat.history() == [] and chat.session_id == ""
        chat.send("Draft the release notes")
        _said_to(chat)
        second = chat.id
        listed = chats.sessions()
        assert [item["id"] for item in listed] == [second, first], "the latest first"
        assert [item["id"] for item in chats.sessions("console")] == [first]
        assert chats.sessions("console")[0]["matched"] == "title"
        assert chats.sessions("seen")[0]["matched"] == "content", "the answers are searched too"
        assert chats.sessions("100%") == [], "a wildcard is a character"
        chats.rename(first, "  Token   rotation ")
        assert chats.sessions("rotation")[0]["title"] == "Token rotation"
        chats.link(first, " Website ")
        assert chats.sessions("website")[0]["project"] == "Website", "found by its project too"
        chat = _again(chat, first)
        assert chat.id == first and chat.history()[0]["text"].startswith("How do I rotate")
        chat.send("and then?")
        assert "and then?" in _said_to(chat), "the session is resumed, without the brief again"
        assert chat.prompts[-1].startswith("[This conversation is about the project “Website”.]")
        assert chat.session_id and chat.turns == 2
        try:
            chats.get("0123456789ab")
        except LookupError:
            pass
        else:
            raise AssertionError("opened a conversation that does not exist")
        chats.delete(first)
        assert [item["id"] for item in chats.sessions()] == [second]
        try:
            chats.get(first)
        except LookupError:
            pass
        else:
            raise AssertionError("a deleted conversation is still held")


@case
def a_conversation_keeps_its_model_and_the_settings_name_the_default() -> None:
    with _chat(web={"chat_model": "haiku"}) as chat:
        assert chat.effective_model() == "haiku", "the setting is the default of a new session"
        chat.choose("opus")
        assert chat.state()["model"] == "opus"
        chat.send("hello")
        _said_to(chat)
        first = chat.id
        other = _fresh(chat, first)
        assert other.effective_model() == "opus", "a new session keeps the model that was chosen"
        other.choose("sonnet")
        assert chat.effective_model() == "opus", "and the other one remembers its own"
        chat.choose("")
        assert chat.effective_model() == "haiku"
        for refused in ("openai/gpt-5", "--dangerous", "a b"):
            try:
                chat.choose(refused)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{refused} was accepted")
        offered = chat.chats.models()
        assert [item["id"] for item in offered["claude"]] == ["opus", "sonnet", "haiku", "fable"]
        assert offered["openrouter"] == {"configured": False, "models": [], "error": ""}


@case
def an_openrouter_model_goes_through_openrouter_whatever_the_provider() -> None:
    body = '[openrouter]\nkey = "sk-or-test"\n'
    with _chat(body) as chat:
        seen: list[dict[str, Any]] = []
        original = session.run

        def run(prompt: str, **rest: Any) -> session.Outcome:
            seen.append(rest)
            return original(prompt, **rest)

        session.run = run
        chat.choose("deepseek/deepseek-r1")
        chat.send("hello")
        _said_to(chat)
        assert seen[-1]["model"] == "deepseek/deepseek-r1", "a slug is not rewritten"
        assert seen[-1]["environment"]["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test"
        assert seen[-1]["environment"]["ANTHROPIC_BASE_URL"].startswith("https://openrouter.ai")
        chat.choose("sonnet")
        chat.send("again")
        _said_to(chat)
        assert seen[-1]["model"] == "sonnet"
        assert "ANTHROPIC_BASE_URL" not in seen[-1]["environment"], (
            "a Claude model stays on the CLI"
        )
        assert chat.chats.models()["recent"] == ["sonnet"]


@case
def the_catalogue_of_openrouter_is_read_once_and_a_failure_is_said() -> None:
    from ponos import openrouter as router

    listed = {
        "id": "a/b",
        "name": "A: B",
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "supported_parameters": ["tools", "temperature"],
    }
    bare = {"id": "c/d", "pricing": {"prompt": "-1", "completion": "-1"}}
    answers = [json.dumps({"data": [listed, bare, {"name": "no id"}]}).encode()]
    opened: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        opened.append(str(request.url))
        return httpx.Response(200, content=answers[0])

    router._catalogue = {}
    try:
        with _http_answering(answer):
            settings = _config('[openrouter]\nkey = "k"\n').openrouter
            assert router.catalogue(settings) == [
                {"id": "a/b", "name": "A: B", "input": 3.0, "output": 15.0, "tools": True},
                {"id": "c/d", "name": "c/d", "input": None, "output": None, "tools": False},
            ], "the price per million tokens, and whether it uses tools"
            router.catalogue(settings)
            assert len(opened) == 1, "kept for a while"
            router._catalogue = {}
            answers[0] = b"nope"
            try:
                router.catalogue(settings)
            except router.Unavailable as error:
                assert "not JSON" in str(error)
            else:
                raise AssertionError("a page that is not JSON was read as a catalogue")
    finally:
        router._catalogue = {}


@case
def a_recording_is_transcribed_and_a_refusal_says_its_sentence() -> None:
    from ponos import openrouter as router
    from ponos import provider

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/key"):
            return httpx.Response(401, json={"error": {"message": "no"}})
        if json.loads(request.content)["input_audio"]["format"] == "webm":
            return httpx.Response(200, json={"text": " bonjour "})
        return httpx.Response(400, json={"error": {"message": "unsupported format"}})

    settings = _config('[openrouter]\nkey = "k"\n').openrouter
    with _http_answering(answer) as pauses:
        assert router.transcribe(settings, b"x", "audio/webm") == "bonjour"
        try:
            router.transcribe(settings, b"x", "audio/flac")
        except router.TranscriptionError as error:
            assert str(error).endswith("400 unsupported format"), error
        else:
            raise AssertionError("a refused recording was taken for a transcription")
        assert provider.openrouter_key("k").ok is False
        assert not pauses, "a refusal is an answer, not a silence"


@case
def a_stopped_session_takes_what_it_had_started_with_it() -> None:
    """Stop ends the CLI *and* the command it was running: nothing runs after it."""
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        ticks = home / "ticks"
        (home / "claude").write_text(
            "#!" + sys.executable + "\n"
            "import json, subprocess, sys, time\n"
            "print(json.dumps({'type': 'assistant', 'message': {'content': ["
            "{'type': 'text', 'text': 'Looking.'}]}}), flush=True)\n"
            # A long command, the way a session runs one: a child that writes.
            f"subprocess.Popen(['/bin/sh', '-c', 'while true; do echo x >> {ticks}; sleep 0.05; done'])\n"
            "time.sleep(60)\n"
        )
        (home / "claude").chmod(0o755)
        previous = os.environ["PATH"]
        os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
        stop = threading.Event()
        try:

            def press() -> None:
                while not ticks.exists():
                    time.sleep(0.02)
                stop.set()

            threading.Thread(target=press, daemon=True).start()
            began = time.monotonic()
            outcome = session.run(
                "look", cwd=home, log=home / "stopped.jsonl", timeout_minutes=1, stop=stop
            )
        finally:
            os.environ["PATH"] = previous
        assert time.monotonic() - began < 10, "stopped, not timed out"
        assert outcome.stopped and not outcome.ok and not outcome.blocked
        assert outcome.answer == "Looking.", "what it had said is kept"
        size = ticks.stat().st_size
        time.sleep(0.3)
        assert ticks.stat().st_size == size, "the command it had started still runs"


def _halting(chat: _Chat, exists: bool = True) -> list[dict[str, Any]]:
    """The `_chat` session, made to wait for Stop and say what it had done."""
    calls: list[dict[str, Any]] = []

    def run(prompt: str, **rest: Any) -> session.Outcome:
        calls.append(rest)
        chat.prompts.append(prompt)
        # Long past any load: a turn of these cases ends on the Stop they press.
        if rest["stop"].wait(60):
            return session.Outcome(
                False,
                False,
                rest["session_id"],
                "",
                Path("/dev/null"),
                answer="halfway",
                error="stopped",
                stopped=True,
            )
        return session.Outcome(
            True, False, rest["session_id"], "", Path("/dev/null"), answer="done"
        )

    session.run = run
    session.exists = lambda session_id: exists
    return calls


def _until(condition: Callable[[], object], what: str, seconds: float = 60) -> None:
    """Wait for a state the case can see, not for a length of time.

    A turn ends on a thread of its own, after a commit to `ponos.db`: on a busy
    machine that is seconds, not the hundredths it takes here. The bound is
    only there for a case that would never get there to fail rather than hang.
    """
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(what)
        time.sleep(0.01)


def _settled(chat: _Chat) -> None:
    _until(lambda: not chat.busy, "the turn never ended")


@case
def a_stopped_turn_is_kept_and_the_conversation_carries_on() -> None:
    original = session.exists
    try:
        with _chat() as chat:
            calls = _halting(chat)
            assert chat.stop()["busy"] is False, "nothing to stop is not an error"
            chat.send("rewrite everything")
            identifier = chat.session_id
            chat.stop()
            chat.stop()  # the double click
            _settled(chat)
            stages = [said["stage"] for kind, said in chat.events if kind == "chat"]
            assert stages.count("stopping") == 1, stages
            assert stages[-1] == "stopped"
            assert chat.history()[-1] == {
                **chat.history()[-1],
                "role": "stopped",
                "text": "halfway",
            }
            assert chat.session_id == identifier and chat.turns == 1
            chat.send("only the README, then")
            chat.stop()
            _settled(chat)
            assert calls[-1]["resume"] is True and calls[-1]["session_id"] == identifier
            # Read back from the disk, a stopped turn with nothing said stays.
            chat.messages.append(web_console.Message("stopped", ""))
            chat.save()
            again = web_console.Chats(chat.config, lambda *a, **k: None).get(chat.id)
            assert [message.role for message in again.messages][-1] == "stopped"
    finally:
        session.exists = original


@case
def a_first_turn_stopped_before_it_was_filed_starts_afresh() -> None:
    original = session.exists
    try:
        with _chat() as chat:
            calls = _halting(chat, exists=False)
            chat.send("hello")
            chat.stop()
            _settled(chat)
            assert chat.session_id == "", "nothing to resume"
            chat.send("hello again")
            chat.stop()
            _settled(chat)
            assert calls[-1]["resume"] is False, "a fresh session, not a stranger resumed"
            assert chat.prompts[-1] != "hello again", "with the brief, as a first turn is"
    finally:
        session.exists = original


@case
def files_nobody_closed_the_conversation_on_go_after_their_days(state_home: Path) -> None:
    root = web_console.attachments_dir()
    folder = web_attachments.Folder(root, "old")
    kept = folder.save("x.png", io.BytesIO(b"png"), 3, 100)
    fresh = folder.save("y.png", io.BytesIO(b"png"), 3, 100)
    old = time.time() - 9 * 86400
    os.utime(kept.path, (old, old))
    assert web_attachments.prune(root, 7) == 1
    assert not kept.path.exists() and fresh.path.exists()
    os.utime(fresh.path, (old, old))
    web_attachments.prune(root, 7)
    assert not folder.path.exists(), "an emptied folder goes too"


@case
def an_attachment_is_written_0600_in_a_folder_only_its_owner_enters(state_home: Path) -> None:
    """A pasted screenshot shows whatever was on the screen: nobody else's to read,
    whatever the umask, and a folder made before with the umask is tightened."""
    root = web_console.attachments_dir()
    root.mkdir(mode=0o775, parents=True)
    root.chmod(0o775)
    previous = os.umask(0o002)
    try:
        folder = web_attachments.Folder(root, "talk")
        kept = folder.save("screenshot.png", io.BytesIO(b"png"), 3, 100)
    finally:
        os.umask(previous)
    assert kept.path.stat().st_mode & 0o777 == 0o600, oct(kept.path.stat().st_mode)
    for directory in (folder.path, root, web_console.web_dir()):
        assert directory.stat().st_mode & 0o777 == 0o700, (directory, oct(directory.stat().st_mode))


@case
def dictation_without_a_key_says_what_is_missing() -> None:
    with _chat() as chat:
        state = chat.state()["dictation"]
        assert state["ready"] is False and "OpenRouter key" in state["why"]
        try:
            chat.chats.transcribe(b"audio", "audio/webm")
        except openrouter.Unavailable as error:
            assert "openrouter.key" in str(error)
        else:
            raise AssertionError("a transcription was attempted with no key")


@case
def dictation_is_sent_to_openrouter_in_the_language_asked_for() -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received: list[dict[str, Any]] = []

    class Whisper(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            received.append(
                {
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                }
            )
            answer = json.dumps({"text": " Bonjour la machine. "}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Whisper)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}/api/v1"
        with _chat('[openrouter]\nkey = "sk-or-test"\n', openrouter={"base_url": base}) as chat:
            assert chat.state()["dictation"]["ready"] is True
            said = chat.chats.transcribe(b"\x1aE\xdf\xa3", "audio/webm;codecs=opus", "fr-FR")
    finally:
        server.shutdown()
        server.server_close()
    assert said == {"text": "Bonjour la machine.", "language": "fr"}
    request = received[0]
    assert request["path"] == "/api/v1/audio/transcriptions"
    assert request["auth"] == "Bearer sk-or-test"
    assert request["body"]["model"] == "openai/whisper-1"
    assert request["body"]["input_audio"]["format"] == "webm"
    assert request["body"]["language"] == "fr"
    assert openrouter.audio_format("audio/mp4") == "m4a"


@case
def the_console_takes_a_file_as_a_raw_body_and_serves_it_back_sandboxed() -> None:
    """Over HTTP, with the guard header and the size limit the page cannot skip."""
    import urllib.error
    import urllib.request

    from ponos.web import app as web_app

    with _chat(web={"attachment_max_mb": 1}) as chat:
        api = _bare_api(_TalkClient([]))
        api.chat = chat.chats
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{console.server_address[1]}"

        def post(
            path: str, body: bytes, guard: bool = True, kind: str = "image/png"
        ) -> tuple[int, dict[str, Any], Message]:
            headers = {"Authorization": "Bearer tok", "Content-Type": kind}
            if guard:
                headers["X-Ponos"] = "1"
            request = urllib.request.Request(base + path, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read()), response.headers
            except urllib.error.HTTPError as error:
                return error.code, json.loads(error.read() or b"{}"), error.headers

        try:
            code, _, _ = post(f"/api/chat/{chat.id}/attachments?name=a.png", b"png", guard=False)
            assert code == 403, "a page elsewhere cannot drop a file here"
            code, said, _ = post(f"/api/chat/{chat.id}/attachments?name=a.png", b"\x89PNG")
            assert code == 200 and said["kind"] == "image", said
            code, refused, _ = post(
                f"/api/chat/{chat.id}/attachments?name=big.png", b"x" * (1024 * 1024 + 1)
            )
            assert code == 413 and "attachment_max_mb" in refused["error"], refused
            code, refused, _ = post("/api/chat/transcribe?lang=fr", b"audio", kind="audio/webm")
            assert code == 503 and "OpenRouter key" in refused["error"], refused

            request = urllib.request.Request(
                f"{base}/api/chat/attachments/{said['id']}", headers={"Authorization": "Bearer tok"}
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.read() == b"\x89PNG"
                assert response.headers["Content-Type"] == "image/png"
                assert "sandbox" in response.headers["Content-Security-Policy"]
            code, refused, _ = post(
                f"/api/chat/{chat.id}/attachments/{said['id']}/remove",
                b"{}",
                kind="application/json",
            )
            assert code == 200, refused
            try:
                urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as error:
                assert error.code == 404
            else:
                raise AssertionError("a removed file is still served")
        finally:
            console.shutdown()
            console.server_close()


@case
def the_console_speaks_a_sentence_and_plans_a_reply_and_says_why_it_cannot() -> None:
    """`/api/chat/speak` over HTTP: guarded like the rest, a WAV when Piper is there, a reason when not."""
    import urllib.error
    import urllib.request

    from test_speech import _piper

    from ponos import speech
    from ponos.web import app as web_app

    with _chat(speech={"speed": 120}) as chat:
        assert chat.state()["speech"]["ready"] is speech.available()
        api = _bare_api(_TalkClient([]))
        api.chat = chat.chats
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{console.server_address[1]}"

        def post(path: str, body: dict[str, Any], guard: bool = True, token: bool = True) -> Any:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = "Bearer tok"
            if guard:
                headers["X-Ponos"] = "1"
            request = urllib.request.Request(
                base + path, data=json.dumps(body).encode(), headers=headers, method="POST"
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, response.read(), response.headers
            except urllib.error.HTTPError as error:
                return error.code, error.read(), error.headers

        original = speech.available
        try:
            code, _, _ = post("/api/chat/speak", {"text": "Bonjour.", "lang": "fr"}, token=False)
            assert code in (401, 403), "the voice is behind the console's door"
            code, _, _ = post("/api/chat/speak", {"text": "Bonjour.", "lang": "fr"}, guard=False)
            assert code == 403, "a page elsewhere cannot make the runner speak"

            speech.available = lambda: False
            assert chat.state()["speech"]["ready"] is False
            assert "Piper" in chat.state()["speech"]["why"]
            code, body, _ = post("/api/chat/speak", {"text": "Bonjour.", "lang": "fr"})
            assert code == 503 and "piper-tts" in json.loads(body)["error"], body

            speech.available = original
            with _piper():
                code, body, headers = post(
                    "/api/chat/speak", {"text": "Bonjour **toi**.", "lang": "fr"}
                )
                assert code == 200 and headers["Content-Type"] == "audio/wav", (code, body)
                assert body[:4] == b"RIFF"
                code, body, _ = post("/api/chat/speak", {"text": "```\nx\n```", "lang": "fr"})
                assert code == 200, "a block of code is spoken as a pointer to the screen"
                code, body, _ = post("/api/chat/speak", {"text": "  ", "lang": "fr"})
                assert code == 400, body
            code, body, _ = post(
                "/api/chat/speak/plan",
                {
                    "text": "Voici le code :\n```\nx\n```\nFini. Et la suite",
                    "lang": "fr",
                    "final": False,
                },
            )
            planned = json.loads(body)
            assert code == 200 and planned["language"] == "fr", planned
            assert planned["sentences"] == [
                "Voici le code :",
                "Je t'ai mis le code à l'écran.",
                "Fini.",
            ]
        finally:
            speech.available = original
            console.shutdown()
            console.server_close()


@case
def the_message_bar_is_one_block_with_its_gestures_inside() -> None:
    """The bar is a component a ticket's thread can take, and the old form is gone.

    Read from the React source: what is checked is a decision about the page,
    which the bundle has minified away.
    """
    bar = "".join(
        path.read_text(encoding="utf-8")
        for path in [
            FRONTEND / "src/components/console/composer.tsx",
            *sorted((FRONTEND / "src/components/console/composer").glob("*.ts*")),
        ]
    )
    pane = (FRONTEND / "src/components/console/console-pane.tsx").read_text(encoding="utf-8")
    assert "export function Composer" in bar
    for gesture in ("PlusIcon", "MicIcon", "ArrowUpIcon", "onPaste", "rounded-full", "max-w-3xl"):
        assert gesture in bar, f"the bar lost {gesture}"
    assert "<Composer" in pane and "onDrop" in pane, "the drawer takes a dropped file"
    assert "<Textarea" not in pane, "the bare field is back"
    assert 't("Send")' not in pane, "a text button for sending is back under the field"
    assert "a sentence talks to your workspace ·" not in pane, "the permanent help line is back"
    tests = (FRONTEND / "src/lib/composer.test.ts").read_text(encoding="utf-8")
    for held in (
        "removed by its cross",
        "pasted screenshot",
        "starts with > is a command",
        "arrow is off",
    ):
        assert held in tests, f"nothing holds the bar to “{held}” any more"
    accepted = set(
        re.findall(
            r"^  (\w+): \"(?:image|video|document)\"",
            (FRONTEND / "src/lib/composer.ts").read_text(encoding="utf-8"),
            re.M,
        )
    )
    assert accepted == set(web_attachments.ACCEPTED), (
        "the page and the server accept different files"
    )


def _drained(chat: _Chat, turns: int) -> None:
    for _ in range(500):
        if len(chat.prompts) >= turns and not chat.busy and not chat.queue:
            return
        time.sleep(0.01)
    raise AssertionError("the queue never drained")


@case
def messages_sent_during_a_turn_wait_and_are_sent_in_order_after_it() -> None:
    with _chat() as chat:
        gate = threading.Event()
        original = session.run

        def run(prompt: str, **rest: Any) -> session.Outcome:
            chat.prompts.append(prompt)
            if len(chat.prompts) == 1:
                gate.wait(5)
            return session.Outcome(
                True, False, rest["session_id"], "", Path("/dev/null"), answer="seen"
            )

        session.run = run
        try:
            chat.send("the first part")
            chat.send("one more thing")
            state = chat.send("and another")
            assert [item["text"] for item in state["queue"]] == ["one more thing", "and another"]
            assert [message["text"] for message in chat.history()] == ["the first part"]
            waiting = state["queue"][1]["id"]
            chat.amend(state["queue"][0]["id"], "one more thing, reworded")
            chat.unqueue(waiting)
            chat.send("and the last")
            gate.set()
            _drained(chat, 3)
            assert [prompt.rsplit("\n", 1)[-1] for prompt in chat.prompts] == [
                "the first part",
                "one more thing, reworded",
                "and the last",
            ]
            assert [m["role"] for m in chat.history()] == ["you", "workspace"] * 3
            stages = [said["stage"] for kind, said in chat.events if kind == "chat"]
            assert "queue" in stages
        finally:
            session.run = original


@case
def a_stop_holds_the_queue_until_it_is_sent_or_thrown_away() -> None:
    original = session.exists
    try:
        with _chat() as chat:
            _halting(chat)
            chat.send("rewrite everything")
            chat.send("and the tests")
            chat.stop()
            _settled(chat)
            state = chat.state()
            assert state["held"] is True and len(state["queue"]) == 1
            assert len(chat.prompts) == 1, "nothing is sent on its own"
            released = chat.release()
            assert released["queue"] == [] and released["held"] is False
            # The released turn starts in its own thread: wait for its prompt.
            _until(lambda: len(chat.prompts) == 2, "the released message was never sent")
            assert chat.prompts[-1].endswith("and the tests")
            chat.stop()
            _settled(chat)
            chat.send("one for the bin")
            chat.send("and another")
            chat.stop()
            _settled(chat)
            assert chat.discard()["queue"] == []
            assert len(chat.prompts) == 3
            try:
                chat.unqueue("0123456789ab")
            except LookupError:
                pass
            else:
                raise AssertionError("a message already gone is not found")
    finally:
        session.exists = original


# -- several conversations at once --------------------------------------------


def _held_open(chat: _Chat) -> dict[str, threading.Event]:
    """The `_chat` session, made to wait for the Stop of *its own* conversation.

    The prompt is kept so that a case can tell which conversation has begun;
    each turn ends on its own Stop, or on `release`, whichever comes first.
    """
    gates: dict[str, threading.Event] = {}

    def run(prompt: str, **rest: Any) -> session.Outcome:
        chat.prompts.append(prompt)
        gate = gates.setdefault(prompt.rsplit("\n", 1)[-1], threading.Event())
        for _ in range(6000):
            if rest["stop"].is_set():
                return session.Outcome(
                    False,
                    False,
                    rest["session_id"],
                    "",
                    Path("/dev/null"),
                    answer="halfway",
                    error="stopped",
                    stopped=True,
                )
            if gate.wait(0.01):
                break
        return session.Outcome(
            True, False, rest["session_id"], "", Path("/dev/null"), answer="done"
        )

    session.run = run
    session.exists = lambda session_id: True
    return gates


@case
def two_conversations_answer_at_once_and_a_stop_reaches_only_its_own() -> None:
    original = session.exists
    try:
        with _chat() as first:
            gates = _held_open(first)
            second = _fresh(first)
            first.send("alpha")
            second.send("bravo")
            _until(lambda: len(first.prompts) == 2, "both turns should be running")
            assert first.busy and second.busy, "each carries its own run"
            assert first.turn is not second.turn and first._stop is not second._stop
            assert first.chats.running() == 2
            # Opening, renaming or listing never waits for a turn of another.
            listed = {item["id"]: item for item in first.chats.sessions()}
            assert listed[first.id]["busy"] and listed[second.id]["busy"]
            first.chats.rename(second.id, "Bravo")
            assert _again(first, second.id) is second
            first.stop()
            _settled(first)
            assert second.busy, "Stop on one does not stop the other"
            assert first.history()[-1]["role"] == "stopped"
            gates["bravo"].set()
            _settled(second)
            assert second.history()[-1]["text"] == "done"
            assert second.unread and first.unread, "both ended with an answer nobody has read"
            assert second.read()["unread"] is False
            events = [said for kind, said in first.events if kind == "chat"]
            assert {said["id"] for said in events} == {first.id, second.id}, "each event says whose"
    finally:
        session.exists = original


@case
def a_turn_past_the_limit_waits_in_its_conversation_for_a_place() -> None:
    original = session.exists
    try:
        with _chat(web={"chat_max_turns": 2}) as one:
            gates = _held_open(one)
            two, three = _fresh(one), _fresh(one)
            one.send("one")
            two.send("two")
            state = three.send("three")
            assert not three.busy and state["limited"] is True and len(state["queue"]) == 1
            assert state["running"] == 2 and state["limit"] == 2
            assert len(one.prompts) == 2, "the third message did not start"
            gates["one"].set()
            _until(lambda: three.busy, "the place that was freed was not given")
            assert three.state()["limited"] is False and three.queue == []
            gates["two"].set()
            gates["three"].set()
            _settled(two)
            _settled(three)
            assert [m["role"] for m in three.history()] == ["you", "workspace"]
    finally:
        session.exists = original


@case
def a_conversation_deleted_while_it_answers_is_stopped_and_never_written_back() -> None:
    original = session.exists
    try:
        with _chat() as chat:
            _held_open(chat)
            other = _fresh(chat)
            chat.send("doomed")
            other.send("kept")
            _until(lambda: len(chat.prompts) == 2, "both should be running")
            chat.chats.delete(chat.id)  # no “a turn is in flight”
            _settled(chat)
            assert other.busy, "the other conversation carries on"
            assert [item["id"] for item in chat.chats.sessions()] == [other.id], (
                "what the stopped turn said was not written back"
            )
            _until(lambda: web_chats.load(chat.id) is None, "the row came back")
            _again(chat, other.id).stop()
            _settled(other)
    finally:
        session.exists = original


@case
def a_name_the_server_forgot_is_a_blank_conversation_to_carry_on_in() -> None:
    with _chat() as chat:
        found = chat.chats.get("0123456789ab", blank=True)
        assert found.history() == [] and found.id == "0123456789ab"
        try:
            chat.chats.get("not-a-name", blank=True)
        except LookupError:
            pass
        else:
            raise AssertionError("any string was taken for the name of a conversation")


# -- in AG-UI ------------------------------------------------------------------


def _speaking(chat: _Chat) -> None:
    """The `_chat` session, made to say a sentence, call a tool, and answer."""

    def run(prompt: str, **rest: Any) -> session.Outcome:
        chat.prompts.append(prompt)
        said = {"type": "text", "text": "I read the board."}
        call = {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}}
        result = {"type": "tool_result", "tool_use_id": "toolu_1", "content": "board.md"}
        rest["on_event"]({"type": "assistant", "message": {"content": [said, call]}})
        rest["on_event"]({"type": "user", "message": {"content": [result]}})
        rest["on_event"](
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "13."}]}}
        )
        return session.Outcome(
            True, False, rest["session_id"], "", Path("/dev/null"), answer="13.", cost_usd=0.0123
        )

    session.run = run


def _agui(chat: _Chat) -> list[dict[str, Any]]:
    return [said["event"] for kind, said in chat.events if kind == "agui"]


@case
def a_turn_is_streamed_in_agui_and_kept_with_what_it_streamed() -> None:
    """The page's `useChat` reads the turn as it happens, and finds it again on reopening.

    The run is the page's: its message keeps the id `useChat` gave it, and the
    turn is said under the run id it asked for — so the tab that sent it
    recognises its own, and the others draw it from the snapshot.
    """
    with _chat() as chat:
        _speaking(chat)
        chat.run(
            {
                "threadId": chat.id,
                "runId": "run-1",
                "messages": [
                    {"id": "msg-1", "role": "user", "parts": [{"type": "text", "content": "count"}]}
                ],
            }
        )
        _settled(chat)
        events = _agui(chat)
        kinds = [event["type"] for event in events]
        assert kinds[:2] == ["MESSAGES_SNAPSHOT", "RUN_STARTED"], kinds
        assert kinds[-2:] == ["RUN_FINISHED", "MESSAGES_SNAPSHOT"], kinds
        assert events[1]["runId"] == "run-1" and events[1]["threadId"] == chat.id
        first = events[0]["messages"]
        assert [(m["id"], m["role"]) for m in first] == [("msg-1", "user")], first
        assert chat.prompts[-1].endswith("count")

        last = events[-1]["messages"]
        answer = last[-1]
        assert answer["role"] == "assistant"
        assert [part["type"] for part in answer["parts"]] == [
            "text",
            "tool-call",
            "tool-result",
            "text",
        ], answer["parts"]
        assert answer["metadata"]["ponos"]["cost"] == 0.0123
        assert answer["metadata"]["ponos"]["role"] == "workspace"

        # Reopened from the disk, the conversation hydrates the same.
        again = web_console.Chats(chat.config, lambda *a, **k: None).get(chat.id)
        hydrated = again.thread()
        assert hydrated["activeRun"] is None and hydrated["interrupts"] is None
        assert hydrated["messages"] == last
        # Another conversation of the same console has its own, and a blank one none.
        assert _fresh(chat).thread()["messages"] == []
        assert chat.thread()["messages"] == last


@case
def a_run_for_another_conversation_or_without_words_is_refused() -> None:
    with _chat() as chat:
        message = {"id": "m", "role": "user", "content": "hello"}
        try:
            chat.run({"threadId": "someone-else", "messages": [message]})
        except RuntimeError:
            pass
        else:
            raise AssertionError("a run for a conversation that is not open")
        try:
            chat.run({"threadId": chat.id, "messages": [{"role": "assistant", "content": "hi"}]})
        except ValueError:
            pass
        else:
            raise AssertionError("a run with nothing from the user")
        assert chat.prompts == [] and not _agui(chat)


@case
def a_conversation_from_before_parts_is_drawn_from_its_words() -> None:
    """Older transcripts have text alone: each message is one part, under a stable id."""
    with _chat() as chat:
        chat.messages = [
            web_console.Message("you", "how many?"),
            web_console.Message("workspace", "13."),
            web_console.Message("error", "claude not found in PATH"),
            web_console.Message("stopped", ""),
        ]
        ui = chat.ui()
        assert [message["id"] for message in ui] == [f"{chat.id}-{n}" for n in range(4)]
        assert ui[0]["parts"] == [{"type": "text", "content": "how many?"}]
        assert ui[1]["parts"] == [{"type": "text", "content": "13."}]
        assert ui[2]["parts"] == [] and ui[2]["metadata"]["ponos"]["error"].startswith("claude")
        assert ui[3]["parts"] == [] and ui[3]["metadata"]["ponos"]["role"] == "stopped"


@case
def another_agui_client_is_answered_the_run_itself_as_server_sent_events() -> None:
    """`Accept: text/event-stream`: the run, from `RUN_STARTED` to `RUN_FINISHED`."""
    from ponos.web import app as web_app

    with _chat() as chat:
        _speaking(chat)
        api = _bare_api(None)
        api.chat = chat.chats
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", console.server_address[1], timeout=10
            )
            body = {"threadId": chat.id, "messages": [{"role": "user", "content": "count"}]}
            connection.request(
                "POST",
                f"/api/chat/{chat.id}/agui",
                body=json.dumps(body),
                headers={
                    "Authorization": "Bearer tok",
                    "X-Ponos": "1",
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            assert response.status == 200, response.read()
            assert response.getheader("Content-Type", "").startswith("text/event-stream")
            events = [
                json.loads(line[len("data: ") :])
                for line in response.read().decode().splitlines()
                if line.startswith("data: ")
            ]
            connection.close()
        finally:
            console.shutdown()
            console.server_close()
        kinds = [event["type"] for event in events]
        assert kinds[0] == "RUN_STARTED" and kinds[-1] == "RUN_FINISHED", kinds
        assert "TOOL_CALL_START" in kinds and "MESSAGES_SNAPSHOT" not in kinds, kinds


def _posting(size: int) -> tuple[int, str]:
    """The status and the sentence of a run posted with `size` bytes of earlier thread."""
    from ponos.web import app as web_app

    with _chat() as chat:
        _speaking(chat)
        api = _bare_api(None)
        api.chat = chat.chats
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", console.server_address[1], timeout=20
            )
            history = [{"role": "assistant", "content": "x" * size}]
            body = {"threadId": chat.id, "messages": [*history, {"role": "user", "content": "go"}]}
            connection.request(
                "POST",
                f"/api/chat/{chat.id}/agui",
                body=json.dumps(body),
                headers={
                    "Authorization": "Bearer tok",
                    "X-Ponos": "1",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            raw = response.read().decode()
            connection.close()
            return response.status, raw
        finally:
            console.shutdown()
            console.server_close()


@case
def a_thread_over_a_megabyte_still_takes_a_new_message() -> None:
    """An AG-UI client posting the whole history is not refused for its length."""
    status, raw = _posting(1024 * 1024 + 1)
    assert status == 200, raw


@case
def a_body_far_too_large_is_refused_in_words_a_person_can_act_on() -> None:
    status, raw = _posting(33 * 1024 * 1024)
    assert status == 413, status
    assert "attachments" in json.loads(raw)["error"], raw
