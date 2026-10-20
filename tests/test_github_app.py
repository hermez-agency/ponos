"""`github_app.py`: the GitHub App."""

from __future__ import annotations

import io
import json
import os
import time
from datetime import UTC, datetime

from support import _TEST_PEM, _github_answering, _test_app, case

from ponos import config as C
from ponos import git as git_module
from ponos import github_app
from ponos.web import github as web_github

# -- the GitHub App ----------------------------------------------------------


@case
def a_github_app_jwt_is_rs256_signed_by_its_key_and_lasts_under_ten_minutes():
    import base64

    def part(text: str) -> bytes:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    token = github_app.jwt(_test_app(), now=1_000_000)
    header, claims, signature = token.split(".")
    assert json.loads(part(header)) == {"alg": "RS256", "typ": "JWT"}
    said = json.loads(part(claims))
    assert said == {"iat": 1_000_000 - 60, "exp": 1_000_000 + 540, "iss": "Iv1.abc"}, said
    assert said["exp"] - said["iat"] <= 600
    # Checked with the public half: the signature, raised to `e`, is the padded digest.
    modulus, _ = github_app.private_key(_TEST_PEM)
    data = base64.b64decode("".join(_TEST_PEM.splitlines()[1:-1]))
    _, outer, _ = github_app._der(data, 0)
    exponent = int.from_bytes(github_app._children(outer)[2][1], "big")
    size = (modulus.bit_length() + 7) // 8
    opened = pow(int.from_bytes(part(signature), "big"), exponent, modulus).to_bytes(size, "big")
    import hashlib

    digest = hashlib.sha256(f"{header}.{claims}".encode()).digest()
    assert opened.startswith(b"\x00\x01\xff") and opened.endswith(github_app.SHA256_PREFIX + digest)
    # Without a client id, the app's id is who signs.
    assert (
        json.loads(part(github_app.jwt(_test_app(client_id=""), now=5).split(".")[1]))["iss"]
        == "42"
    )


@case
def the_manifest_code_is_exchanged_once_and_the_app_kept_with_the_secrets():
    def answer(method, path, headers, body):
        if path.startswith("/app/installations?"):
            return 200, []
        assert (method, path) == ("POST", "/app-manifests/abc123/conversions"), (method, path)
        assert "Authorization" not in headers
        return 201, {
            "id": 42,
            "slug": "ponos-laptop",
            "name": "Ponos — laptop",
            "owner": {"login": "Hermez"},
            "pem": _TEST_PEM,
            "client_id": "Iv1.abc",
            "client_secret": "shh",
            "webhook_secret": "hook",
            "html_url": "https://github.com/apps/ponos-laptop",
        }

    with _github_answering(answer) as calls:
        state = github_app.draw_state(organisation="hermez")
        code, where = web_github.callback("abc123", state)
        assert code == 303 and where.endswith("/apps/ponos-laptop/installations/new"), where
        assert [call[1] for call in calls] == ["/app-manifests/abc123/conversions"]
        kept = github_app.apps()
        assert [(app.id, app.slug, app.owner, app.client_secret) for app in kept] == [
            (42, "ponos-laptop", "Hermez", "shh")
        ]
        assert kept[0].pem == _TEST_PEM, "the key comes back whole, line breaks and all"
        file = C.secrets_path()
        assert file.stat().st_mode & 0o777 == 0o600
        # The console is shown names and places, never what signs or opens.
        shown = json.dumps(web_github.status())
        assert "PRIVATE KEY" not in shown and "shh" not in shown and "hook" not in shown
        # The same state a second time is a link already used.
        code, _ = web_github.callback("abc123", state)
        assert code == 400
        assert sum(call[1].startswith("/app-manifests/") for call in calls) == 1
        assert web_github.disconnect("ponos-laptop")["forgotten"] == "ponos-laptop"
        assert github_app.apps() == []


@case
def a_github_state_that_is_unknown_used_or_expired_is_refused_before_github_is_asked():
    with _github_answering(lambda *_: (500, {})) as calls:
        assert github_app.take_state("") is None
        assert github_app.take_state("made-up") is None
        code, page = web_github.callback("abc123", "made-up")
        assert code == 400 and "expired" in page
        late = github_app.draw_state()
        until, data = github_app._states[late]
        github_app._states[late] = (time.monotonic() - 1, data)
        assert github_app.take_state(late) is None
        good = github_app.draw_state(organisation="hermez")
        assert github_app.take_state(good) == {"organisation": "hermez"}
        assert github_app.take_state(good) is None
        assert calls == []


@case
def connecting_github_posts_a_manifest_for_an_account_or_an_organisation():
    mine = github_app.begin("http://127.0.0.1:8787/", "", "laptop")
    assert mine["action"].startswith("https://github.com/settings/apps/new?state=")
    theirs = github_app.begin("https://ponos.example", "@Hermez", "laptop")
    assert theirs["action"].startswith(
        "https://github.com/organizations/Hermez/settings/apps/new?state="
    )
    said = json.loads(theirs["manifest"])
    assert said["name"] == "Ponos — laptop" and said["public"] is False
    assert said["redirect_url"] == "https://ponos.example/api/github/manifest/callback"
    assert said["setup_url"] == "https://ponos.example/api/github/installed"
    assert said["hook_attributes"]["active"] is False
    assert said["default_permissions"]["contents"] == "write"
    assert said["default_permissions"]["metadata"] == "read"
    assert not any(key.startswith("organization_") for key in said["default_permissions"])
    assert (
        len(github_app.app_name("a-very-long-machine-name-indeed-yes")) <= github_app.LONGEST_NAME
    )
    assert github_app.take_state(theirs["state"]) == {"organisation": "Hermez"}


