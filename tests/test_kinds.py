"""`kinds.py`: the type of a ticket."""

from __future__ import annotations

from pathlib import Path

from support import _nameless, _naming_session, _saved, _state_home, _TypedClient, case

from ponos import config as C
from ponos import kinds, projects, prompt, question, state, voice
from ponos.web import settings as web_settings

# -- the type of a ticket ----------------------------------------------------


@case
def a_classification_is_read_out_of_whatever_the_session_wrapped_it_in():
    said = (
        'Voici :\n```json\n{"type": "Publication", "reason": "Un  post.", '
        '"confidence": "HIGH", "alternative": "writing"}\n```'
    )
    guess = kinds.parse(said)
    assert (guess.kind, guess.confidence, guess.alternative) == ("publication", "high", "writing")
    assert guess.reason == "Un post."
    assert kinds.parse("je ne sais pas") == kinds.Guess(), "no object is no type"
    unknown = kinds.parse('{"type": "deploy", "confidence": "sure"}')
    assert unknown.kind == "" and unknown.confidence == "low", "outside the four is nothing"
    same = kinds.parse('{"type": "code", "confidence": "high", "alternative": "code"}')
    assert same.alternative == "", "hesitating with itself is not hesitating"


@case
def a_doubt_is_never_settled_by_running_the_ticket():
    """Too unsure, or unsure between a harmless type and one that acts on the
    world: either way it is a question — and in doubt, the careful type."""
    sure = kinds.Guess("writing", "", "high", "")
    assert kinds.doubt(sure) == ""
    assert kinds.doubt(kinds.Guess()) == "unknown"
    assert kinds.doubt(kinds.Guess("code", "", "low", "")) == "unsure"
    assert kinds.doubt(kinds.Guess("code", "", "medium", ""), "high") == "unsure"
    assert kinds.doubt(kinds.Guess("code", "", "low", ""), "low") == ""
    assert kinds.doubt(kinds.Guess("writing", "", "high", "publication")) == "hesitant"
    assert kinds.doubt(kinds.Guess("external", "", "high", "code")) == "hesitant"
    assert kinds.doubt(kinds.Guess("code", "", "high", "writing")) == "", (
        "hesitating between two harmless types is not a reason to stop"
    )
    assert kinds.prudent("writing", "publication") == "publication"
    assert kinds.prudent("code", "external") == "external"
    assert kinds.prudent("code", "writing") == "code"


@case
def a_doubt_between_code_and_another_type_takes_the_one_that_needs_no_commit():
    """An audit, a deployment, a setting in production: about code, not code.

    Settled rather than asked, whatever the confidence — and said, so the
    choice can be corrected where it was made.
    """
    for kind, alternative, taken in (
        ("code", "external", "external"),
        ("external", "code", "external"),
        ("code", "writing", "writing"),
        ("writing", "code", "writing"),
        ("code", "publication", "publication"),
    ):
        settled = kinds.settle(kinds.Guess(kind, "", "low", alternative))
        assert (settled.kind, settled.settled, settled.alternative) == (taken, "code", ""), settled
        assert kinds.doubt(settled) == "", "settled is not a doubt"
    plain = kinds.Guess("code", "", "low", "")
    assert kinds.settle(plain) is plain and kinds.doubt(plain) == "unsure", (
        "unsure of code alone is still a question"
    )
    risky = kinds.Guess("writing", "", "high", "publication")
    assert kinds.settle(risky) is risky and kinds.doubt(risky) == "hesitant"
    asked = kinds.prompt("Audit", "Ne code rien.", project="Site", repository=True)
    assert "An audit, a review, a check or a verification is writing" in asked
    assert "Deploying or redeploying" in asked
    assert "Between code and another type, choose the other one" in asked


@case
def a_ticket_settled_off_code_says_so_on_the_ticket(state_home):
    runner, ticket = _typed(body="Vérifie que la prod répond, ne code rien.")
    answer = (
        '{"type": "code", "reason": "Peut-être un correctif.", "confidence": "low", '
        '"alternative": "external"}'
    )
    with _naming_session(answer):
        job = runner.prepare(ticket)

    assert job is not None and job.kind == "external" and not job.project.is_code
    assert runner.client.written[0] == {"Type": "Action externe"}, runner.client.written
    said = runner.client.said[0]
    assert "Code" in said and "commit" in said, said


