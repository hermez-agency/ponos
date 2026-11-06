"""The settings group: what `config.toml` says, read for what would surprise.

Secrets and keys, languages, validation, the vault, the console, the ideas:
each table read against what the runner will do with it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .. import config as config_module
from .. import idea_schedule, kinds, project_settings, speech, vault, vault_store, voice
from ..web import attempts
from .check import ERROR, INFO, OK, WARN, Check, _check


def _settings(config: config_module.Config) -> list[Check]:
    return [
        *_secrets(config),
        *_keys(config),
        *_retired(config),
        *_languages(config.runner),
        *_validation(config.runner),
        *_self_review(config.runner),
        *_vault(config),
        *_vault_store(),
        *_console(config),
        *_ideas(config.runner),
    ]


def _voice(settings: config_module.Speech) -> list[Check]:
    """The console's voice: Piper installed, and which voices are already downloaded."""
    title = "Voice"
    if not settings.enabled:
        return [_check("settings.voice", INFO, title, "Off: speech.enabled is false.")]
    if not speech.available():
        return [
            _check(
                "settings.voice",
                INFO,
                title,
                "Piper is not installed: the voice mode and the Listen buttons are greyed out.",
                steps=[
                    "Install the `voice` extra: `pip install piper-tts` in Ponos's environment."
                ],
            )
        ]
    names = (settings.voice_fr, settings.voice_en)
    missing = [name for name in names if not (speech.voice_dir() / f"{name}.onnx").exists()]
    if missing:
        return [
            _check(
                "settings.voice",
                OK,
                title,
                "Piper is installed; {{voices}} will be downloaded (about 60 MB each) into "
                "{{folder}} the first time they speak.",
                params={"voices": ", ".join(missing), "folder": str(speech.voice_dir())},
            )
        ]
    return [
        _check(
            "settings.voice",
            OK,
            title,
            "Piper is installed, with {{voices}}.",
            params={"voices": ", ".join(names)},
        )
    ]


def _secrets(config: config_module.Config) -> list[Check]:
    """Where the secrets are: never in config.toml, and nobody else's to read."""
    found: list[Check] = []
    target = config_module.secrets_path(config.path)
    title = "Secrets"
    if config.exposed:
        found.append(
            _check(
                "settings.secrets",
                ERROR,
                title,
                "{{file}} still holds {{keys}}: ignored, and moved to {{target}} at the next launch.",
                params={
                    "file": str(config.path),
                    "keys": ", ".join(config.exposed),
                    "target": str(target),
                },
                steps=["Start Ponos once (`ponos run`, or the console) to move them."],
            )
        )
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        found.append(
            _check(
                "settings.secrets",
                OK,
                title,
                "No secret in {{file}}, none in {{target}} either: the environment holds them.",
                params={"file": config.path.name, "target": target.name},
            )
        )
        return found
    if mode & 0o077:
        found.append(
            _check(
                "settings.secrets",
                ERROR,
                title,
                "{{target}} can be read by others ({{mode}}).",
                params={"target": str(target), "mode": oct(mode)[2:]},
                steps=["Run `chmod 600 {{target}}`."],
            )
        )
    elif not config.exposed:
        found.append(
            _check(
                "settings.secrets",
                OK,
                title,
                "Secrets in {{target}} (600), none in {{file}}.",
                params={"target": str(target), "file": config.path.name},
            )
        )
    return found


def _keys(config: config_module.Config) -> list[Check]:
    """A key of config.toml no table reads: a setting that does nothing, said rather than refused."""
    return [
        _check(
            "settings.keys",
            WARN,
            "Configuration",
            "{{file}}, line {{line}}: {{key}} is not a known key — did you mean {{match}}?"
            if match
            else "{{file}}, line {{line}}: {{key}} is not a known key.",
            params={"file": config.path.name, "line": str(line), "key": key, "match": match},
            cause="It is ignored, and its default applies.",
        )
        for line, key, match in config.unknown
    ]


