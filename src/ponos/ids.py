"""One spelling of a page identifier, whoever wrote it.

Notion hands the same page back dashed in one answer and bare in the next, a URL
ends with it, a person pastes either. Every comparison, key and file name is
made on the bare form — thirty-two hexadecimal characters, no dashes — so that
one page is never two.
"""

from __future__ import annotations


def bare(identifier: object) -> str:
    """A page identifier without its dashes, nor the spaces around it."""
    return str(identifier or "").replace("-", "").strip()
