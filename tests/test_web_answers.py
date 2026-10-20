"""`web/answers.py`: what the schema says the API answers, for the page's types."""

from __future__ import annotations

from support import case


@case
def the_schema_says_what_each_route_answers_and_what_the_stream_carries():
    """A route names its answer, and a key that may be missing is not a key with a default.

    `openapi-typescript` reads a default as "always there": a key the answer
    may leave out must be out of `required` without one, or the page would be
    told it can count on it.
    """
    from ponos.web import app

    schema = app.schema()
    ok = schema["paths"]["/api/board"]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["$ref"].endswith("/Board"), ok
    events = schema["paths"]["/api/events"]["get"]["responses"]["200"]["content"]
    assert events["application/json"]["schema"]["$ref"].endswith("/Stream"), events
    shapes = schema["components"]["schemas"]
    ticket = shapes["Ticket"]
    assert "project_id" not in ticket["required"] and "column" in ticket["required"]
    assert "default" not in ticket["properties"]["project_id"], ticket["properties"]["project_id"]
    assert "default" not in ticket["properties"]["block"], ticket["properties"]["block"]
    assert ticket["properties"]["project_id"]["description"].startswith("The project's page id")
    # The names the page reads, not the ones Python could not use.
    assert "validate" in shapes["Board"]["properties"], shapes["Board"]["properties"]
    assert "from" in shapes["Statistics"]["required"], shapes["Statistics"]["required"]
    assert "global" in shapes["Validation"]["required"], shapes["Validation"]["required"]
    # A body the API reads and a shape it answers never share a name.
    assert "Decision" in shapes and "Chosen" in shapes, sorted(shapes)
