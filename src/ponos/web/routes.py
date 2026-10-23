"""The console's API: what the page reads and writes, once the door is passed.

Every route here is behind the guard `app.py` puts in front of the whole
application — the token or a sign-in, the `Host` it was reached under, and on
a write the header no page elsewhere can set. Nothing in this module checks
any of it again, and nothing here may be reached without it: a route added
here is a route added behind the door.

Two things are said once, here, rather than in each route:

- **What a failure answers.** The `Api` raises what it raises — a `LookupError`
  for a ticket that is not there, a `RuntimeError` for a write that came too
  late — and `Answered` turns it into the status the page has always read,
  the same mapping for every route of a method. A read and a write do not
  map alike: a read has no "too late".
- **What a body is.** JSON, whatever the `Content-Type` said: the page and the
  scripts that post here never sent anything else, and a client that labelled
  it `application/x-www-form-urlencoded` — `urllib` does, by default — was
  understood. The models below say which fields a write reads, for the
  OpenAPI schema the page's types come from; they are lenient about the rest,
  as the dictionaries they replace were.

Every route is a plain `def`: the `Api` waits on Notion, git and processes,
and FastAPI runs such a route on a thread of its own — which is what
`http.server` did for every request.
"""

from __future__ import annotations

import json
import logging
import queue
import re
from collections.abc import Callable, Coroutine, Iterator
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.convertors import Convertor, register_url_convertor

from .. import config as config_module
from .. import journal, notifications, store, vault
from . import agui, answers, creation, github, mcp_setup, setup
from .api import Api

logger = logging.getLogger(__name__)

# Bodies are small — a ticket, a message, a command. Anything larger is a
# mistake, and reading it would be the mistake becoming ours.
MAX_BODY = 256 * 1024

# Except a picture, which is a file and not a message: the console shrinks it
# before sending, and this is Notion's own ceiling for one piece.
MAX_PICTURE = 20 * 1024 * 1024

# What a picture is served under. It is drawn by an <img> and never run: an SVG
# opened on its own, at this origin, would otherwise be a page with a script.
PICTURE_POLICY = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


class _Pattern(Convertor[str]):
    """A path segment matched against a pattern, handed over as it is.

    The routes' identifiers are matched as `http.server` matched them: a path
    whose segment is not a page id is no route at all — a 404 — rather than a
    route that refuses its argument.
    """

    def __init__(self, regex: str) -> None:
        self.regex = regex  # type: ignore[misc]  # one pattern per route, not per class

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


# A Notion page, with or without its dashes; a file of the conversation; a
# picture's slot; a log file's name.
register_url_convertor("page", _Pattern(r"[0-9a-fA-F-]{32,36}"))
register_url_convertor("attachment", _Pattern(r"[0-9a-f]{12}"))
register_url_convertor("slot", _Pattern(r"\w+"))
register_url_convertor("log", _Pattern(r"[\w.\-]+"))


def answer(payload: Any, code: int = 200) -> Response:
    """Every answer of the API, masked on its way to the page: see vault.py."""
    return Response(
        json.dumps(vault.masked(payload), ensure_ascii=False).encode(),
        status_code=code,
        media_type="application/json",
    )


def fail(code: int, message: str) -> Response:
    return answer({"error": message}, code)


def _first_line(error: BaseException) -> str:
    return (str(error).splitlines() or [""])[0]


def failure(error: Exception, request: Request) -> Response:
    """What a route that raised answers: the status the page reads it by.

    Called from the `except` that caught it: a 500 leaves its trace in the
    journal, which the answer — one line of JSON — does not carry.
    """
    if request.method == "GET":
        if isinstance(error, store.StoreError):
            return fail(502, f"the board: {_first_line(error)}")
        if isinstance(error, LookupError):
            return fail(404, str(error))
        return _crashed(error, request)
    if isinstance(error, config_module.ConfigError):
        return fail(400, _first_line(error))
    if isinstance(error, ValueError):
        return fail(400, str(error))
    if isinstance(error, LookupError):
        return fail(404, str(error))
    if isinstance(error, RuntimeError):
        return fail(409, str(error))
    if isinstance(error, FileNotFoundError):
        return fail(503, str(error))
    if isinstance(error, store.StoreError):
        return fail(502, f"the board: {_first_line(error)}")
    return _crashed(error, request)


