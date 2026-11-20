"""`guards.py`: ce que le hook `PreToolUse` décide, d'après le JSON que Claude Code lui donne."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from support import _config, case

from ponos import config as config_module
from ponos import guards, session

SOURCE = str(Path(guards.__file__).resolve().parent.parent)
CWD = "/work/tree"
RULES = guards.Rules(
    read_only=("LICENSE", "**/package.json", "docs/"),
    forbidden=(".env", "secrets/**"),
    commands=(r"terraform\s+destroy",),
    default_branch="develop",
)


def _call(tool: str, **arguments: Any) -> dict[str, Any]:
    return {"tool_name": tool, "tool_input": arguments, "cwd": CWD}


def _bash(command: str, rules: guards.Rules = RULES) -> str:
    return guards.decide(_call("Bash", command=command), rules)


@case
def a_write_to_a_read_only_path_is_refused_and_a_read_is_not() -> None:
    assert "lecture seule" in guards.decide(_call("Write", file_path=f"{CWD}/LICENSE"), RULES)
    assert "lecture seule" in guards.decide(_call("Edit", file_path="LICENSE"), RULES)
    assert guards.decide(_call("Read", file_path=f"{CWD}/LICENSE"), RULES) == ""
    assert guards.decide(_call("Edit", file_path=f"{CWD}/packages/a/package.json"), RULES)
    assert guards.decide(_call("Write", file_path=f"{CWD}/docs/deep/page.md"), RULES), "a folder"
    assert guards.decide(_call("Write", file_path=f"{CWD}/src/LICENSE.py"), RULES) == ""
    assert guards.decide(_call("Write", file_path=f"{CWD}/src/../LICENSE"), RULES), "`..` settled"


@case
def a_forbidden_path_is_neither_read_nor_written() -> None:
    assert "interdit" in guards.decide(_call("Read", file_path=f"{CWD}/.env"), RULES)
    assert guards.decide(_call("Write", file_path=f"{CWD}/secrets/key.pem"), RULES)
    assert guards.decide(_call("Grep", pattern="x", path="secrets/sub"), RULES)
    assert guards.decide(_call("Read", file_path=f"{CWD}/src/main.py"), RULES) == ""
    assert guards.decide(_call("Read", file_path="/etc/hosts"), RULES) == "", "outside the tree"


@case
def a_shell_command_is_checked_for_what_it_writes_and_what_it_matches() -> None:
    assert "lecture seule" in _bash("echo x > LICENSE")
    assert _bash("sed -i s/a/b/ packages/a/package.json")
    assert _bash("rm docs/page.md")
    assert _bash("cat LICENSE") == "", "reading a read-only file is fine"
    assert "interdit" in _bash("cat .env")
    assert "motif" in _bash("cd infra && terraform   destroy -auto-approve")
    assert _bash("ls -la && git status") == ""


@case
def pushing_to_the_default_branch_is_refused_whichever_way_it_is_written() -> None:
    for command in (
        "git push origin main",
        "git push origin HEAD:main",
        "git push -u origin master",
        "git push origin develop",
        "git -C sub push origin main",
        "GIT_SSH_COMMAND=ssh git push origin refs/heads/main",
        "ls && git push origin main",
        "git push --all",
    ):
        assert "branche par défaut" in _bash(command) or "toutes" in _bash(command), command
    assert _bash("git push -u origin ticket/ma-branche") == ""
    assert _bash("git push origin HEAD") == ""


@case
def force_pushes_and_branch_deletions_are_refused() -> None:
    for command in (
        "git push --force origin ticket/a",
        "git push -f origin ticket/a",
        "git push --force-with-lease origin ticket/a",
        "git push origin +ticket/a",
    ):
        assert "forcé" in _bash(command), command
    for command in (
        "git push origin --delete ticket/a",
        "git push origin :ticket/a",
        "git branch -D old",
        "git branch -d old",
    ):
        assert "supprimer" in _bash(command), command
    assert _bash("git branch --list") == ""
    assert _bash("git branch new-one") == ""


@case
def a_rule_switched_off_lets_its_action_through() -> None:
    free = guards.Rules(push_default=False, force_push=False, delete_branch=False)
    assert not free.active
    assert _bash("git push --force origin main", free) == ""
    only_force = guards.Rules(push_default=False, delete_branch=False)
    assert _bash("git push origin main", only_force) == ""
    assert _bash("git push -f origin x", only_force)


@case
def a_push_without_a_target_follows_the_branch_checked_out(state_home: Path) -> None:
    tree = state_home / "tree"
    (tree / ".git").mkdir(parents=True)
    (tree / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    event = {"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": str(tree)}
    assert guards.decide(event, RULES)
    (tree / ".git" / "HEAD").write_text("ref: refs/heads/ticket/x\n")
    assert guards.decide(event, RULES) == ""


@case
def rules_are_the_files_and_the_projects_and_a_project_never_sees_another(
    state_home: Path,
) -> None:
    config = _config("[guards]\nread_only = ['LICENSE']\nallow_git = ['force_push']\n").guards
    assert config.read_only == ("LICENSE",) and config.allow_git == ("force_push",)
    mine = guards.parse(
        '[guards]\nread_only = ["a.txt"]\nforbidden = [".env"]\nallow_git = ["push_default"]'
    )
    other = guards.parse("# nothing here\n")
    one = guards.combine(guards.of_config(config), mine, "main")
    two = guards.combine(guards.of_config(config), other, "main")
    assert one.read_only == ("LICENSE", "a.txt") and one.forbidden == (".env",)
    assert not one.push_default and one.force_push and one.delete_branch, "the project's word"
    assert two.read_only == ("LICENSE",) and two.forbidden == () and two.push_default
    assert not two.force_push and two.delete_branch, "the file's word when the project is silent"
    assert guards.parse("not = [valid").read_only == (), "a file that does not parse says nothing"
    assert guards.parse("[guards]\nread_only = 3\nallow_git = 3").allow_git is None
    assert guards.parse('[guards]\nallow_git = ["push", "force_push"]').allow_git == ("force_push",)


@case
def the_rules_of_a_project_are_read_from_its_base_not_its_branch(state_home: Path) -> None:
    repo = state_home / "repo"
    repo.mkdir(parents=True)

    def git(*arguments: str) -> None:
        subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "a@b.c")
    git("config", "user.name", "a")
    (repo / ".ponos.toml").write_text('[guards]\nforbidden = ["base.txt"]\n')
    git("add", ".")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "ticket/x")
    (repo / ".ponos.toml").write_text('[guards]\nforbidden = ["branch.txt"]\n')
    rules = guards.for_job(config_module.Guards(), repo, "main")
    assert rules.forbidden == ("base.txt",) and rules.default_branch == "main"
    assert guards.for_job(config_module.Guards(), repo, "origin/nothing").forbidden == ()


@case
def the_hook_answers_deny_with_the_reason_and_writes_the_block(state_home: Path) -> None:
    path = guards.write(state_home / "s.guards.json", RULES)
    event = json.dumps(_call("Write", file_path=f"{CWD}/LICENSE"))
    done = subprocess.run(
        [sys.executable, "-m", "ponos.guards", "--rules", str(path)],
        input=event,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": SOURCE, "PATH": "/usr/bin:/bin"},
        check=True,
    )
    answer = json.loads(done.stdout)["hookSpecificOutput"]
    assert answer["hookEventName"] == "PreToolUse" and answer["permissionDecision"] == "deny"
    assert (
        "LICENSE" in answer["permissionDecisionReason"]
        and "Change de méthode" in (answer["permissionDecisionReason"])
    )
    blocked = guards.blocks(path)
    assert len(blocked) == 1 and blocked[0]["tool"] == "Write" and "LICENSE" in blocked[0]["detail"]
    allowed = subprocess.run(
        [sys.executable, "-m", "ponos.guards", "--rules", str(path)],
        input=json.dumps(_call("Read", file_path="LICENSE")),
        capture_output=True,
        text=True,
        env={"PYTHONPATH": SOURCE, "PATH": "/usr/bin:/bin"},
        check=True,
    )
    assert allowed.stdout == "" and len(guards.blocks(path)) == 1
    guards.write(path, RULES)
    assert guards.blocks(path) == [], "a new session starts with no block"


@case
def a_hook_that_cannot_read_its_rules_lets_the_session_go_on(state_home: Path) -> None:
    missing = state_home / "gone.json"
    assert guards.run(json.dumps(_call("Bash", command="git push origin main")), missing) == (
        "",
        "",
    )
    state_home.mkdir(parents=True, exist_ok=True)
    broken = state_home / "broken.json"
    broken.write_text("{")
    assert guards.run("{}", broken) == ("", "")
    path = guards.write(state_home / "ok.json", RULES)
    assert guards.run("not json", path) == ("", "")
    assert guards.run("[1]", path) == ("", "")


@case
def a_session_is_given_its_hook_beside_its_unsigned_settings(state_home: Path) -> None:
    rules = guards.write(state_home / "s.guards.json", RULES)

    def settings(**options: Any) -> dict[str, Any]:
        command = session._command(
            "claude",
            "s1",
            resume=False,
            permission_mode="bypassPermissions",
            model="",
            max_budget_usd=0,
            **options,
        )
        return (
            json.loads(command[command.index("--settings") + 1]) if "--settings" in command else {}
        )

    guarded = settings(guard=rules)
    hook = guarded["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "*" and str(rules) in hook["hooks"][0]["command"]
    assert "ponos.guards" in hook["hooks"][0]["command"]
    assert guarded["attribution"] == {"commit": "", "pr": ""}, "still unsigned"
    assert "hooks" not in settings(), "no rules, no hook"
    assert settings(attribution=True) == {} and "hooks" in settings(attribution=True, guard=rules)
    steered = settings(guard=rules, steered=state_home / "s.steering.json")
    assert set(steered["hooks"]) == {"PreToolUse", "PostToolUse", "Stop"}, (
        "the queue's and the guards'"
    )
