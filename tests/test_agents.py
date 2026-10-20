"""`agents.py`: the role a ticket is handled by."""

from __future__ import annotations

from support import case

from ponos import agents, notion

# -- the role a ticket is handled by -----------------------------------------


class _AgentClient:
    def __init__(self, page: notion.Page | None, brief: str = "", broken: bool = False):
        self._page, self._brief, self._broken = page, brief, broken

    def page(self, page_id: str) -> notion.Page:
        if self._page is None:
            raise notion.NotionError("object not found")
        return self._page

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        if self._broken:
            raise notion.NotionError("object not found")
        return self._brief


def _agent_page(title: str, model: str = "") -> notion.Page:
    properties = {"Name": {"type": "title", "title": [{"plain_text": title}]}}
    if model:
        properties["Model"] = {"type": "select", "select": {"name": model}}
    return notion.Page(id="p-agent", url="", title=title, properties=properties)


@case
def an_agent_is_a_page_and_may_name_its_model():
    client = _AgentClient(_agent_page("Rédacteur", "haiku"), brief="Ton direct, pas d'emoji.")
    agent = agents.resolve(client, "p-agent")
    assert agent.name == "Rédacteur"
    assert agent.brief == "Ton direct, pas d'emoji."
    assert agent.model == "haiku"
    assert agent, "a named agent is truthy"


@case
def an_unreadable_agent_is_no_agent_rather_than_a_failed_ticket():
    assert not agents.resolve(_AgentClient(None), "p-agent").name
    # The page reads but its body does not: the role is lost, the run is not.
    partial = agents.resolve(_AgentClient(_agent_page("Rédacteur"), broken=True), "p-agent")
    assert partial.name == "Rédacteur" and partial.brief == ""
    assert not agents.Agent(), "no agent at all is falsy"
