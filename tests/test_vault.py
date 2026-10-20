"""`vault.py`: the secrets a project's sessions are given, and kept out of everything written."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import httpx
from support import _bare_runner, _config, _http_answering, _tools, case

from ponos import config as C
from ponos import files, notion, prompt, session, vault

# -- the vault ---------------------------------------------------------------


@case
def the_vault_is_read_project_by_project_and_checked():
    """`[vault]` grants each project its own keys, and says what it cannot hand over."""
    settings = _config(
        '[vault]\nprovider = "pass"\n'
        '[vault.projects]\nLeadz = ["LEADZ_DOKPLOY_TOKEN"]\n'
        '[vault.projects.Ponos]\nNPM_TOKEN = "hermez-npm"\nGH_TOKEN = "keyring:service=gh"\n'
        'ANTHROPIC_API_KEY = "stolen"\nPONOS_NOTION_TOKEN = "stolen"\n"not a name" = "x"\n'
    ).vault
    assert settings.provider == "pass"
    assert settings.granted("leadz") == {"LEADZ_DOKPLOY_TOKEN": "LEADZ_DOKPLOY_TOKEN"}
    assert settings.granted(" PONOS ") == {
        "NPM_TOKEN": "hermez-npm",
        "GH_TOKEN": "keyring:service=gh",
    }
    assert settings.granted("Opoil") == {}, "a project the table does not name is given nothing"
    joined = "\n".join(settings.problems)
    assert "ANTHROPIC_API_KEY is the runner's own" in joined, joined
    assert "PONOS_NOTION_TOKEN is the runner's own" in joined, joined
    assert "'not a name' is not an environment variable name" in joined, joined
    assert C.Config.__dataclass_fields__["vault"]  # and an empty file has a vault too
    empty = _config("").vault
    assert empty.provider == "env" and empty.projects == {} and empty.problems == ()
    typo = _config('[vault]\nprovider = "1pass"\n').vault
    assert "vault.provider = '1pass'" in typo.problems[0]
    assert vault.where("pass:hermez/npm", "env") == ("pass", "hermez/npm")
    assert vault.where("service=gh account=a:b", "keyring") == ("keyring", "service=gh account=a:b")
    example = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text()
    assert "[vault]" in example and "[vault.projects]" in example


@case
def each_provider_reads_a_secret_and_tells_a_missing_one_from_a_locked_vault():
    vault.forget()
    os.environ["PONOS_TEST_VAULT"] = "from-the-environment"
    try:
        environment = vault.provider("env", {"IN_FILE": "from-secrets-env"})
        assert environment.read("PONOS_TEST_VAULT") == "from-the-environment"
        assert environment.read("IN_FILE") == "from-secrets-env"
        assert environment.read("NOWHERE") == ""
    finally:
        os.environ.pop("PONOS_TEST_VAULT")
    with _tools(
        {
            "pass": (
                "if sys.argv[2] == 'hermez/npm': print('npm_granular_abcdef\\nlogin: hermez')\n"
                "else: sys.stderr.write('Error: x is not in the password store.\\n'); sys.exit(1)\n"
            ),
            "secret-tool": (
                "if sys.argv[1:] == ['lookup', 'service', 'ponos', 'username', 'npm']: print('kr_secret_value', end='')\n"
                "elif sys.argv[1:] == ['lookup', 'service', 'gh', 'account', 'me']: print('kr_github_value', end='')\n"
                "else: sys.exit(1)\n"
            ),
            "bw": (
                "assert os.environ['BW_SESSION'] == 'unlocked'\n"
                "if sys.argv[3] == 'dokploy': print('bw_dokploy_value')\n"
                "else: sys.stderr.write('Not found.'); sys.exit(1)\n"
            ),
        }
    ):
        assert vault.provider("pass").read("hermez/npm") == "npm_granular_abcdef", (
            "the first line only"
        )
        assert vault.provider("pass").read("other") == ""
        assert vault.provider("keyring").read("npm") == "kr_secret_value"
        assert vault.provider("keyring").read("service=gh account=me") == "kr_github_value"
        assert vault.provider("keyring").read("absent") == ""
        try:
            vault.provider("bitwarden", {}).read("dokploy")
        except vault.VaultError as error:
            assert "BW_SESSION" in str(error)
        else:
            raise AssertionError("a locked Bitwarden is not an empty one")
        unlocked = vault.provider("bitwarden", {"BW_SESSION": "unlocked"})
        assert unlocked.read("dokploy") == "bw_dokploy_value"
        assert unlocked.read("absent") == ""
        found = vault.read(
            {"NPM_TOKEN": "hermez/npm", "DOKPLOY": "bitwarden:dokploy", "GONE": "nothing-here"},
            "pass",
            {"BW_SESSION": "unlocked"},
        )
        assert found.values == {"NPM_TOKEN": "npm_granular_abcdef", "DOKPLOY": "bw_dokploy_value"}
        assert found.missing == ["GONE (pass: no such item)"], found.missing
        assert "npm_granular_abcdef" not in "".join(found.missing)
        assert vault.mask("token npm_granular_abcdef here") == "token *** here", (
            "read is remembered"
        )
    try:
        vault.provider("onepassword")
    except vault.VaultError as error:
        assert "env, keyring, pass, bitwarden" in str(error)
    else:
        raise AssertionError("an unknown provider is said, not guessed")
    vault.forget()


@case
def a_secret_read_is_masked_wherever_it_would_be_written():
    vault.forget()
    try:
        vault.remember("abc")  # too short to be masked without masking the code
        assert vault.mask("abc") == "abc"
        vault.remember('tok"en\\value')
        vault.remember("npm_0123456789")
        assert vault.mask("NPM=npm_0123456789!") == "NPM=***!"
        assert vault.mask(json.dumps({"x": 'tok"en\\value'})) == '{"x": "***"}', (
            "the JSON spelling too"
        )
        assert vault.masked({"a": ["npm_0123456789", 3], "b": {"c": "ok"}}) == {
            "a": ["***", 3],
            "b": {"c": "ok"},
        }
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "x.err"
            stderr.write_text("auth failed for npm_0123456789\n")
            vault.scrub(stderr)
            assert stderr.read_text() == "auth failed for ***\n"
            # The Markdown board.
            board = files.Board(Path(directory) / "board", _config("").notion)
            database = board.resolve_database("Tickets")
            page = board.create_row(database, "Publish npm_0123456789")
            board.comment(page, "done with npm_0123456789")
            written = "".join(path.read_text() for path in Path(directory, "board").rglob("*.md"))
            assert "npm_0123456789" not in written and "***" in written, written
        # Notion: what is sent, whatever the call.
        sent: list[bytes] = []

        def answer(request):
            sent.append(request.content)
            return httpx.Response(200, json={})

        with _http_answering(answer):
            notion.Client("ntn_test").comment("p", "the key is npm_0123456789")
        assert sent and b"npm_0123456789" not in sent[0] and b"***" in sent[0], sent
    finally:
        vault.forget()


@case
def a_session_given_a_secret_never_writes_it_down():
    """What the session prints of its key is masked in its transcript, answer and stderr."""
    vault.forget()
    vault.remember("npm_supersecret_42")
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        (home / "claude").write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys\n"
            "sys.stdin.read()\n"
            "sys.stderr.write('debug ' + os.environ['NPM_TOKEN'] + '\\n')\n"
            "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'using ' + os.environ['NPM_TOKEN']}]}}))\n"
            "print(json.dumps({'type': 'result', 'result': 'published with ' + os.environ['NPM_TOKEN'] + '\\nRESULT: ok — done', 'session_id': 's'}))\n"
        )
        (home / "claude").chmod(0o755)
        previous = os.environ["PATH"]
        os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
        seen: list[dict] = []
        try:
            outcome = session.run(
                "go",
                cwd=home,
                log=home / "s.jsonl",
                timeout_minutes=1,
                environment={"NPM_TOKEN": "npm_supersecret_42"},
                on_event=seen.append,
            )
        finally:
            os.environ["PATH"] = previous
            vault.forget()
        assert outcome.ok, outcome.error
        assert "npm_supersecret_42" not in outcome.answer and "***" in outcome.answer
        assert "npm_supersecret_42" not in json.dumps(seen)
        assert "npm_supersecret_42" not in (home / "s.jsonl").read_text()
        assert (home / "s.err").read_text() == "debug ***\n"


@case
def a_ticket_session_is_given_its_project_secrets_by_name_only():
    vault.forget()
    runner = _bare_runner(None)
    runner.dry_run = False
    runner.config = _config('[vault]\n[vault.projects]\nLeadz = ["PONOS_TEST_LEADZ_KEY"]\n')
    os.environ["PONOS_TEST_LEADZ_KEY"] = "leadz_secret_value"
    try:
        leadz = type("J", (), {"project": type("P", (), {"name": "Leadz"})()})()
        other = type("J", (), {"project": type("P", (), {"name": "Ponos"})()})()
        assert runner._secrets(other) == {}, "nobody else's keys"
    finally:
        os.environ.pop("PONOS_TEST_LEADZ_KEY")
    # A PONOS_ name is refused for a project: the runner's own namespace.
    assert "PONOS_TEST_LEADZ_KEY is the runner's own" in runner.config.vault.problems[0]
    runner.config = _config('[vault]\n[vault.projects]\nLeadz = ["LEADZ_TEST_KEY"]\n')
    os.environ["LEADZ_TEST_KEY"] = "leadz_secret_value"
    try:
        assert runner._secrets(leadz) == {"LEADZ_TEST_KEY": "leadz_secret_value"}
        assert vault.mask("leadz_secret_value") == "***"
    finally:
        os.environ.pop("LEADZ_TEST_KEY")
        vault.forget()
    text = prompt.build(
        prompt.DOCUMENT,
        project="Leadz",
        title="t",
        body="b",
        repo="r",
        branch="b",
        base="main",
        url="u",
        secrets=["LEADZ_TEST_KEY"],
    )
    assert "# Secrets" in text and "`LEADZ_TEST_KEY`" in text and "leadz_secret_value" not in text
    assert "# Secrets" not in prompt.build(
        prompt.DEFAULT, project="p", title="t", body="b", repo="r", branch="b", base="m", url="u"
    )