def _crashed(error: Exception, request: Request) -> Response:
    logger.exception("console: %s %s failed", request.method, request.url.path)
    return fail(500, _first_line(error))


def refusal(error: RequestValidationError) -> Response:
    """A body that is not what the route reads, said the way every refusal is."""
    for problem in error.errors():
        if problem.get("type") == "json_invalid":
            return fail(400, "the body is not JSON")
        where = ".".join(str(part) for part in problem.get("loc", ())[1:])
        said = str(problem.get("msg", "invalid"))
        return fail(400, f"{where}: {said}" if where else said)
    return fail(400, "invalid request")


def _as_json(request: Request) -> Request:
    """The same request, its body labelled JSON — see the module's docstring."""
    headers = [(name, value) for name, value in request.scope["headers"] if name != b"content-type"]
    scope = {**request.scope, "headers": [*headers, (b"content-type", b"application/json")]}
    return Request(scope, request.receive)


class Answered(APIRoute):
    """A route of the API: its failures answered, its body read as JSON."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        reads_body = self.body_field is not None

        async def answered(request: Request) -> Response:
            if reads_body:
                try:
                    length = int(request.headers.get("content-length") or 0)
                except ValueError:
                    length = 0
                if length > MAX_BODY:
                    return fail(413, "a message is smaller than that")
                request = _as_json(request)
            try:
                return await handler(request)
            except HTTPException:
                raise
            except RequestValidationError as error:
                return refusal(error)
            except Exception as error:  # noqa: BLE001
                return failure(error, request)

        return answered


router = APIRouter(route_class=Answered)


def _api(request: Request) -> Api:
    api: Api = request.app.state.console.api
    return api


# -- what a write carries ------------------------------------------------------


class Payload(BaseModel):
    """A body the API reads some fields of, and tolerates anything else in."""

    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)


class NewTicket(Payload):
    title: str = ""
    body: str = ""
    project: str = ""
    ready: bool = True
    priority: Any = ""
    type: str = ""
    model: str = ""
    subtype: str = ""
    on: str = ""
    goal: str = ""


class On(Payload):
    on: str = ""


class Move(Payload):
    column: str = ""
    # The column the page last saw the ticket in: a move from a board that is
    # out of date is refused rather than applied.
    seen: str | None = Field(default=None, alias="from")


class Text(Payload):
    text: str = ""


class Chosen(Payload):
    key: str = ""
    number: int | None = 0
    text: str = ""
    model: str = ""
    titles: list[str] | None = None


class Line(Payload):
    line: str = ""


class Sent(Payload):
    text: str = ""
    attachments: list[str] | None = None


class Model(Payload):
    model: str = ""


class RunAgentInput(Payload):
    """What an AG-UI client posts to start a run: see `run_chat`."""

    threadId: str = ""  # noqa: N815 — AG-UI's own names
    runId: str = ""  # noqa: N815
    messages: list[Any] = Field(default_factory=list)
    forwardedProps: dict[str, Any] | None = None  # noqa: N815


class Title(Payload):
    title: str = ""


class ProjectLink(Payload):
    project: str = ""


class Scope(Payload):
    # Absent is every scope; "" is the workspace's.
    project: str | None = None


class Organisation(Payload):
    organisation: str = ""


class Slug(Payload):
    slug: str = ""


class Picture(Payload):
    url: str = ""
    emoji: str = ""
    remove: bool = False


class Probe(Payload):
    target: str = ""


class Read(Payload):
    # One notification, or all of them when absent.
    id: int | None = None


class Named(Payload):
    name: str = ""


# A body passed whole to the `Api`, which reads it field by field.
Fields = dict[str, Any]


# -- the API's reads -----------------------------------------------------------


@router.get("/api/state", response_model=answers.RunnerState)
def state(request: Request) -> Response:
    return answer(_api(request).state(local=request.state.asking.local()))


@router.get("/api/board", response_model=answers.Board)
def board(request: Request) -> Response:
    return answer(_api(request).board())


@router.get("/api/notifications", response_model=answers.Bell)
def recent_notifications() -> Response:
    return answer(notifications.recent())


@router.get("/api/projects", response_model=answers.Projects)
def projects(request: Request) -> Response:
    return answer(_api(request).all_projects())


@router.get("/api/projects/check", response_model=answers.ProjectCheck)
def projects_check(request: Request, repository: str = "", path: str = "") -> Response:
    return answer(_api(request).check_project(repository, path))


@router.get("/api/projects/{project_id:page}", response_model=answers.ProjectDetail)
def project(request: Request, project_id: str) -> Response:
    return answer(_api(request).project(project_id))


@router.get("/api/projects/{project_id:page}/brief", response_model=answers.ProjectBrief)
def project_brief(request: Request, project_id: str) -> Response:
    return answer(_api(request).project_brief(project_id))


@router.get("/api/projects/{project_id:page}/settings", response_model=answers.ProjectSettings)
def project_settings(request: Request, project_id: str) -> Response:
    return answer(_api(request).project_settings(project_id))


@router.get("/api/projects/{project_id:page}/image/{slot:slot}", response_class=Response)
def project_image(request: Request, project_id: str, slot: str) -> Response:
    data, kind = _api(request).picture(project_id, slot)
    return Response(
        data,
        media_type=kind,
        headers={
            "Content-Security-Policy": PICTURE_POLICY,
            "Cache-Control": "private, max-age=86400",
        },
    )


@router.get("/api/files/{file_id:page}", response_class=Response)
def file(request: Request, file_id: str) -> Response:
    return Response(
        b"",
        status_code=302,
        media_type="text/plain",
        headers={"Location": _api(request).attachment(file_id)},
    )


@router.get("/api/context", response_model=answers.Context)
def context(request: Request) -> Response:
    return answer(_api(request).context())


@router.get("/api/schedules", response_model=answers.Schedules)
def schedules(request: Request) -> Response:
    return answer(_api(request).schedules())


@router.get("/api/schedules/{schedule_id:page}/activity", response_model=answers.ScheduleActivity)
def schedule_activity(request: Request, schedule_id: str) -> Response:
    return answer(_api(request).schedule_activity(schedule_id))


@router.get("/api/schedules/{schedule_id:page}", response_model=answers.ScheduleDetail)
def schedule(request: Request, schedule_id: str) -> Response:
    return answer(_api(request).schedule(schedule_id))


@router.get("/api/goals", response_model=answers.Goals)
def goals(request: Request) -> Response:
    return answer(_api(request).goals())


@router.post("/api/goals", response_model=answers.GoalNamed)
def create_goal(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(_api(request).create_goal(str(payload.get("name", "")), payload))


@router.post("/api/goals/{goal_id:page}/delete", response_model=answers.GoalNamed)
def delete_goal(request: Request, goal_id: str) -> Response:
    return answer(_api(request).delete_goal(goal_id))


@router.post("/api/goals/{goal_id:page}", response_model=answers.GoalSaved)
def save_goal(
    request: Request, goal_id: str, payload: Fields = Body(default_factory=dict)
) -> Response:
    return answer(_api(request).save_goal(goal_id, payload))


@router.get("/api/ideas", response_model=answers.Ideas)
def ideas(request: Request, project: str = "") -> Response:
    # No `project` is the workspace's ideas, the dashboard's.
    return answer(_api(request).proposed_ideas(project))


@router.get("/api/ideas/all", response_model=answers.IdeaList)
def ideas_all(request: Request, project: str = "", scope: str = "") -> Response:
    # `scope=all` is every project's ideas and the workspace's together.
    return answer(_api(request).every_idea(None if scope == "all" else project))


@router.get("/api/ideas/schedule", response_model=answers.IdeasPlan)
def ideas_schedule(request: Request) -> Response:
    return answer(_api(request).planned.describe())


@router.get("/api/ideas/unscored", response_model=answers.Unscored)
def ideas_unscored(request: Request, project: str = "", scope: str = "") -> Response:
    # What scoring the ideas with none would take: said before it is started.
    return answer(_api(request).unscored_ideas(None if scope == "all" else project))


@router.get("/api/history", response_model=answers.History)
def history(request: Request) -> Response:
    return answer(_api(request).history())


@router.get("/api/disk", response_model=answers.Disk)
def disk(request: Request) -> Response:
    return answer(_api(request).disk())


@router.get("/api/health", response_model=answers.HealthReport)
def health(request: Request) -> Response:
    return answer(_api(request).health())


@router.get("/api/statistics", response_model=answers.Statistics)
def statistics(
    request: Request, start: str = Query("", alias="from"), to: str = "", project: str = ""
) -> Response:
    try:
        # No `project`, or a blank one, is the whole board.
        figures = _api(request).statistics(start, to, project or None)
    except ValueError as error:
        # A period that makes no sense, said as the page's mistake.
        return fail(400, str(error))
    return answer(figures)


@router.get("/api/chat", response_model=answers.Chat)
def chat(request: Request) -> Response:
    talk = _api(request).chat
    return answer({"messages": talk.history(), **talk.state()})


@router.get("/api/chat/agui", response_model=answers.ChatThread)
def chat_thread(request: Request, threadId: str = "") -> Response:  # noqa: N803
    """A conversation as `useChat` hydrates it, from Ponos's own storage."""
    return answer(_api(request).chat.thread(threadId))


