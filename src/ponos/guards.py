"""Garde-fous appliqués avant l'outil, plutôt que demandés dans un prompt.

« Ne touche pas à LICENSE », « pas de push sur main » : écrites dans un prompt,
ces règles se contournent, et on ne le voit qu'après coup. Claude Code appelle un
hook `PreToolUse` avant chaque outil ; s'il répond « deny », l'outil ne s'exécute
pas et la raison revient à l'agent, qui change de méthode. Le hook est ce module,
lancé par `python -m ponos.guards` (ou `ponos hook pre-tool-use`) : il lit le
JSON de Claude Code sur l'entrée standard et les règles du ticket dans un fichier.

**Un fichier de règles par session, écrit par le runner.** Les règles globales
(`[guards]` de `config.toml`) et celles du projet (`[guards]` du `.ponos.toml`,
lu sur la base et non sur la branche : la branche qui réécrit les règles n'est pas
celle qui les applique, comme pour `generated.py`) sont fusionnées une fois au
lancement. Le hook ne connaît donc que ce fichier, et un projet ne voit jamais les
règles d'un autre. Les listes s'ajoutent ; un booléen que le projet dit lui-même
l'emporte sur celui du fichier global.

**Ce module reste en bibliothèque standard** (et `generated.py`, pour ses globs) :
il démarre à chaque appel d'outil, la page de la console et pydantic n'ont rien à
y faire.

**Le hook ne bloque jamais par accident.** Une règle illisible, une entrée qui n'est
pas du JSON : la session continue, et l'erreur va sur la sortie d'erreur. Un
garde-fou qui plante ne doit pas arrêter un ticket. Chaque blocage est une ligne
JSON de plus dans `blocks`, que le runner recopie dans le journal du ticket.

**C'est un filet, pas une prison.** Un `Bash` peut écrire un fichier de cent façons ;
on repère les gestes courants (redirections, `sed -i`, `rm`, `mv`, `cp`, `tee`…),
pas ceux qu'on invente exprès pour contourner.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .generated import Rules as Globs

CONFIG = ".ponos.toml"
TABLE = "guards"

# The three git actions a rule may forbid, by the key that switches each.
GIT_KEYS = ("push_default", "force_push", "delete_branch")

# The tools that write, and those that only read.
WRITING = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
READING = frozenset({"Read", "Glob", "Grep"})

# What a shell command does to a path it names, for a path that is read-only.
_WRITERS = re.compile(
    r"(?:^|[\s;&|(])(?:rm|mv|cp|tee|touch|truncate|chmod|chown|ln|install|dd|rsync|patch|"
    r"sed\s+(?:-[a-zA-Z]*i|--in-place)|perl\s+-[a-zA-Z]*i|git\s+(?:checkout|restore|rm|mv|clean))\b"
)
_REDIRECT = re.compile(r">>?\s*\S")


@dataclass(frozen=True)
class Rules:
    """What a session may not do. Empty, nothing is checked."""

    read_only: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    push_default: bool = True
    force_push: bool = True
    delete_branch: bool = True
    # The branch a push may not reach, besides `main` and `master`.
    default_branch: str = ""

    @property
    def active(self) -> bool:
        return bool(
            self.read_only
            or self.forbidden
            or self.commands
            or self.push_default
            or self.force_push
            or self.delete_branch
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "read_only": list(self.read_only),
            "forbidden": list(self.forbidden),
            "commands": list(self.commands),
            "push_default": self.push_default,
            "force_push": self.force_push,
            "delete_branch": self.delete_branch,
            "default_branch": self.default_branch,
        }


@dataclass
class Table:
    """One `[guards]` table as it was written.

    `allow_git` names the git actions it lets through (`GIT_KEYS`); None is a
    table that does not say, which is not the same as one that allows nothing.
    """

    read_only: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    allow_git: tuple[str, ...] | None = None


def _list(value: object) -> tuple[str, ...]:
    """A list of non-blank strings; anything else is no rule at all."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := str(item).strip()))


