"""`ids.py`: one spelling of a page identifier."""

from __future__ import annotations

from support import case

from ponos import ids


@case
def a_page_identifier_is_bare_however_it_was_given():
    bare = "402451680af48192b424d96f83aa3e7b"
    assert ids.bare("40245168-0af4-8192-b424-d96f83aa3e7b") == bare
    assert ids.bare(f" {bare}\n") == bare
    assert ids.bare(bare) == bare
    assert ids.bare(None) == ""
    assert ids.bare("") == ""