@router.get("/api/chat/sessions", response_model=answers.ChatSessions)
def chat_sessions(request: Request, q: str = "") -> Response:
    return answer({"sessions": _api(request).chat.sessions(q)})


@router.get("/api/chat/models", response_model=answers.ChatModels)
def chat_models(request: Request) -> Response:
    return answer(_api(request).chat.models())


@router.get("/api/settings", response_model=answers.Settings)
def settings(request: Request) -> Response:
    return answer(_api(request).settings())


@router.get("/api/mcp", response_model=answers.McpOverview)
def mcp(request: Request) -> Response:
    asking = request.state.asking
    return answer(mcp_setup.overview(asking.loopback(), _api(request).config.web.url))


@router.get("/api/mcp/servers", response_model=answers.McpServers)
def mcp_servers() -> Response:
    return answer(mcp_setup.servers())


@router.get("/api/settings/folder", response_model=answers.Folder)
def settings_folder(request: Request, path: str = "") -> Response:
    try:
        return answer(_api(request).folder(path))
    except ValueError as error:
        return fail(400, str(error))


@router.get("/api/setup/summary", response_model=answers.SetupSummary)
def setup_summary(request: Request) -> Response:
    return answer(setup.summary(_api(request)))


@router.get("/api/setup/claude", response_model=answers.ClaudeLogin)
def setup_claude() -> Response:
    return answer(setup.claude_login())


