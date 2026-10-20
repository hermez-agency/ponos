"""`github_token.py`: the GitHub token."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from support import _config, _github_answering, _test_app, _tools, case

from ponos import config as C
from ponos import git as git_module
from ponos import github_app, github_token, vault
from ponos.web import github as web_github

# -- the GitHub token ----------------------------------------------------------


@contextmanager
def _token_answering(answer, configuration: str = ""):
    """GitHub replaced by `answer(path, token) -> (status, headers, payload)`, with a config of its own.

    Yields the paths asked. Nothing here reads the machine's own configuration,
    secrets or environment: `PONOS_GITHUB_TOKEN` is cleared for the length of it.
    """
    asked: list[str] = []

    def send(url, bearer):
        path = url[len(github_app.api()) :]
        asked.append(path)
        status, headers, payload = answer(path, bearer)
        return status, headers, json.dumps(payload).encode()

    folder = Path(tempfile.mkdtemp())
    (folder / "config.toml").write_text(configuration)
    names = ("PONOS_CONFIG", C.SECRETS_PATH_ENV, C.GITHUB_TOKEN_ENV)
    before = {name: os.environ.get(name) for name in names}
    original = github_token._send
    github_token._send = send
    os.environ["PONOS_CONFIG"] = str(folder / "config.toml")
    os.environ[C.SECRETS_PATH_ENV] = str(folder / "secrets.env")
    os.environ.pop(C.GITHUB_TOKEN_ENV, None)
    github_token._kept = None
    github_app._installations.clear()
    github_app._tokens.clear()
    try:
        yield asked
    finally:
        github_token._send = original
        github_token._kept = None
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(folder, ignore_errors=True)
        vault.forget()


def _fine_grained(repositories, pulls=200):
    """A fine-grained token as GitHub answers for it: no scopes header, `pulls` for the pull requests."""

    def answer(path, bearer):
        if path == "/user":
            return 200, {}, {"login": "salva"}
        if path.startswith("/user/repos"):
            return 200, {}, repositories
        if "/pulls" in path:
            return pulls, {}, []
        raise AssertionError(path)

    return answer


_WRITABLE = [{"full_name": "salva/site", "permissions": {"push": True, "pull": True}}]


@case
def a_token_with_what_a_code_ticket_needs_is_kept_and_never_shown():
    with _token_answering(_fine_grained(_WRITABLE)):
        checked = github_token.check("github_pat_abcdef123456")
        assert checked["ok"] and checked["login"] == "salva" and checked["kind"] == "fine-grained"
        assert checked["repositories"] == ["salva/site"] and checked["missing"] == []
        assert "github_pat_abcdef123456" not in json.dumps(checked)
        assert github_token.token() == ""
        github_token.save("github_pat_abcdef123456")
        assert github_token.token() == "github_pat_abcdef123456"
        assert github_token.source() == "secrets.env"
        assert "github_pat_abcdef123456" not in C.config_path().read_text()
        assert oct((Path(os.environ[C.SECRETS_PATH_ENV])).stat().st_mode & 0o777) == "0o600"
        assert vault.mask("pushed with github_pat_abcdef123456") == "pushed with ***"
        assert "github_pat_abcdef123456" not in json.dumps(github_token.describe())
        assert github_token.forget() is True and github_token.token() == ""


@case
def a_token_that_is_refused_or_too_narrow_says_what_it_lacks():
    with _token_answering(lambda path, bearer: (401, {}, {"message": "Bad credentials"})):
        try:
            github_token.check("github_pat_wrong")
        except github_token.GithubTokenError as error:
            assert "mistyped, expired or revoked" in str(error) and "github_pat_wrong" not in str(
                error
            )
        else:
            raise AssertionError("a refused token is no token")
    read_only = [{"full_name": "salva/site", "permissions": {"push": False, "pull": True}}]
    with _token_answering(_fine_grained(read_only)):
        assert github_token.check("github_pat_x")["missing"] == [
            {"permission": "Contents", "level": "Read and write"}
        ]
    with _token_answering(_fine_grained(_WRITABLE, pulls=403)):
        assert github_token.check("github_pat_x")["missing"] == [
            {"permission": "Pull requests", "level": "Read and write"}
        ]
    with _token_answering(_fine_grained([])):
        assert github_token.check("github_pat_x")["missing"][0]["permission"] == "Repository access"

    # A classic token says its scopes in a header; `repo` is the one it cannot do without.
    def classic(path, bearer):
        headers = {"x-oauth-scopes": "read:user"}
        if path == "/user":
            return 200, headers, {"login": "salva"}
        return 200, headers, _WRITABLE

    with _token_answering(classic):
        checked = github_token.check("ghp_" + "a" * 36)
        assert checked["kind"] == "classic" and checked["ok"] is False
        assert checked["missing"] == [{"permission": "repo", "level": "scope"}]
        assert any("workflow" in warning for warning in checked["warnings"])


@case
def the_console_keeps_only_a_token_that_can_work_and_selects_it():
    saved: list[dict] = []

    class Api:
        def save_settings(self, payload):
            saved.append(payload)
            return {"saved": []}

    with _token_answering(_fine_grained(_WRITABLE, pulls=403)):
        answer = web_github.save_token(Api(), {"token": "github_pat_narrow"})
        assert answer["saved"] is False and answer["missing"][0]["permission"] == "Pull requests"
        assert github_token.token() == "" and saved == [], (
            "a token that lacks a permission is not kept"
        )
        try:
            web_github.save_token(Api(), {"token": "has a space"})
        except ValueError as error:
            assert "one line" in str(error)
        else:
            raise AssertionError("a pasted sentence is no token")
    with _token_answering(_fine_grained(_WRITABLE)):
        answer = web_github.save_token(Api(), {"token": "github_pat_good"})
        assert answer["saved"] is True and "github_pat_good" not in json.dumps(answer)
        assert saved == [{"settings": {"github_access.mode": "token"}}]
        assert github_token.token() == "github_pat_good"


@case
def a_token_comes_before_gh_and_after_or_before_the_app_as_the_mode_says():
    def answer(path, bearer):
        if path.startswith("/app/installations?"):
            return (
                200,
                {},
                [{"id": 7, "account": {"login": "hermez"}, "repository_selection": "all"}],
            )
        raise AssertionError(path)

    def app_token(method, path, headers, body):
        if path.startswith("/app/installations?"):
            return 200, [{"id": 7, "account": {"login": "hermez"}, "repository_selection": "all"}]
        return 201, {"token": "ghs_app", "expires_at": "2099-01-01T00:00:00Z"}

    sessions = {}
    for mode, expected in (("", "ghs_app"), ("app", "ghs_app"), ("token", "github_pat_mine")):
        with _github_answering(app_token):
            config = Path(os.environ["PONOS_CONFIG"])
            config.write_text(f'[github_access]\nmode = "{mode}"\n' if mode else "")
            github_app.save(_test_app())
            github_token.save("github_pat_mine")
            assert git_module.token_for("hermez/site", {"hermez": "salva"}) == expected, mode
            sessions[mode] = github_token.session_environment("hermez")
    assert sessions["token"]["GH_TOKEN"] == sessions["token"]["GITHUB_TOKEN"] == "github_pat_mine"
    assert "github_pat_mine" not in "".join(
        value for name, value in sessions["token"].items() if name.startswith("GIT_CONFIG")
    ), "git reads the token from the environment, it is written into no setting"
    assert sessions["app"]["GH_TOKEN"] == "ghs_app"
    # Without the app, the token answers for every owner — in `auto` and in `token` alike.
    with _token_answering(answer):
        assert git_module.token_for("someone/else", None) == ""
        github_token.save("github_pat_mine")
        assert git_module.token_for("someone/else", {"someone": "gh-account"}) == "github_pat_mine"
        assert github_token.session_environment("someone")["GH_TOKEN"] == "github_pat_mine"
        seen = git_module.run(
            ["sh", "-c", 'echo "$GH_TOKEN $GIT_CONFIG_COUNT"'],
            token=git_module.token_for("someone/else", None),
        )
        assert seen.out.split()[0] == "github_pat_mine" and int(seen.out.split()[1]) >= 5, seen.out
        # `gh`'s own token is passed on as it always was.
        assert (
            git_module.run(["sh", "-c", 'echo "${GIT_CONFIG_COUNT:-none}"'], token="gho_mine").out
            == "none"
        )


@case
def a_token_is_read_from_the_environment_or_a_vault_and_masked():
    with _token_answering(lambda *_: (200, {}, {})):
        os.environ[C.GITHUB_TOKEN_ENV] = "github_pat_from_the_container"
        github_token._kept = None
        assert github_token.token() == "github_pat_from_the_container"
        assert github_token.source() == C.GITHUB_TOKEN_ENV
        assert vault.mask("echo github_pat_from_the_container") == "echo ***"
        assert github_token.forget() is False, "a token the environment gives is not ours to drop"
    with (
        _token_answering(
            lambda *_: (200, {}, {}), '[github_access]\ntoken_item = "pass:ponos/github"\n'
        ),
        _tools({"pass": "print('github_pat_from_pass\\nnote')"}),
    ):
        assert github_token.token() == "github_pat_from_pass"
        assert github_token.source() == "pass:ponos/github"
        assert github_token.unavailable() == ""
        assert vault.mask("github_pat_from_pass") == "***"
    with (
        _token_answering(lambda *_: (200, {}, {}), '[github_access]\ntoken_item = "pass:absent"\n'),
        _tools(
            {"pass": "sys.stderr.write('Error: absent is not in the password store.'); sys.exit(1)"}
        ),
    ):
        assert github_token.token() == "" and "holds no item" in github_token.unavailable()


@case
def the_github_access_keys_are_documented_and_the_token_is_a_secret():
    assert C.SECRETS[("github_access", "token")] == "PONOS_GITHUB_TOKEN"
    example = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text()
    assert "[github_access]" in example and "PONOS_GITHUB_TOKEN" in example
    assert "token_item" in example
    assert _config('[github_access]\nmode = "token"\n').github_access.mode == "token"
    assert _config('[github_access]\nmode = "nonsense"\n').github_access.mode == ""
    assert (
        "contents=write" in github_token.CREATE_URL
        and "pull_requests=write" in github_token.CREATE_URL
    )