@case
def a_report_of_work_done_outside_the_repository_is_told_from_a_code_change():
    from ponos import execution

    for outside in (
        "Variable SMTP_HOST ajoutée dans Dokploy, application redéployée.",
        "6 bugs et 13 idées créés dans Notion.",
        "Enregistrement DNS ajouté chez OVH, le domaine répond.",
        "Redeployed the app with the new environment variable.",
    ):
        assert execution._done_elsewhere(outside), outside
    for code in (
        "J'ai corrigé le fichier de configuration puis redéployé dans Dokploy.",
        "Changed src/app.ts and redeployed.",
        "Le titre de la page est corrigé.",
        "",
    ):
        assert not execution._done_elsewhere(code), code
    assert execution._report("Fait.\n\n**RESULT: ok — fait**") == "Fait."


@case
def the_classification_is_told_whether_there_is_a_repository():
    asked = kinds.prompt(
        "Le DNS",
        "Ajoute un CNAME.",
        project="Site",
        repository=False,
        comments=["the ticket's author: c'est chez Hostinger"],
    )
    assert "no code repository: it cannot be a code ticket" in asked
    assert "Ajoute un CNAME." in asked and "c'est chez Hostinger" in asked
    assert "belongs to no project" in kinds.prompt("x", "", project="", repository=False)
    assert "has a code repository" in kinds.prompt("x", "", project="Site", repository=True)


@case
def a_board_spells_the_types_in_either_language():
    """A board built by hand in French reads as typed, not as four unknown words."""
    settings = C.Notion()
    assert settings.kind_of("Rédaction") == "writing"
    assert settings.kind_of(" action externe ") == "external"
    assert settings.kind_of("Code") == "code" and settings.kind_of("Writing") == "writing"
    assert settings.kind_of("Urgent") == "" and settings.kind_of("") == ""
    named = C.Notion(types={"writing": "Texte"})
    assert named.kind_of("Texte") == "writing"
    assert named.kind_of("Rédaction") == "", "a name the file chose is the only one read"


@case
def a_type_somebody_chose_takes_a_repository_ticket_off_its_repository():
    project = projects.Project(name="Site", path=Path("/repo"))
    assert kinds.worked_in(project, "code") is project
    assert kinds.worked_in(project, "") is project
    for kind in ("writing", "external", "publication"):
        assert not kinds.worked_in(project, kind).is_code, kind
        assert kinds.worked_in(project, kind).name == "Site"
    assert "prepare it, do not publish it" in prompt.kind("publication")
    assert "Stop at the first doubt" in prompt.kind("external")
    assert prompt.kind("writing") == "" and prompt.kind("code") == ""
    assert "/repo: read it" in prompt.kind("writing", Path("/repo"))


@case
def a_prompt_file_older_than_the_types_still_says_do_not_publish():
    """A template of your own has no `{kind}`: the rule is added at its end."""
    built = prompt.build(
        "Old template — {title}\n{body}",
        project="",
        title="Post",
        body="Un post.",
        repo="/tmp/x",
        branch="",
        base="",
        url="u",
        kind=prompt.kind("publication"),
    )
    assert built.startswith("Old template — Post")
    assert built.rstrip().endswith(prompt.PREPARE.rstrip())
    document = prompt.build(
        prompt.DOCUMENT,
        project="",
        title="Post",
        body="Un post.",
        repo="/tmp/x",
        branch="",
        base="",
        url="u",
        kind=prompt.kind("publication"),
    )
    assert document.index("do not publish it") < document.index("# What is expected")
    plain = prompt.build(
        prompt.DOCUMENT,
        project="",
        title="Post",
        body="Un post.",
        repo="/tmp/x",
        branch="",
        base="",
        url="u",
    )
    assert "- Notion ticket: u\n\n# What is expected" in plain, "no type, no change"