@router.get("/api/setup/github", response_model=answers.SetupGithub)
def setup_github() -> Response:
    return answer(setup.github())


@router.get("/api/setup/notion", response_model=answers.Shared)
def setup_notion(request: Request) -> Response:
    return answer(setup.notion_shared(_api(request), {}))


@router.get("/api/setup/projects", response_model=answers.ProjectChoices)
def setup_projects(request: Request) -> Response:
    return answer(setup.project_choices(_api(request)))


@router.get("/api/setup/demo", response_model=answers.Demo)
def setup_demo(request: Request, id: str = "") -> Response:  # noqa: A002
    return answer(setup.demo_state(_api(request), id))


@router.get("/api/setup/doctor", response_model=answers.Doctor)
def setup_doctor() -> Response:
    return answer(setup.doctor())


@router.get("/api/github", response_model=answers.Github)
def github_status() -> Response:
    return answer(github.status())


@router.get("/api/tickets/{ticket_id:page}", response_model=answers.TicketDetail)
def ticket(request: Request, ticket_id: str) -> Response:
    return answer(_api(request).ticket(ticket_id))


@router.get("/api/tickets/{ticket_id:page}/talk", response_model=answers.Talk)
def ticket_talk(request: Request, ticket_id: str) -> Response:
    return answer(_api(request).talk(ticket_id))


@router.get("/api/tickets/{ticket_id:page}/decision", response_model=answers.Decision)
def ticket_decision(request: Request, ticket_id: str) -> Response:
    try:
        return answer(_api(request).decision(ticket_id))
    except ValueError as error:
        return fail(409, str(error))


@router.get("/api/tickets/{ticket_id:page}/runs", response_model=answers.Runs)
def ticket_runs(request: Request, ticket_id: str) -> Response:
    return answer(_api(request).runs(ticket_id))


@router.get("/api/tickets/{ticket_id:page}/transitions", response_model=answers.Transitions)
def ticket_transitions(request: Request, ticket_id: str) -> Response:
    return answer(_api(request).transitions(ticket_id))