def table(raw: object) -> Table:
    """A `[guards]` table, read leniently: a key of the wrong type is a key not said."""
    if not isinstance(raw, dict):
        return Table()
    return Table(
        read_only=_list(raw.get("read_only")),
        forbidden=_list(raw.get("forbidden")),
        commands=_list(raw.get("commands")),
        allow_git=tuple(one for one in _list(raw["allow_git"]) if one in GIT_KEYS)
        if isinstance(raw.get("allow_git"), (list, str))
        else None,
    )


def parse(text: str) -> Table:
    """The `[guards]` of a `.ponos.toml` — nothing when the file does not parse."""
    try:
        return table(tomllib.loads(text).get(TABLE))
    except tomllib.TOMLDecodeError:
        return Table()


def combine(globally: Table, own: Table, default_branch: str = "") -> Rules:
    """The rules of a project: both lists, and the project's word on which git actions pass."""
    allowed = own.allow_git if own.allow_git is not None else globally.allow_git or ()
    return Rules(
        read_only=tuple(dict.fromkeys((*globally.read_only, *own.read_only))),
        forbidden=tuple(dict.fromkeys((*globally.forbidden, *own.forbidden))),
        commands=tuple(dict.fromkeys((*globally.commands, *own.commands))),
        push_default="push_default" not in allowed,
        force_push="force_push" not in allowed,
        delete_branch="delete_branch" not in allowed,
        default_branch=default_branch,
    )


def rules_from(raw: dict[str, Any]) -> Rules:
    """The rules a rules file holds."""
    parsed = table(raw)
    return Rules(
        read_only=parsed.read_only,
        forbidden=parsed.forbidden,
        commands=parsed.commands,
        push_default=raw.get("push_default", True) is not False,
        force_push=raw.get("force_push", True) is not False,
        delete_branch=raw.get("delete_branch", True) is not False,
        default_branch=str(raw.get("default_branch") or "").strip(),
    )


def of_config(guards: Any) -> Table:
    """`config.Guards`, as the table it came from."""
    return Table(
        read_only=tuple(guards.read_only),
        forbidden=tuple(guards.forbidden),
        commands=tuple(guards.commands),
        allow_git=tuple(guards.allow_git),
    )


def project_table(worktree: Path | str, base: str) -> Table:
    """The `[guards]` the base of a project declares in its `.ponos.toml`."""
    from . import git

    shown = git.git(["show", f"{base}:{CONFIG}"], worktree)
    return parse(shown.out) if shown.ok else Table()


def for_job(guards: Any, worktree: Path | str, base: str) -> Rules:
    """The rules a ticket's session is held to: the file's and its project's."""
    default = base.removeprefix("origin/").removeprefix("refs/heads/")
    return combine(of_config(guards), project_table(worktree, base), default)


def write(target: Path, rules: Rules) -> Path:
    """The rules file the hook reads — written once, before the session starts."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rules.to_json(), indent=2), encoding="utf-8")
    blocks_path(target).unlink(missing_ok=True)
    return target


# -- paths -------------------------------------------------------------------------


def _relative(path: str, cwd: str) -> str:
    """A path as the rules write it: from the worktree's root, `..` settled."""
    if not path:
        return ""
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd, path))
    try:
        inside = os.path.relpath(full, cwd)
    except ValueError:
        return full
    return full if inside == ".." or inside.startswith("../") else inside


def _globs(patterns: tuple[str, ...]) -> Globs:
    """A folder written with its slash covers everything under it."""
    return Globs(paths=[f"{one}**" if one.endswith("/") else one for one in patterns])


def _covers(patterns: tuple[str, ...], name: str) -> bool:
    if not name:
        return False
    globs = _globs(patterns)
    # A folder named without a star covers what is under it as well.
    return globs.covers(name) or any(globs.covers(parent) for parent in _parents(name))


def _parents(name: str) -> list[str]:
    parts = name.split("/")
    return ["/".join(parts[:count]) for count in range(1, len(parts))]


def _paths(tool: str, arguments: dict[str, Any]) -> list[str]:
    keys = ("file_path", "notebook_path", "path")
    return [str(arguments[key]) for key in keys if isinstance(arguments.get(key), str)]


# -- shell commands ----------------------------------------------------------------


def _segments(command: str) -> list[list[str]]:
    """The simple commands of a line, each as its words."""
    out: list[list[str]] = []
    for part in re.split(r"&&|\|\||[;|\n]", command):
        try:
            words = shlex.split(part, comments=False)
        except ValueError:
            words = part.split()
        if words:
            out.append(words)
    return out


