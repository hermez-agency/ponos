"""The shape every check shares, apart from the checks themselves.

Each group's module imports it from here rather than from the package, whose
`__init__` imports them all: one module below the others, so that none has to
ask the package for something it is still building.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import prerequisites

OK, WARN, ERROR, INFO = "ok", "warn", "error", "info"


# One probe never holds a page for longer than this — `provider.CHECK_TIMEOUT`
# is for a single call, and a remote that does not answer is the case at hand.
PROBE_TIMEOUT = 15


@dataclass
class Check:
    code: str
    group: str
    state: str
    title: str
    said: str
    params: dict[str, str] = field(default_factory=dict)
    # Why it is likely so, and what to do by hand: sentences like `said`.
    cause: str = ""
    steps: list[str] = field(default_factory=list)
    url: str = ""
    # What a tool printed, quoted — never translated.
    evidence: str = ""
    # What each name in a list is worth: {"name", "said": [sentences]}, the
    # sentences templates like the rest, the name a thing of the user's own.
    notes: list[dict[str, Any]] = field(default_factory=list)
    # {"action", "label", "confirm", "target"} when Ponos can make the fix.
    fix: dict[str, str] | None = None

    def text(self, template: str) -> str:
        """A sentence of this check with its holes filled, for the terminal."""
        return re.sub(
            r"\{\{(\w+)\}\}", lambda hole: str(self.params.get(hole[1], hole[0])), template
        )

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


def _check(code: str, state: str, title: str, said: str, **rest: Any) -> Check:
    return Check(code, code.split(".", 1)[0], state, title, said, **rest)


def _first_line(error: object) -> str:
    return (str(error).strip().splitlines() or [""])[0]


INSTALL_STEP = "Install it: `{{command}}`."


def _installing(tool: str, *steps: str) -> dict[str, Any]:
    """The steps of a check whose tool is missing: the command that installs it here first.

    Spread into `_check`, with the `params` that fill it — none when no package
    manager is known here.
    """
    command = prerequisites.install_command(tool)
    if not command:
        return {"steps": list(steps)}
    return {"steps": [INSTALL_STEP, *steps], "params": {"command": command}}


def _fix(
    action: str, label: str, confirm: str, names: list[str], target: str = ""
) -> dict[str, str]:
    return {
        "action": action,
        "label": label,
        "confirm": confirm,
        "missing": ", ".join(f"“{name}”" for name in names),
        "target": target,
    }