@router.get("/api/runs/{run:int}/steps", response_model=answers.RunSteps)
def run_steps(
    request: Request, run: int, before: str = "", after: str = "", limit: str = ""
) -> Response:
    try:
        pages = {
            name: int(value or 0)
            for name, value in (("before", before), ("after", after), ("limit", limit))
        }
    except ValueError:
        return fail(400, "before, after and limit are numbers")
    return answer(
        _api(request).run_steps(
            run,
            before=pages["before"],
            after=pages["after"],
            limit=pages["limit"] or journal.PAGE,
        )
    )


@router.get("/api/logs", response_model=answers.Logs)
def logs(request: Request, ticket: str = "") -> Response:
    return answer(_api(request).logs(ticket))


@router.get("/api/service-log", response_model=answers.ServiceLog)
def service_log(request: Request, lines: str = "500") -> Response:
    return answer(_api(request).service_log(int(lines) if lines.isdigit() else 500))


@router.get("/api/logs/{name:log}", response_model=answers.LogSteps)
def log(request: Request, name: str) -> Response:
    return answer(_api(request).log(name))


# -- the API's writes ----------------------------------------------------------


@router.post("/api/projects/{project_id:page}/image/{slot:slot}", response_model=answers.Pictures)
async def set_project_image(request: Request, project_id: str, slot: str) -> Response:
    """A picture chosen — an address, an emoji, none — or sent whole, as the body.

    Both at one address: what the body is says which. A file is the body as it
    is, its type in `Content-Type` and its name in `X-Filename`.
    """
    api = _api(request)
    if not (request.headers.get("content-type") or "").startswith("image/"):
        try:
            payload = Picture.model_validate(json.loads(await _small(request) or b"{}"))
        except ValueError as error:
            return fail(400, str(error))
        chosen = store.Picture(url=payload.url.strip(), emoji=payload.emoji.strip())
        if chosen.removed and not payload.remove:
            return fail(400, "say which picture: a url, an emoji, or remove")
        try:
            said = await run_in_threadpool(api.set_picture, project_id, slot, chosen)
        except Exception as error:  # noqa: BLE001
            return failure(error, request)
        return answer(said)
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = -1
    if length <= 0 or length > MAX_PICTURE:
        return fail(413, f"a picture is sent whole, and under {MAX_PICTURE // (1024 * 1024)} MB")
    data = await request.body()
    kind = (request.headers.get("content-type") or "").split(";")[0].strip()
    name = re.sub(r"[^\w.\-]+", "-", unquote(request.headers.get("x-filename") or ""))[:80]
    picture = store.Picture(data=data, type=kind, name=name)
    try:
        said = await run_in_threadpool(api.set_picture, project_id, slot, picture)
    except ValueError as error:
        return fail(400, str(error))
    except store.StoreError as error:
        return fail(502, f"the board: {_first_line(error)}")
    except Exception as error:  # noqa: BLE001
        return _crashed(error, request)
    return answer(said)


async def _small(request: Request) -> bytes:
    """The body, refused past what a message may be."""
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY:
        raise ValueError("a message is smaller than that")
    return await request.body()


@router.post("/api/setup/done", response_model=answers.Ok)
def setup_done() -> Response:
    return answer(setup.finish())