def _git_words(words: list[str]) -> tuple[str, list[str]] | None:
    """`(subcommand, its arguments)` of a `git` invocation, its own options skipped."""
    # Leading assignments (`GIT_SSH_COMMAND=… git push`) and `sudo`, `env`.
    index = 0
    while index < len(words) and (
        "=" in words[index].split("/")[-1][:40] or words[index] in ("env", "sudo", "command")
    ):
        index += 1
    if index >= len(words) or os.path.basename(words[index]) != "git":
        return None
    index += 1
    while index < len(words) and words[index].startswith("-"):
        # `-C dir` and `-c k=v` take an argument.
        index += 2 if words[index] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if index >= len(words):
        return None
    return words[index], words[index + 1 :]


def _branch_of(cwd: str) -> str:
    """The branch checked out in `cwd`, read from HEAD without running git."""
    folder = Path(cwd)
    for _ in range(40):
        head = folder / ".git"
        if head.is_file():
            try:
                pointed = head.read_text(encoding="utf-8").strip().removeprefix("gitdir:").strip()
                head = Path(pointed if os.path.isabs(pointed) else folder / pointed)
            except OSError:
                return ""
        if head.is_dir():
            try:
                text = (head / "HEAD").read_text(encoding="utf-8").strip()
            except OSError:
                return ""
            return text.removeprefix("ref: refs/heads/") if text.startswith("ref:") else ""
        if folder.parent == folder:
            return ""
        folder = folder.parent
    return ""


def _is_default(name: str, rules: Rules) -> bool:
    name = name.removeprefix("refs/heads/").removeprefix("origin/")
    return name in {"main", "master", rules.default_branch} - {""}


def _push(arguments: list[str], rules: Rules, cwd: str) -> str:
    options = [one for one in arguments if one.startswith("-")]
    refs = [one for one in arguments if not one.startswith("-")]
    forced = any(
        one in ("-f", "--force", "--force-if-includes")
        or one.startswith("--force-with-lease")
        or (not one.startswith("--") and "f" in one[1:] and one[1:].isalpha())
        for one in options
    ) or any(one.startswith("+") for one in refs[1:])
    deleting = any(one in ("-d", "--delete") for one in options) or any(
        one.startswith(":") for one in refs[1:]
    )
    if forced and rules.force_push:
        return "un push forcé est interdit (garde-fou `force_push`)"
    if deleting and rules.delete_branch:
        return "supprimer une branche distante est interdit (garde-fou `delete_branch`)"
    if not rules.push_default:
        return ""
    if "--all" in options or "--mirror" in options:
        return "un push de toutes les branches atteindrait la branche par défaut"
    targets = []
    for one in refs[1:]:
        targets.append(one.lstrip("+").split(":")[-1])
    # `git push` or `git push origin` pushes the checked-out branch.
    if not targets and _is_default(_branch_of(cwd), rules):
        return "la branche par défaut est celle de la session"
    if any(_is_default(one, rules) for one in targets):
        return "un push sur la branche par défaut est interdit (garde-fou `push_default`)"
    return ""


def _git(words: list[str], rules: Rules, cwd: str) -> str:
    found = _git_words(words)
    if not found:
        return ""
    sub, arguments = found
    if sub == "push":
        return _push(arguments, rules, cwd)
    if sub == "branch" and rules.delete_branch:
        if any(
            one in ("-d", "-D", "--delete") or re.fullmatch(r"-[a-zA-Z]*[dD]", one)
            for one in arguments
        ):
            return "supprimer une branche est interdit (garde-fou `delete_branch`)"
    return ""


def _shell(command: str, rules: Rules, cwd: str) -> str:
    for pattern in rules.commands:
        try:
            hit = re.search(pattern, command) is not None
        except re.error:  # not a pattern: the words themselves
            hit = pattern in command
        if hit:
            return f"la commande correspond au motif interdit `{pattern}`"
    for words in _segments(command):
        if reason := _git(words, rules, cwd):
            return reason
    named = _named(command, cwd)
    for name in named:
        if _covers(rules.forbidden, name):
            return f"`{name}` est un chemin interdit (garde-fou `forbidden`)"
    writes = bool(_WRITERS.search(command) or _REDIRECT.search(command))
    for name in named:
        if writes and _covers(rules.read_only, name):
            return f"`{name}` est en lecture seule (garde-fou `read_only`)"
    return ""


