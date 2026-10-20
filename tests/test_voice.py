"""`voice.py`: the language the runner answers in, and every phrase in each of them."""

from __future__ import annotations

from support import case

from ponos import legacy, prompt, voice

# -- the language it answers in ----------------------------------------------


@case
def a_language_is_read_down_to_one_the_runner_speaks():
    """A locale, a capital, a language written out: all one answer."""
    for spelling in ("fr", "FR", "fr-FR", "fr_CA", " Français ", "french"):
        assert voice.understood(spelling) == "fr", spelling
    for spelling in ("en", "English", "en-GB", "anglais"):
        assert voice.understood(spelling) == "en", spelling
    # Not a failure: a typo in a language name must not be the reason a ticket
    # comes back unreported.
    assert voice.understood("") == voice.understood("klingon") == "en"


@case
def a_runner_nobody_told_a_language_says_exactly_what_it_used_to():
    """Empty is not “English”: it is “nobody decided”, and the prompts say so.

    Every template already carries its own rule — write in the language of the
    ticket, of the message — and a default that overrode it would answer a
    French ticket in English on the day this shipped.
    """
    common = dict(
        project="Animalink", title="t", body="b", repo="/r", branch="br", base="main", url="u"
    )
    assert prompt.build(prompt.DEFAULT, **common) == prompt.build(
        prompt.DEFAULT, **common, language=voice.Voice().instruction()
    )
    assert voice.Voice("").instruction() == ""
    assert voice.Voice("en").instruction(), "asking for English is still asking"

    asked = prompt.build(prompt.DEFAULT, **common, language=voice.Voice("fr").instruction())
    assert "Write in French" in asked
    assert asked.index("Write in French") < asked.index("End with a final line")
    assert "commit messages" in asked, "and the repository keeps its own language"


@case
def a_conversation_is_told_the_language_too_and_so_is_its_next_turn():
    """A thread that answers in French once and in English after is worse than
    a thread that never switched."""
    said = voice.Voice("fr")
    first = prompt.conversation(
        prompt.CONVERSATION,
        project="Animalink",
        title="t",
        body="b",
        where="w",
        url="u",
        message="et le footer ?",
        language=said.instruction(reply=True),
    )
    assert "Answer in French" in first
    assert "Answer in French" in prompt.follow_up("et le header ?", said.instruction(reply=True))
    assert prompt.follow_up("et le header ?") == prompt.FOLLOW_UP.format(
        message="et le header ?", language=""
    ), "and nothing at all when nothing was asked for"


@case
def a_report_opens_on_what_is_expected_of_you_and_says_it_in_three_lines():
    """The first line is a notification: it has eighty characters, and that is
    the whole of the design.

    Nothing in front of it — the host that used to sign every report spent its
    first forty-four characters saying which laptop was talking — and nothing
    under it but the sentence and the link.
    """
    for language, verdict, expected in (
        ("", "To review", "PR #1 · 3 commits · 18 minutes · $6.41"),
        ("fr", "À relire", "PR #1 · 3 commits · 18 minutes · 6,41 $"),
    ):
        said = voice.Voice(language)
        report = said.report(
            said.verdict(
                "review",
                said.say("pull-request", number="1"),
                said.count(3, "commit"),
                *said.spent(1092.0, 6.405),
            ),
            "Le header est parti.",
            "https://github.com/x/y/pull/1",
        )
        first = report.splitlines()[0]
        assert first == f"✅ {verdict} — {expected}", first
        assert len(first) <= 80, "a phone shows about that much, and then stops"
        assert len(report.splitlines()) == 3
        assert report.endswith("https://github.com/x/y/pull/1")
        assert "ponos@" not in report and "claude --resume" not in report

    assert voice.Voice().spent(90.0, 0.0) == ("2 minutes", ""), "no price, nothing to say"
    assert voice.Voice().verdict("failed") == "⚠️ Failed", "and no facts, no dash"


@case
def a_sentence_a_session_wrote_too_long_is_cut_on_a_word():
    """The prompt asks for one sentence and mostly gets one. Mostly is not a
    length, and a report is not where to find that out."""
    said = voice.Voice()
    assert said.brief("Le header est parti.") == "Le header est parti."
    assert said.brief("  two\n lines  ") == "two lines", "and a paragraph is one line"
    long = "ajoute la commande app:search:diagnose " * 10
    cut = said.brief(long)
    assert len(cut) <= voice.BRIEF and cut.endswith("…")
    assert not cut.rstrip("…").endswith(" "), "cut on a word, not mid-syllable"


@case
def a_report_is_told_from_an_answer_by_the_mark_it_opens_with():
    """Three places used to recognise the runner by the host it signed with, so
    dropping the host without putting something in its place would have had the
    next run read its own words back as an instruction."""
    assert voice.is_report("✅ To review — PR #1 · 2 commits")
    assert voice.is_report("🙋 Bloqué — quel en-tête ?")
    assert not voice.is_report("Celui du dashboard, pas du site public.")
    # A board does not start over when the runner is updated: the reports
    # already on it opened with a host, and are still ours.
    assert voice.is_report(f"{legacy.OLD}@laptop — done.\nFait.")
    assert voice.plain(f"{legacy.OLD}@laptop — done.\nFait.") == "done.\nFait."
    assert voice.plain("✅ To review — PR #1") == "✅ To review — PR #1"


@case
def a_measurement_is_rounded_to_something_a_person_would_say():
    """Nobody reports their afternoon to the tenth of a minute."""
    said = voice.Voice()
    assert said.minutes(1092.0) == "18 minutes"
    assert said.minutes(90.0) == "2 minutes"
    assert said.minutes(20.0) == "under a minute"
    assert voice.Voice("fr").minutes(20.0) == "moins d'une minute"
    assert said.count(1, "commit") == "1 commit" and said.count(3, "commit") == "3 commits"
    assert voice.Voice("fr").count(1, "block") == "1 bloc"


@case
def every_phrase_exists_in_every_language_it_claims_to_speak():
    """A key nobody translated is a sentence that fails the day it is said.

    Which is the whole risk of a table like this: the missing one is always the
    failure path, and the failure path is what nobody exercises before shipping.
    """
    for key, spellings in voice._SAID.items():
        assert set(spellings) == set(voice.LANGUAGES), key
        for language, text in spellings.items():
            assert text.strip(), f"{key}/{language}"
    assert voice.DEFAULT in voice.LANGUAGES
