"""`preparation.py`: a ticket turned into a job, and claimed."""

from __future__ import annotations

from support import _nameless, _NamelessClient, _naming_session, case

from ponos import notion

# -- the claim ----------------------------------------------------------------


class _MovedClient(_NamelessClient):
    """The same ticket, which somebody can move while it is being prepared."""

    def __init__(self, body: str):
        super().__init__(body)
        self.status = "Ready"
        self.said: list[str] = []

    def page(self, page_id: str) -> notion.Page:
        return notion.Page(
            id=page_id,
            url="",
            title="",
            properties={"Status": {"type": "status", "status": {"name": self.status}}},
        )

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.said.append(text)


@case
def a_ticket_moved_out_of_ready_while_it_is_prepared_is_not_run(state_home):
    """Naming it took a session; it was cancelled meanwhile. The claim does not
    take, so no job comes out — and the cancellation is not failed over."""
    runner, ticket = _nameless("", "Le bandeau de la console reste blanc au chargement.")
    ticket.page.properties["Status"] = {"type": "status", "status": {"name": "Ready"}}
    client = runner.client = _MovedClient("Le bandeau de la console reste blanc au chargement.")
    with _naming_session("Réparer le bandeau blanc de la console") as asked:
        original = runner._name

        def cancelled_while_named(*args):
            original(*args)
            client.status = "Cancelled"

        runner._name = cancelled_while_named
        job = runner.prepare(ticket)

    assert asked, "the naming session ran before the claim"
    assert job is None, "no session is started on a cancelled ticket"
    assert not [values for values in client.written if "Status" in values or "Runner" in values]
    # The model is chosen, and said, before the claim: only a failure is wrong here.
    assert [text for text in client.said if "Model chosen" not in text] == [], "no failure"


@case
def a_ticket_still_in_ready_is_claimed_as_ever(state_home):
    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    ticket.page.properties["Status"] = {"type": "status", "status": {"name": "Ready"}}
    client = runner.client = _MovedClient("Il coûte 12 % de CPU pour rien.")
    with _naming_session(""):
        job = runner.prepare(ticket)

    assert job is not None
    assert [values for values in client.written if values.get("Status") == "In progress"]