@case
def an_installation_token_is_kept_and_renewed_before_it_lapses():
    minted: list[str] = []

    def answer(method, path, headers, body):
        if path.startswith("/app/installations?"):
            return 200, [{"id": 7, "account": {"login": "Hermez"}, "repository_selection": "all"}]
        assert (method, path) == ("POST", "/app/installations/7/access_tokens"), path
        assert headers["Authorization"].startswith("Bearer ey")
        minted.append(f"ghs_{len(minted)}")
        return 201, {"token": minted[-1], "expires_at": "2030-01-01T12:00:00Z"}

    with _github_answering(answer):
        github_app.save(_test_app())
        lapse = datetime(2030, 1, 1, 12, tzinfo=UTC).timestamp()
        app = github_app.apps()[0]
        assert github_app.installation_token(app, 7, now=lapse - 3000) == "ghs_0"
        assert github_app.installation_token(app, 7, now=lapse - 700) == "ghs_0", "still fresh"
        assert github_app.installation_token(app, 7, now=lapse - 300) == "ghs_1", "renewed"
        assert minted == ["ghs_0", "ghs_1"]
        # The owner's repositories are worked with it, in place of any `gh` account.
        assert (
            git_module.token_for("git@github.com:hermez/site.git", {"hermez": "salva"}) == "ghs_1"
        )
        assert github_app.issued("ghs_1") and not github_app.issued("gho_personal")
        assert github_app.token("someone-else") == ""


@case
def a_session_and_a_push_on_an_installed_owner_carry_the_app_token_and_its_bot():
    def answer(method, path, headers, body):
        if path.startswith("/app/installations?"):
            return 200, [
                {"id": 7, "account": {"login": "hermez"}, "repository_selection": "selected"}
            ]
        if path == "/app/installations/7/access_tokens":
            return 201, {"token": "ghs_session", "expires_at": "2099-01-01T00:00:00Z"}
        if path == "/users/ponos-laptop%5Bbot%5D":
            return 200, {"id": 99}
        if path.startswith("/installation/repositories"):
            return 200, {"repositories": [{"full_name": "hermez/site"}]}
        raise AssertionError(path)

    with _github_answering(answer):
        github_app.save(_test_app())
        given = github_app.session_environment("hermez")
        assert given["GH_TOKEN"] == given["GITHUB_TOKEN"] == "ghs_session"
        assert given["GIT_AUTHOR_NAME"] == given["GIT_COMMITTER_NAME"] == "ponos-laptop[bot]"
        assert given["GIT_AUTHOR_EMAIL"] == "99+ponos-laptop[bot]@users.noreply.github.com"
        assert "ghs_session" not in "".join(
            value for name, value in given.items() if name.startswith("GIT_CONFIG")
        ), "the token is read from the environment, never written into a git setting"
        assert github_app.session_environment("someone-else") == {}
        assert github_app.covers("hermez/site", "hermez") is True
        assert github_app.covers("hermez/other", "hermez") is False
        # What the runner itself runs with an app token: the token, and git told how to use it.
        seen = git_module.run(
            ["sh", "-c", 'echo "$GH_TOKEN $GIT_CONFIG_COUNT"'],
            token=git_module.token_for("https://github.com/hermez/site", None),
        )
        assert seen.out.split()[0] == "ghs_session" and int(seen.out.split()[1]) >= 5, seen.out
        # A `gh` account's token is passed as it always was, and nothing more.
        plain = git_module.run(
            ["sh", "-c", 'echo "$GH_TOKEN ${GIT_CONFIG_COUNT:-none}"'], token="gho_mine"
        )
        assert plain.out == "gho_mine none" or plain.out.startswith("gho_mine "), plain.out


@case
def without_a_github_app_the_gh_accounts_answer_as_before():
    with _github_answering(lambda *_: (500, {})) as calls:
        assert github_app.apps() == []
        assert git_module.token_for("hermez/site", {}) == ""
        assert github_app.covers("hermez/site", "hermez") is None
        assert github_app.describe() == []
        assert calls == [], "nothing is asked of GitHub when no app is connected"


@case
def git_is_given_the_app_token_through_its_environment_and_never_in_a_value():
    environment = github_app.git_environment(base={"GIT_CONFIG_COUNT": "2"})
    assert environment["GIT_CONFIG_COUNT"] == "7"
    assert "GIT_CONFIG_KEY_0" not in environment, "what was already carried stays where it was"
    assert environment["GIT_CONFIG_KEY_2"] == "credential.https://github.com.helper"
    assert environment["GIT_CONFIG_VALUE_2"] == ""
    assert "$GH_TOKEN" in environment["GIT_CONFIG_VALUE_3"]
    assert environment["GIT_CONFIG_VALUE_5"] == "git@github.com:"
    # A session's helper answers git with a token, for github.com only.
    out = io.StringIO()
    before = {name: os.environ.get(name) for name in ("GH_TOKEN", "PONOS_GITHUB_LAPSES")}
    os.environ.update(GH_TOKEN="ghs_held", PONOS_GITHUB_LAPSES=str(int(time.time()) + 3000))
    try:
        github_app.helper(
            ["get"], read=lambda: "protocol=https\nhost=github.com\npath=hermez/site.git\n", out=out
        )
        assert out.getvalue() == "username=x-access-token\npassword=ghs_held\n", out.getvalue()
        elsewhere = io.StringIO()
        github_app.helper(["get"], read=lambda: "protocol=https\nhost=gitlab.com\n", out=elsewhere)
        assert elsewhere.getvalue() == ""
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
