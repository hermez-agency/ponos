"""`scripts/build_blog.py`: the blog is a build that is committed, and it must stay one."""

from __future__ import annotations

import json
import re
import subprocess
import sys

import build_blog
from support import ROOT, case


@case
def the_committed_blog_is_what_the_articles_give() -> None:
    """Pages serves `docs/` as it is: an article added without the build is not published.

    `python3 scripts/build_blog.py --check` is the same refusal the pre-commit gesture
    would be — a new `.md` under `blog/content/` and nothing else to touch.
    """
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_blog.py"), "--check"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr


@case
def every_article_page_carries_what_a_search_engine_reads() -> None:
    articles = build_blog.load()
    assert articles["en"] and articles["fr"], "the first article has no EN + FR pair"
    for lang, items in articles.items():
        for a in items:
            page = (
                ROOT / "docs" / build_blog._prefix(lang) / "blog" / a.slug / "index.html"
            ).read_text(encoding="utf-8")
            assert f"<title>{build_blog._e(a.title)} — Ponos</title>" in page
            assert f'<link rel="canonical" href="{a.url}">' in page
            assert f'<html lang="{lang}">' in page
            for tag in ("og:title", "og:description", "og:image", "twitter:card", "twitter:image"):
                assert tag in page, f"{a.slug} has no {tag}"
            blocks = re.findall(
                r'<script type="application/ld\+json">\n(.*?)\n</script>', page, re.S
            )
            kinds = {json.loads(block)["@type"] for block in blocks}
            assert {"BlogPosting", "BreadcrumbList"} <= kinds
            posting = next(json.loads(b) for b in blocks if '"BlogPosting"' in b)
            assert (
                posting["author"]["name"] == "Hermez" and posting["publisher"]["name"] == "Hermez"
            )
            assert "<script" not in re.sub(
                r"<script.*?</script>", "", page, flags=re.S
            )  # reading needs none
            if a.translation:
                assert (
                    'hreflang="x-default"' in page
                    and 'hreflang="fr"' in page
                    and 'hreflang="en"' in page
                )


@case
def the_sitemap_the_feeds_and_llms_txt_list_the_articles() -> None:
    sitemap = (ROOT / "docs/sitemap.xml").read_text(encoding="utf-8")
    llms = (ROOT / "docs/llms.txt").read_text(encoding="utf-8")
    for lang, items in build_blog.load().items():
        feed = (ROOT / "docs" / build_blog._prefix(lang) / "blog/feed.xml").read_text(
            encoding="utf-8"
        )
        for a in items:
            assert f"<loc>{a.url}</loc>" in sitemap
            assert a.url in feed and a.url in llms
    for url in ("https://the-ponos.app/blog/", "https://the-ponos.app/fr/blog/"):
        assert f"<loc>{url}</loc>" in sitemap


@case
def the_landing_pages_link_the_blog_in_header_and_footer() -> None:
    for page, href in (("docs/index.html", "blog/"), ("docs/fr/index.html", "blog/")):
        text = (ROOT / page).read_text(encoding="utf-8")
        assert text.count(f'<a class="btn btn-ghost btn-sm" href="{href}">Blog</a>') == 1
        assert f'<a href="{href}">Blog</a>' in text


@case
def markdown_keeps_html_out_of_the_text_and_scripts_out_of_links() -> None:
    assert "<h2" in build_blog.markdown("# T\n")  # the page's h1 is the header's
    html = build_blog.markdown("a & b [x](javascript:alert(1)) `<i>`\n")
    assert "javascript:" not in html and "&lt;i&gt;" in html and "a &amp; b" in html