@case
def every_session_reads_what_it_may_do_alone():
    """The policy is in the prompt of each ticket, the list written or the default."""
    common = dict(project="", title="T", body="b", repo="/tmp/x", branch="", base="", url="u")
    for template in (prompt.DEFAULT, prompt.DOCUMENT, prompt.DELIVERY, prompt.RESOLVE):
        text = prompt.build(
            template, **common, allowed=["relancer une CI"], ask=["modifier un DNS"]
        )
        assert "You do these without asking:\n- relancer une CI" in text, template[:30]
        assert "before these" in text and "- modifier un DNS" in text
        assert (
            text.index("# What you may do alone") < text.index("# Context")
            or "{agent}" not in template
        )
        assert "access.sudo" in text and "access.credentials" in text
    old = prompt.build("Old template — {title}", **common, allowed=["relancer une CI"])
    assert "- relancer une CI" in old, "a prompt file of your own gets it at its end"
    nothing = prompt.build(prompt.DEFAULT, **common)
    assert "You do these without asking" not in nothing and "access.sudo" in nothing
    assert "# What you may do alone" not in prompt.conversation(
        prompt.CONVERSATION, project="", title="T", body="b", where="w", url="u", message="m"
    )

    defaults = C.Permissions()
    assert "relancer une CI" in defaults.allowed and "fusionner une PR validée" in defaults.allowed
    assert any("cloner" in rule for rule in defaults.allowed)
    assert "toute dépense" in defaults.ask and "modifier un DNS" in defaults.ask
    assert C.load(_saved()[0]).permissions == defaults


@case
def the_permissions_name_nobody():
    """Every installation reads them: the defaults and the prompt around them are
    nobody's in particular — the owners named are the ones `[github]` knows."""
    names = ("Salva", "SalvadorCardona", "hermez", "cardona", "Northwind", "Dokploy")
    defaults = C.Permissions()
    for text in (
        prompt.permissions(),
        prompt.permissions(defaults.allowed, defaults.ask),
        *defaults.allowed,
        *defaults.ask,
    ):
        for name in names:
            assert name.lower() not in text.lower(), (name, text)
    assert "this project's GitHub owner" in " ".join(prompt.permissions().split())
    owned = " ".join(prompt.permissions(owners=["acme", "acme-bot", "acme"]).split())
    assert "owned by this project's GitHub owner or `acme` or `acme-bot`," in owned, (
        "a ticket aimed at another repository of a known owner is not a question either"
    )


@case
def the_permissions_are_edited_in_the_settings_and_an_empty_list_is_an_answer():
    path, config = _saved()
    drawn = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    assert drawn["permissions.allowed"]["fallback"] == list(C.ALLOWED)
    assert drawn["permissions.ask"]["value"] is None
    web_settings.save(
        config,
        {
            "settings": {
                "permissions.allowed": [" relancer   une CI ", "", "fusionner une PR validée"],
                "permissions.ask": [],
            }
        },
    )
    saved = C.load(path).permissions
    assert saved.allowed == ("relancer une CI", "fusionner une PR validée")
    assert saved.ask == (), "emptied is written, not brought back to the default"
    web_settings.save(config, {"settings": {"permissions.ask": None}})
    assert C.load(path).permissions.ask == C.ASK
    try:
        web_settings.save(config, {"settings": {"permissions.allowed": "relancer une CI"}})
        raise AssertionError("a string is not a list")
    except ValueError:
        pass


@case
def a_ticket_that_needs_sudo_blocks_with_the_commands_and_no_yes_no():
    answer = (
        "Tailscale needs root.\n"
        "DONE: nothing\n"
        "WHY: je n'ai pas le mot de passe sudo\n"
        "QUESTION: Lance ces commandes puis réponds « fait »\n"
        "MODE: yes-no\n"
        "CODE: access.sudo\n"
        "COMMAND: sudo apt install -y tailscale\n"
        "COMMAND: `sudo tailscale up`\n"
        "RESULT: blocked — sudo demande un mot de passe"
    )
    asked = question.parse(answer)
    assert asked.code == "access.sudo" and asked.mode == "free", "never a yes-no"
    assert asked.commands == ["sudo apt install -y tailscale", "sudo tailscale up"]
    lines = voice.Voice("fr").question(asked)
    assert lines[1] == "`access.sudo`"
    assert lines[2:4] == ["`sudo apt install -y tailscale`", "`sudo tailscale up`"]
    assert lines[-1].startswith("Lance ces commandes") and "oui" not in lines[-1].lower()
    unknown = question.parse("QUESTION: ok ?\nMODE: yes-no\nCODE: whatever\nCOMMAND: rm -rf /")
    assert unknown.code == "" and unknown.commands == [] and unknown.mode == "yes-no"


