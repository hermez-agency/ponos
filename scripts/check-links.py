#!/usr/bin/env python3
"""Ask every external link of the README, the guide and the site whether it still answers.

`tests/test_release.py` already holds the links that point into this repository
to a page and a heading that exist, but only the network can say that a host
went away — uvicorn left www.uvicorn.org for uvicorn.dev, and the link kept
pointing at a name nobody resolves any more. That needs the network, which the
two suites never touch, so this runs once a week (`.github/workflows/links.yml`)
and never stands between a pull request and `main`: a site that is down for an
hour is not a reason to refuse a commit.

A link is dead when its host does not answer, or answers 404, 410 or 5xx. A
401, 403 or 429 is a site that turns robots away, not a missing page: it is
printed, and does not fail the run. The addresses the pages give as examples or
as a local console are not links to anything, and are skipped by `SKIPPED`.
Only the standard library: the job installs nothing.
"""

from __future__ import annotations

import concurrent.futures
import html
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["README.md", "CONTRIBUTING.md", "guide/*.md", "docs/*.html", "docs/llms.txt"]
LINK = re.compile(r"https?://[^\s)\"'<>`\]]+")
SKIPPED = re.compile(
    r"//(127\.0\.0\.1|localhost)[:/]"
    r"|example\.com|…|\.\.\.|<|/owner/repo|/you/|/your-"
    # origins the site preconnects to, and an API base: no page lives there
    r"|^https://fonts\.(googleapis|gstatic)\.com/?$|^https://raw\.githubusercontent\.com/$"
    r"|^https://openrouter\.ai/api/v1$"
)
REFUSING = {401, 403, 429}
AGENT = "Mozilla/5.0 (compatible; ponos-links; +https://github.com/hermez-agency/ponos)"


def links() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for pattern in PAGES:
        for page in sorted(ROOT.glob(pattern)):
            for match in LINK.finditer(page.read_text(encoding="utf-8")):
                url = html.unescape(match.group()).rstrip(".,;:").split("#")[0]
                if url and not SKIPPED.search(url):
                    found.setdefault(url, []).append(str(page.relative_to(ROOT)))
    return found


def status(url: str) -> int | str:
    """The HTTP status of `url`, or why nothing answered; a HEAD first, a GET if refused."""
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers={"User-Agent": AGENT})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return int(response.status)
        except urllib.error.HTTPError as error:
            if method == "GET" or error.code not in {*REFUSING, 404, 405}:
                return error.code
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            return str(reason)
    return "no answer"


def main() -> int:
    found = links()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        answers = dict(zip(found, pool.map(status, found), strict=True))
    dead = 0
    for url, answer in sorted(answers.items()):
        if isinstance(answer, int) and answer < 400:
            continue
        refusing = answer in REFUSING
        dead += not refusing
        where = ", ".join(sorted(set(found[url])))
        print(f"{'refused' if refusing else 'dead'}: {url} ({answer}) — {where}")
    print(f"{len(answers)} links, {dead} dead")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