def _retired(config: config_module.Config) -> list[Check]:
    """The keys of config.toml that are constants now: read as the default, and told once."""
    if not config.retired:
        return []
    names = ", ".join(key for _, key in config.retired)
    return [
        _check(
            "settings.retired",
            INFO,
            "Configuration",
            "{{file}} still holds {{count}} keys that are constants now ({{keys}}).",
            params={"file": config.path.name, "count": str(len(config.retired)), "keys": names},
            cause="They are ignored, and each one's default applies.",
            steps=["Delete those lines; the file keeps working as it is until then."],
        )
    ]


def _languages(settings: config_module.Runner) -> list[Check]:
    """Which language the reports and the console are in — and a name nobody speaks.

    A language the runner does not know is read as English rather than refused,
    which is right for a run and wrong to keep quiet about: `de` would otherwise
    look like a setting that does nothing.
    """
    found: list[Check] = []
    for key, asked in (("language", settings.language), ("app_language", settings.app_language)):
        if asked and not voice.known(asked):
            found.append(
                _check(
                    "settings.language",
                    WARN,
                    "Language",
                    "runner.{{key}} = “{{asked}}” is not a language spoken here: it is read as English.",
                    params={"key": key, "asked": asked},
                )
            )
    names = {"en": "English", "fr": "French"}
    shown = settings.interface_language()
    params = {
        "reports": names[voice.understood(settings.language)] if settings.language else "English",
        "console": names[voice.understood(shown)] if shown else "the browser's language",
    }
    found.append(
        _check(
            "settings.language",
            INFO,
            "Language",
            "Reports in {{reports}}, sessions told to write in it; the console in {{console}}."
            if settings.language
            else "Reports in English, sessions answer in the ticket's language; the console in {{console}}.",
            params=params,
        )
    )
    return found


def _validation(settings: config_module.Runner) -> list[Check]:
    """How far work goes on its own once validated: conflicts resolved, review skipped."""
    found: list[Check] = []
    if settings.rebase and settings.resolve_conflicts:
        excepted = settings.resolve_conflicts_except.strip()
        found.append(
            _check(
                "settings.validation",
                OK,
                "Validation",
                "A validated merge that conflicts is resolved by {{model}}, except on {{excepted}}."
                if excepted
                else "A validated merge that conflicts is resolved by {{model}}.",
                params={
                    "model": settings.resolve_model or "the ticket’s own model",
                    "excepted": excepted,
                },
            )
        )
    else:
        found.append(
            _check(
                "settings.validation",
                WARN,
                "Validation",
                "{{setting}} is off: a validated merge that conflicts blocks its ticket.",
                params={
                    "setting": "runner.rebase"
                    if not settings.rebase
                    else "runner.resolve_conflicts"
                },
            )
        )
    # Not a problem, since it is a choice — but the one setting that lets work
    # leave the machine for good without anybody having read it, so it is said.
    forced = [kind for kind in kinds.KINDS if settings.forces_validation(kind)]
    if forced:
        found.append(
            _check(
                "settings.validation",
                WARN,
                "Validation",
                "Force validated: {{kinds}}. Merged or published as soon as the session succeeds, without waiting for review.",
                params={"kinds": ", ".join(forced)},
            )
        )
        if "code" in forced and not (settings.push and settings.open_pull_request):
            found.append(
                _check(
                    "settings.validation",
                    WARN,
                    "Validation",
                    "runner.force_validated_code is on, but no pull request is opened to merge.",
                )
            )
    # And the projects that decide for themselves, in either direction: the
    # lines above are not the whole story for them.
    owning = project_settings.owning_validation()
    if owning:
        found.append(
            _check(
                "settings.validation",
                OK,
                "Validation",
                "An automatic validation of their own, over the lines above: {{names}}.",
                params={"names": ", ".join(project["name"] or project["id"] for project in owning)},
            )
        )
    preparing = project_settings.owning_setup()
    if preparing:
        found.append(
            _check(
                "settings.setup",
                OK,
                "Worktree setup",
                "A setup command runs in each fresh worktree before the session ({{minutes}} minutes at most): {{names}}.",
                params={
                    "minutes": settings.setup_timeout_minutes,
                    "names": ", ".join(project["name"] or project["id"] for project in preparing),
                },
            )
        )
    return found