def _typed(kind: str = "", body: str = "Poste l'annonce de la v2 sur LinkedIn."):
    runner, ticket = _nameless("Annoncer la v2", body)
    runner.client = _TypedClient(body)
    if kind:
        ticket.page.properties["Type"] = {"type": "select", "select": {"name": kind}}
    return runner, ticket


@case
def a_ticket_with_no_type_is_classified_before_it_runs(state_home):
    """Written on the page in the board's own spelling, and explained in a comment."""
    runner, ticket = _typed()
    answer = (
        '{"type": "writing", "reason": "Il demande un texte.", "confidence": "high", '
        '"alternative": ""}'
    )
    with _naming_session(answer) as asked:
        job = runner.prepare(ticket)

    assert len(asked) == 1 and "say what kind of ticket it is" in asked[0]
    assert runner.client.written[0] == {"Type": "Rédaction"}, runner.client.written
    assert runner.client.said[0].startswith("🏷️") and "Il demande un texte." in runner.client.said[0]
    assert job is not None and job.kind == "writing"
    assert not job.project.is_code and job.reference == Path("/repo"), (
        "a text is not worked in the repository, only allowed to read it"
    )


@case
def the_classification_session_counts_against_the_daily_limit(state_home):
    runner, ticket = _typed()
    answer = '{"type": "writing", "reason": "Un texte.", "confidence": "high", "alternative": ""}'
    with _naming_session(answer, cost=0.25):
        runner.prepare(ticket)
    assert state.spent_today() == 0.25, state.spent_today()


@case
def a_type_somebody_chose_is_never_classified_again(state_home):
    runner, ticket = _typed("Code")
    with _naming_session('{"type": "publication", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)

    assert asked == [], "a chosen type costs no session"
    assert all("Type" not in values for values in runner.client.written)
    assert job is not None and job.kind == "code" and job.project.is_code


@case
def a_classification_that_is_not_sure_blocks_the_ticket_with_the_question():
    """Nothing claimed, no type written — the column is left for you to fill."""
    runner, ticket = _typed()
    answer = (
        '{"type": "writing", "reason": "Rédiger, ou publier ?", "confidence": "high", '
        '"alternative": "publication"}'
    )
    with _state_home(), _naming_session(answer):
        job = runner.prepare(ticket)

    assert job is None
    assert runner.client.written == [{"Status": "Blocked", "Blocage": "ticket.kind-unsure"}], (
        runner.client.written
    )
    question = runner.client.said[-1]
    assert "Rédaction or Publication?" in question and "Rédiger, ou publier ?" in question
    assert "I would take Publication" in question, "in doubt, the careful one"

    runner, ticket = _typed()
    with _state_home(), _naming_session('{"type": "code", "confidence": "low"}'):
        assert runner.prepare(ticket) is None
    assert runner.client.written == [{"Status": "Blocked", "Blocage": "ticket.kind-unsure"}]

    runner, ticket = _typed()
    with _state_home(), _naming_session("", missing=True):
        assert runner.prepare(ticket) is None, "no answer at all is the deepest doubt"


@case
def a_board_without_the_column_or_the_setting_runs_tickets_as_before():
    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    with _state_home(), _naming_session('{"type": "writing", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [] and job.kind == "" and job.project.is_code

    runner, ticket = _typed()
    runner.config.runner.classify = False
    with _state_home(), _naming_session('{"type": "writing", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [] and job.kind == "" and job.project.is_code