@router.post("/api/setup/provider", response_model=answers.ProviderChecked)
def setup_provider(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(setup.save_provider(_api(request), payload))


@router.post("/api/setup/notion", response_model=answers.NotionProvisioned)
def setup_save_notion(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(setup.save_notion(_api(request), payload))


@router.post("/api/setup/notion/shared", response_model=answers.Shared)
def setup_notion_shared(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(setup.notion_shared(_api(request), payload))


@router.post("/api/setup/demo", response_model=answers.TicketCreated)
def setup_start_demo(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(setup.demo(_api(request), payload))


@router.post("/api/setup/channels", response_model=answers.ChannelsProvisioned)
def setup_channels(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(setup.save_channels(_api(request), payload))


@router.post("/api/github/connect", response_model=answers.GithubManifest)
def github_connect(
    request: Request, payload: Organisation = Body(default_factory=Organisation)
) -> Response:
    return answer(github.connect(request.state.asking.base(), payload.organisation))


@router.post("/api/github/token", response_model=answers.GithubTokenSaved)
def github_token(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(github.save_token(_api(request), payload))


@router.post("/api/github/token/forget", response_model=answers.GithubTokenForgotten)
def github_token_forget(request: Request) -> Response:
    return answer(github.forget_token(_api(request)))


@router.post("/api/github/disconnect", response_model=answers.GithubDisconnected)
def github_disconnect(payload: Slug = Body(default_factory=Slug)) -> Response:
    return answer(github.disconnect(payload.slug))


@router.post("/api/tickets", response_model=answers.TicketCreated)
def create_ticket(
    request: Request, payload: NewTicket = Body(default_factory=NewTicket)
) -> Response:
    return answer(
        _api(request).create_ticket(
            payload.title,
            payload.body,
            payload.project,
            payload.ready,
            payload.priority,
            payload.type,
            payload.model,
            payload.subtype,
            payload.on,
            payload.goal,
        )
    )


@router.post("/api/tickets/{ticket_id:page}/on", response_model=answers.TicketOn)
def set_ticket_on(
    request: Request, ticket_id: str, payload: On = Body(default_factory=On)
) -> Response:
    return answer(_api(request).set_on(ticket_id, payload.on))


@router.post("/api/tickets/{ticket_id:page}/goal", response_model=answers.TicketGoal)
def set_ticket_goal(
    request: Request, ticket_id: str, payload: Fields = Body(default_factory=dict)
) -> Response:
    return answer(_api(request).set_ticket_goal(ticket_id, str(payload.get("goal", ""))))


@router.post("/api/tickets/{ticket_id:page}/status", response_model=answers.Moved)
def set_ticket_status(
    request: Request, ticket_id: str, payload: Move = Body(default_factory=Move)
) -> Response:
    return answer(_api(request).set_status(ticket_id, payload.column, payload.seen))


@router.post("/api/tickets/{ticket_id:page}/talk", response_model=answers.Message)
def tell_ticket(
    request: Request, ticket_id: str, payload: Text = Body(default_factory=Text)
) -> Response:
    return answer(_api(request).tell(ticket_id, payload.text))


@router.post("/api/tickets/{ticket_id:page}/decision", response_model=answers.Decided)
def decide_ticket(
    request: Request, ticket_id: str, payload: Chosen = Body(default_factory=Chosen)
) -> Response:
    return answer(
        _api(request).decide(
            ticket_id,
            payload.key,
            number=payload.number or 0,
            text=payload.text,
            model=payload.model,
            titles=payload.titles or [],
        )
    )


@router.post("/api/command", response_model=answers.CommandAccepted)
def command(request: Request, payload: Line = Body(default_factory=Line)) -> Response:
    return answer(_api(request).commands.start(payload.line))


@router.post("/api/chat", response_model=answers.ChatState)
def send_chat(request: Request, payload: Sent = Body(default_factory=Sent)) -> Response:
    return answer(_api(request).chat.send(payload.text, payload.attachments or []))


@router.post("/api/chat/agui", response_model=answers.ChatState)
def run_chat(
    request: Request, payload: RunAgentInput = Body(default_factory=RunAgentInput)
) -> Response:
    """The chat's AG-UI door: a `RunAgentInput` in, the run's events out.

    The console's own page asks for JSON and reads the events where it reads
    everything else, on `/api/events` — one stream per tab, whatever it
    watches. Any other AG-UI client asks for `text/event-stream` and is
    answered the run itself, from `RUN_STARTED` to `RUN_FINISHED`: waiting
    behind the turn in flight first, if there is one.
    """
    talk = _api(request).chat
    given = payload.model_dump()
    if "text/event-stream" not in request.headers.get("accept", ""):
        return answer(talk.run(given))
    # Named here when the client did not: the stream follows its own run, and
    # not the next one that starts.
    run_id = given["runId"] = given.get("runId") or agui.new_id("run")
    channel = talk.listen()
    try:
        talk.run(given)
    except Exception:
        talk.unlisten(channel)
        raise

    def events() -> Iterator[bytes]:
        ours = False
        try:
            while True:
                try:
                    event = channel.get(timeout=15)
                except queue.Empty:
                    yield b": still here\n\n"
                    continue
                if event.get("type") == "RUN_STARTED":
                    ours = event.get("runId") == run_id
                if not ours:
                    continue
                said = json.dumps(event, ensure_ascii=False)
                yield f"data: {vault.mask(said)}\n\n".encode()
                if event.get("type") in ("RUN_FINISHED", "RUN_ERROR"):
                    return
        finally:
            talk.unlisten(channel)

    return StreamingResponse(
        events(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/api/chat/attachments/{identifier:attachment}/remove", response_model=answers.Detached
)
def remove_chat_attachment(request: Request, identifier: str) -> Response:
    return answer(_api(request).chat.detach(identifier))


@router.post("/api/chat/queue/send", response_model=answers.ChatState)
def send_queue(request: Request) -> Response:
    return answer(_api(request).chat.release())


@router.post("/api/chat/queue/discard", response_model=answers.ChatState)
def discard_queue(request: Request) -> Response:
    return answer(_api(request).chat.discard())


@router.post("/api/chat/queue/{identifier:attachment}/remove", response_model=answers.ChatState)
def remove_queued(request: Request, identifier: str) -> Response:
    return answer(_api(request).chat.unqueue(identifier))


@router.post("/api/chat/queue/{identifier:attachment}/edit", response_model=answers.ChatState)
def edit_queued(
    request: Request, identifier: str, payload: Sent = Body(default_factory=Sent)
) -> Response:
    return answer(_api(request).chat.amend(identifier, payload.text))


@router.post("/api/chat/stop", response_model=answers.ChatState)
def stop_chat(request: Request) -> Response:
    return answer(_api(request).chat.stop())


@router.post("/api/chat/reset", response_model=answers.ChatState)
def reset_chat(request: Request) -> Response:
    return answer(_api(request).chat.reset())


@router.post("/api/chat/model", response_model=answers.ChatState)
def choose_chat_model(request: Request, payload: Model = Body(default_factory=Model)) -> Response:
    return answer(_api(request).chat.choose(payload.model))


@router.post("/api/chat/sessions/{identifier:attachment}/open", response_model=answers.ChatState)
def open_chat_session(request: Request, identifier: str) -> Response:
    return answer(_api(request).chat.open(identifier))


@router.post("/api/chat/sessions/{identifier:attachment}/rename", response_model=answers.ChatState)
def rename_chat_session(
    request: Request, identifier: str, payload: Title = Body(default_factory=Title)
) -> Response:
    return answer(_api(request).chat.rename(identifier, payload.title))


@router.post("/api/chat/sessions/{identifier:attachment}/project", response_model=answers.ChatState)
def link_chat_session(
    request: Request, identifier: str, payload: ProjectLink = Body(default_factory=ProjectLink)
) -> Response:
    return answer(_api(request).chat.link(identifier, payload.project))


@router.post("/api/chat/sessions/{identifier:attachment}/delete", response_model=answers.ChatState)
def delete_chat_session(request: Request, identifier: str) -> Response:
    return answer(_api(request).chat.delete(identifier))


@router.post("/api/projects", response_model=answers.Project)
def create_project(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    try:
        return answer(_api(request).create_project(payload))
    except creation.Refused as error:
        # Under the field it is about, as the form draws a refusal.
        said = str(error)
        violation = {"propertyPath": error.field, "message": said}
        return answer({"error": said, "violations": [violation]}, 400)


@router.post("/api/projects/{project_id:page}/delete", response_model=answers.ProjectDeleted)
def delete_project(
    request: Request, project_id: str, payload: Fields = Body(default_factory=dict)
) -> Response:
    return answer(_api(request).delete_project(project_id, payload))


@router.post("/api/projects/{project_id:page}/settings", response_model=answers.ProjectSettings)
def save_project_settings(
    request: Request, project_id: str, payload: Fields = Body(default_factory=dict)
) -> Response:
    return answer(_api(request).save_project_settings(project_id, payload))


@router.post("/api/projects/{project_id:page}", response_model=answers.ProjectDetail)
def save_project(
    request: Request, project_id: str, payload: Fields = Body(default_factory=dict)
) -> Response:
    return answer(_api(request).save_project(project_id, payload))


@router.post("/api/settings", response_model=answers.Saved)
def save_settings(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(_api(request).save_settings(payload))


@router.post("/api/context", response_model=answers.ContextSaved)
def save_context(request: Request, payload: Text = Body(default_factory=Text)) -> Response:
    return answer(_api(request).save_context(payload.text))


@router.post("/api/schedules", response_model=answers.ScheduleNamed)
def create_schedule(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(_api(request).create_schedule(str(payload.get("name", "")), payload))


@router.post("/api/schedules/{schedule_id:page}/launch", response_model=answers.ScheduleLaunched)
def launch_schedule(request: Request, schedule_id: str) -> Response:
    return answer(_api(request).launch_schedule(schedule_id))


@router.post("/api/schedules/{schedule_id:page}/delete", response_model=answers.ScheduleNamed)
def delete_schedule(request: Request, schedule_id: str) -> Response:
    return answer(_api(request).delete_schedule(schedule_id))


@router.post("/api/schedules/{schedule_id:page}", response_model=answers.ScheduleSaved)
def save_schedule(
    request: Request, schedule_id: str, payload: Fields = Body(default_factory=dict)
) -> Response:
    return answer(_api(request).save_schedule(schedule_id, payload))


@router.post("/api/ideas/generate", response_model=answers.Found)
def generate_ideas(
    request: Request, payload: ProjectLink = Body(default_factory=ProjectLink)
) -> Response:
    return answer(_api(request).generate_ideas(payload.project))


@router.post("/api/ideas/schedule", response_model=answers.IdeasPlan)
def save_ideas_schedule(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(_api(request).planned.save(payload))


@router.post("/api/ideas", response_model=answers.Idea)
def create_idea(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(_api(request).create_idea(payload))


@router.post("/api/ideas/score", response_model=answers.Unscored)
def score_ideas(request: Request, payload: Scope = Body(default_factory=Scope)) -> Response:
    # No `project` at all is every scope's; "" the workspace's.
    return answer(_api(request).score_unscored_ideas(payload.project))


@router.post("/api/ideas/undo", response_model=answers.Undone)
def undo_idea(request: Request, payload: Scope = Body(default_factory=Scope)) -> Response:
    # A `project` (empty for the workspace's) takes back that scope's
    # last decision; none at all, the last decision of any.
    return answer(_api(request).undo_idea(payload.project))


@router.post("/api/ideas/{number:int}", response_model=answers.Idea)
def edit_idea(
    request: Request, number: int, payload: Fields = Body(default_factory=dict)
) -> Response:
    return answer(_api(request).edit_idea(number, payload))


@router.post("/api/ideas/{number:int}/keep", response_model=answers.Idea)
def keep_idea(request: Request, number: int) -> Response:
    return answer(_api(request).keep_idea(number))


@router.post("/api/ideas/{number:int}/discard", response_model=answers.Idea)
def discard_idea(request: Request, number: int) -> Response:
    return answer(_api(request).discard_idea(number))


@router.post("/api/ideas/{number:int}/ticket", response_model=answers.Idea)
def ticket_idea(request: Request, number: int) -> Response:
    return answer(_api(request).idea_ticket(number))


@router.post("/api/ideas/{number:int}/reopen", response_model=answers.Idea)
def reopen_idea(request: Request, number: int) -> Response:
    return answer(_api(request).reopen_idea(number))


@router.post("/api/disk/clean", response_model=answers.Cleaned)
def clean_disk(request: Request) -> Response:
    return answer(_api(request).clean())


@router.post("/api/health/fix", response_model=answers.HealthFixed)
def fix_health(request: Request, payload: Fields = Body(default_factory=dict)) -> Response:
    return answer(_api(request).fix_health(payload))


@router.post("/api/mcp/test", response_model=answers.McpTest)
def test_mcp(request: Request, payload: Probe = Body(default_factory=Probe)) -> Response:
    # The address tried is one of the two the tab offers, never one the page typed.
    web = _api(request).config.web
    address = f"{web.url.rstrip('/')}/mcp" if web.url else ""
    if payload.target != "public":
        address = f"{request.state.asking.loopback()}/mcp"
    return answer(mcp_setup.probe(address))


@router.post("/api/notifications/read", response_model=answers.Bell)
def read_notifications(request: Request, payload: Read = Body(default_factory=Read)) -> Response:
    return answer(_api(request).read_notifications(payload.id))


@router.post("/api/refresh", response_model=answers.Ok)
def refresh(request: Request) -> Response:
    _api(request).resynchronise()
    return answer({"ok": True})