def _self_review(settings: config_module.Runner) -> list[Check]:
    """Whether a branch is read against its ticket before its push — see review.py."""
    if not settings.self_review:
        return [
            _check(
                "settings.self_review",
                INFO,
                "Self-review",
                "runner.self_review is off: branches are pushed without being read against their ticket.",
            )
        ]
    return [
        _check(
            "settings.self_review",
            OK,
            "Self-review",
            "Each branch is read against its ticket by {{model}} before the push, and its session picked up once on what is blocking.",
            params={"model": settings.review_model or "the ticket’s own model"},
        )
    ]


def _vault(config: config_module.Config) -> list[Check]:
    """The keys `[vault]` grants each project, and whether they can be read now.

    Each one is read, as a session would — and only said to be there or not:
    no value, and not even its length, is said. See vault.py.
    """
    settings = config.vault
    title = "Vault"
    found = [
        _check(
            "settings.vault",
            ERROR,
            title,
            "A line of [vault] cannot be used as written.",
            evidence=problem,
        )
        for problem in settings.problems
    ]
    if not settings.projects:
        if vault_store.exists() and vault_store.listing():
            # Ponos's own vault grants its keys itself: see `_vault_store`.
            return found
        found.append(
            _check(
                "settings.vault",
                INFO,
                title,
                "No [vault] secret: no project is given a key.",
            )
        )
        return found
    used = {settings.provider} | {
        vault.where(item, settings.provider)[0]
        for granted in settings.projects.values()
        for item in granted.values()
    }
    for name in sorted(used & set(vault.PROVIDERS)):
        missing = vault.provider(name).available() if name != "env" else ""
        if missing:
            found.append(
                _check(
                    "settings.vault",
                    ERROR,
                    title,
                    "The secret provider {{provider}} cannot be asked.",
                    params={"provider": name},
                    evidence=missing,
                )
            )
        else:
            found.append(
                _check(
                    "settings.vault",
                    OK,
                    title,
                    "The secret provider {{provider}} answers.",
                    params={"provider": name},
                )
            )
    stored = config_module.read_secrets(config_module.secrets_path(config.path))
    for project, granted in sorted(settings.projects.items()):
        read = vault.read(granted, settings.provider, stored)
        if read.values:
            found.append(
                _check(
                    "settings.vault",
                    OK,
                    title,
                    "{{project}} is given {{keys}}.",
                    params={"project": project, "keys": ", ".join(sorted(read.values))},
                )
            )
        for missing in read.missing:
            found.append(
                _check(
                    "settings.vault",
                    ERROR,
                    title,
                    "{{project}} is not given a key it was granted.",
                    params={"project": project},
                    evidence=missing,
                )
            )
    return found