def _named(command: str, cwd: str) -> list[str]:
    """The paths a command line names, as rules write them: every word that is not an option."""
    return [
        _relative(word, cwd)
        for words in _segments(command)
        for word in (one.lstrip(">") for one in words)
        if word and not word.startswith("-")
    ]


# -- the decision ------------------------------------------------------------------


def decide(event: dict[str, Any], rules: Rules) -> str:
    """Why this tool call must not run — or '' when it may.

    `event` is what Claude Code gives a `PreToolUse` hook: `tool_name`,
    `tool_input` and `cwd`.
    """
    if not rules.active:
        return ""
    tool = str(event.get("tool_name") or "")
    arguments = event.get("tool_input")
    arguments = arguments if isinstance(arguments, dict) else {}
    cwd = str(event.get("cwd") or os.getcwd())
    if tool == "Bash":
        command = arguments.get("command")
        return _shell(command, rules, cwd) if isinstance(command, str) else ""
    for path in _paths(tool, arguments):
        name = _relative(path, cwd)
        if _covers(rules.forbidden, name):
            return f"`{name}` est un chemin interdit (garde-fou `forbidden`)"
        if tool in WRITING and _covers(rules.read_only, name):
            return f"`{name}` est en lecture seule (garde-fou `read_only`)"
    return ""


def message(reason: str) -> str:
    """What the agent is told: the reason, and that another way is wanted."""
    return (
        f"Garde-fou Ponos : {reason}. Cette règle est appliquée par Ponos, pas par le prompt : "
        "ne cherche pas à la contourner. Change de méthode, ou, si le ticket l'exige "
        "vraiment, termine bloqué en expliquant ce qu'il faudrait autoriser."
    )


def run(stdin: str, rules_path: Path) -> tuple[str, str]:
    """`(answer for Claude Code, reason)` — both empty when the call may go on."""
    try:
        event = json.loads(stdin)
        rules = rules_from(json.loads(rules_path.read_text(encoding="utf-8")))
    except (ValueError, OSError) as error:
        print(f"ponos guards: {error}", file=sys.stderr)
        return "", ""
    if not isinstance(event, dict):
        return "", ""
    reason = decide(event, rules)
    if not reason:
        return "", ""
    answer = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message(reason),
        }
    }
    try:
        blocked = event.get("tool_input") or {}
        detail = str(
            blocked.get("command") or blocked.get("file_path") or blocked.get("path") or ""
        )
        line = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool": str(event.get("tool_name") or ""),
            "detail": detail[:300],
            "reason": reason,
        }
        with blocks_path(rules_path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    except (OSError, AttributeError) as error:
        print(f"ponos guards: block not written: {error}", file=sys.stderr)
    return json.dumps(answer, ensure_ascii=False), reason


def blocks_path(rules_path: Path) -> Path:
    """Where the blocks of a session are written, beside its rules."""
    return rules_path.with_suffix(".blocks.jsonl")


def blocks(rules_path: Path) -> list[dict[str, str]]:
    """What the hook blocked in a session, in order."""
    try:
        lines = blocks_path(rules_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            one = json.loads(line)
        except ValueError:
            continue
        if isinstance(one, dict):
            out.append({key: str(one.get(key) or "") for key in ("at", "tool", "detail", "reason")})
    return out


def command(rules_path: Path) -> str:
    """The shell command Claude Code runs as its hook."""
    source = str(Path(__file__).resolve().parent.parent)
    return (
        f"PYTHONPATH={shlex.quote(source)} {shlex.quote(sys.executable or 'python3')} "
        f"-m ponos.guards --rules {shlex.quote(str(rules_path))}"
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["pre-tool-use"]:
        arguments = arguments[1:]
    if len(arguments) != 2 or arguments[0] != "--rules":
        print("usage: ponos hook pre-tool-use --rules FILE", file=sys.stderr)
        return 2
    answer, _ = run(sys.stdin.read(), Path(arguments[1]))
    if answer:
        print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