def _vault_store() -> list[Check]:
    """Ponos's own vault: its file, where its key is kept, and what is in it — never a value.

    A key kept as a file is said every time: it is the one way in that a backup
    of the configuration and the state together takes with it. See vault_store.py.
    """
    title = "Vault"
    try:
        entries = vault_store.listing()
    except (vault.VaultError, sqlite3.Error, OSError) as error:
        return [
            _check(
                "settings.vault",
                ERROR,
                title,
                "The vault of Ponos cannot be opened.",
                evidence=str(error),
            )
        ]
    if not entries:
        return []
    found: list[Check] = []
    problem = vault_store.problem()
    if problem:
        found.append(
            _check(
                "settings.vault",
                ERROR,
                title,
                "The vault of Ponos cannot be opened.",
                evidence=problem,
            )
        )
    held = vault_store.path()
    for target in (held, vault_store.key_path()):
        mode = vault_store.mode_of(target)
        if mode is not None and mode & 0o077:
            found.append(
                _check(
                    "settings.vault",
                    ERROR,
                    title,
                    "{{path}} can be read by others.",
                    params={"path": str(target), "mode": f"{mode:o}"},
                    steps=["Make it yours alone: `chmod 600 {{path}}`."],
                )
            )
    where = vault_store.whereabouts()
    if where["source"] == "file":
        found.append(
            _check(
                "settings.vault",
                WARN,
                title,
                "The vault's key is a file, {{path}}: a backup that holds it and vault.db holds every key.",
                params={"path": where["where"]},
                cause="Neither secret-tool nor PONOS_VAULT_KEY was there when the vault was made.",
                steps=[
                    "Keep {{path}} out of the backups of the state directory, or give the key in PONOS_VAULT_KEY instead.",
                ],
            )
        )
    elif where["source"]:
        found.append(
            _check(
                "settings.vault",
                OK,
                title,
                "The vault's key is kept apart from it: {{where}}.",
                params={"where": where["where"]},
            )
        )
    past, soon = vault_store.expiring()
    if past:
        found.append(
            _check(
                "settings.vault",
                ERROR,
                title,
                "Past their expiry date in the vault: {{names}}.",
                params={"names": ", ".join(past)},
                steps=["Replace the value in Context → Vault, or revoke the entry."],
            )
        )
    if soon:
        found.append(
            _check(
                "settings.vault",
                WARN,
                title,
                "Expiring within {{days}} days in the vault: {{names}}.",
                params={"names": ", ".join(soon), "days": str(vault_store.EXPIRING_DAYS)},
            )
        )
    alone = [entry["name"] for entry in entries if not entry["projects"]]
    if alone:
        found.append(
            _check(
                "settings.vault",
                WARN,
                title,
                "Granted to no project, so given to no session: {{names}}.",
                params={"names": ", ".join(alone)},
                steps=["Choose its projects in Context → Vault."],
            )
        )
    if not found or all(check.state == OK for check in found):
        found.append(
            _check(
                "settings.vault",
                OK,
                title,
                "The vault of Ponos holds {{count}} entries.",
                params={"count": str(len(entries))},
            )
        )
    return found


def _console(config: config_module.Config) -> list[Check]:
    """How the console is opened, what reaches it, and what a message there can carry."""
    web = config.web
    found: list[Check] = []
    params = {"address": f"http://{web.host}:{web.port}"}
    # "We have a sign-in, and the page still asks me for a token" is the
    # ordinary shape of a console whose `web.email` and `web.password` were
    # never both set — the sign-in is dormant until they are, and the token
    # never goes away anyway. Said here rather than left to be guessed from a
    # login page that does not appear.
    if web.email and web.password:
        found.append(
            _check(
                "settings.console",
                OK,
                "Console",
                "{{address}} is opened by signing in as {{email}}; the token keeps working for a script.",
                params={**params, "email": web.email},
            )
        )
    else:
        found.append(
            _check(
                "settings.console",
                OK,
                "Console",
                "{{address}} is opened with its token (`ponos service run --print-token`).",
                params=params,
            )
        )
        if web.email or web.password:
            found.append(
                _check(
                    "settings.console",
                    WARN,
                    "Console",
                    "Half a sign-in: web.email without web.password, or the other way round, is not a way in.",
                    steps=["Set both web.email and web.password, or neither."],
                )
            )
        found.append(
            _check(
                "settings.console",
                INFO,
                "Console",
                "web.email and web.password, the two, to sign in instead.",
            )
        )
    # An entry that is neither an address nor a network is left out — which
    # counts whatever it meant to trust as one address, and says nothing.
    for entry in web.trusted_proxies:
        if attempts.network(entry) is None:
            found.append(
                _check(
                    "settings.console",
                    WARN,
                    "Console",
                    "web.trusted_proxies: {{entry}} is neither an address nor a network, and is left out.",
                    params={"entry": entry},
                    steps=["Write an address (10.0.1.5) or a network (10.0.1.0/24)."],
                )
            )
    # The MCP connector is pasted by its address: the one claude.ai reaches
    # has to be HTTPS, and Claude Code on this machine takes the loopback one.
    public = web.url
    if public.startswith("https://"):
        found.append(
            _check(
                "settings.mcp",
                OK,
                "MCP connector",
                "{{public}}/mcp for claude.ai; {{address}}/mcp for Claude Code here.",
                params={**params, "public": public},
            )
        )
    elif public:
        found.append(
            _check(
                "settings.mcp",
                WARN,
                "MCP connector",
                "web.url is {{public}}: claude.ai only adds a connector at an https:// address.",
                params={**params, "public": public},
            )
        )
    else:
        found.append(
            _check(
                "settings.mcp",
                INFO,
                "MCP connector",
                "{{address}}/mcp for Claude Code here; web.url for claude.ai.",
                params=params,
            )
        )
    # What a message typed there can carry, and the two things that need
    # something this machine may not have: a video needs ffmpeg to be looked at
    # (see `_tools`), and dictation needs somebody to transcribe it.
    found.append(
        _check(
            "settings.attachments",
            OK,
            "Attachments",
            "Up to {{size}} MB a file, kept {{days}} days.",
            params={"size": str(web.attachment_max_mb), "days": str(web.attachment_days)},
        )
    )
    openrouter = config.openrouter
    if openrouter.key:
        found.append(
            _check(
                "settings.dictation",
                OK,
                "Dictation",
                "Transcribed by {{model}}.",
                params={"model": openrouter.transcription_model},
            )
        )
    else:
        found.append(
            _check(
                "settings.dictation",
                INFO,
                "Dictation",
                "Off: it is transcribed by OpenRouter (openrouter.key).",
            )
        )
    found.extend(_voice(config.speech))
    chat_model = web.chat_model
    model = {"model": chat_model}
    if chat_model and "/" in chat_model and not openrouter.key:
        found.append(
            _check(
                "settings.chat",
                WARN,
                "Console sessions",
                "web.chat_model = {{model}} is an OpenRouter model, and openrouter.key is empty.",
                params=model,
            )
        )
    elif chat_model:
        found.append(
            _check(
                "settings.chat",
                OK,
                "Console sessions",
                "New console sessions start on {{model}}.",
                params=model,
            )
        )
    elif openrouter.key:
        found.append(
            _check(
                "settings.chat",
                OK,
                "Console sessions",
                "Claude models, and every OpenRouter model.",
            )
        )
    return found


def _ideas(settings: config_module.Runner) -> list[Check]:
    """Finding ideas on a schedule: that it can fire, and that it has projects to fire on."""
    wanted = idea_schedule.plan(settings)
    title = "Ideas schedule"
    if not wanted.on:
        return [
            _check(
                "settings.ideas",
                INFO,
                title,
                "runner.ideas_schedule = off: ideas are found when asked.",
            )
        ]
    params = {"schedule": wanted.schedule}
    if cause := idea_schedule.problem(wanted):
        return [
            _check(
                "settings.ideas",
                ERROR,
                title,
                "runner.ideas_schedule = {{schedule}} never fires.",
                params=params,
                evidence=cause,
            )
        ]
    following = idea_schedule.next_after(wanted, datetime.now().astimezone())
    found = [
        _check(
            "settings.ideas",
            OK,
            title,
            "Ideas are found on a schedule ({{schedule}}), next pass on {{when}}.",
            params={**params, "when": following.strftime("%Y-%m-%d %H:%M")},
        )
        if following
        else _check(
            "settings.ideas",
            OK,
            title,
            "Ideas are found on a schedule ({{schedule}}), with no pass to come.",
            params=params,
        )
    ]
    if wanted.scope == "selected" and not wanted.projects and not wanted.workspace:
        found.append(
            _check(
                "settings.ideas",
                WARN,
                title,
                "runner.ideas_scope = selected names no project: only a project's own switch counts.",
            )
        )
    if wanted.budget_usd:
        found.append(
            _check(
                "settings.ideas",
                INFO,
                title,
                "A pass spends ${{budget}} at the most.",
                params={"budget": f"{wanted.budget_usd:.2f}"},
            )
        )
    found.append(
        _check(
            "settings.ideas",
            INFO,
            title,
            "The passes run in the console (`ponos service run`), not in the daemon.",
        )
    )
    return found
