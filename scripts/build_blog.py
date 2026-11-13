#!/usr/bin/env python3
"""Le blog du site, des fichiers Markdown aux pages que GitHub Pages sert.

    python3 scripts/build_blog.py          écrit docs/blog/, docs/fr/blog/, sitemap.xml et le bloc Blog de llms.txt
    python3 scripts/build_blog.py --check  ne touche à rien, échoue si ce qui est commité n'est plus ce que les articles donnent

Pourquoi un build commité plutôt qu'une étape du workflow : GitHub Pages sert
`docs/` tel quel, sans workflow, et le site entier doit rester lisible sans
outil — comme `src/ponos/web/static/`, la sortie vit dans le dépôt et un test
(`tests/test_blog.py`) refuse qu'elle ait pris du retard sur les sources.

Les sources sont à la racine (`blog/content/<lang>/<slug>.md`), pas sous
`docs/` : tout ce qui est sous `docs/` est servi, et un test y refuse le
Markdown. Un article est donc un fichier à ajouter, puis ce script à lancer ;
aucun code à toucher.

Le rendu reprend `site/src/ui/article.tsx` de Brand Assets (colonne de lecture,
en-tête, figure large, citation, encadré, pied, carte d'article) en classes
écrites à la main dans `docs/blog/blog.css` : le site n'est pas en React, et
n'a pas de build à qui confier Tailwind. Rien ici ne nomme une couleur ; tout
vient de `docs/tokens.css`.

Le convertisseur Markdown est le nôtre, en bibliothèque standard : le cœur n'a
pas le droit d'une dépendance de plus pour un script de site, et les articles
n'ont besoin que d'un sous-ensemble — titres, paragraphes, listes, code,
citations, tableaux, images, liens, emphase. Ce qui n'y est pas se dit par du
HTML brut dans l'article.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "blog" / "content"
DOCS = ROOT / "docs"
SITE = "https://the-ponos.app"
LANGS = ("en", "fr")
DEFAULT_COVER = "mascot/og.png"
DOCS_URL = "https://github.com/hermez-agency/ponos#readme"
LLMS_START = "<!-- blog:start — écrit par scripts/build_blog.py -->"
LLMS_END = "<!-- blog:end -->"

MONTHS = {
    "en": "January February March April May June July August September October November December",
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
}

OTHER_LINKS = {
    "en": ("Documentation", "Repository", "Changelog"),
    "fr": ("Documentation", "Dépôt", "Changelog"),
}

WORDS: dict[str, dict[str, str]] = {
    "en": {
        "blog": "Blog",
        "home": "Ponos",
        "docs": "Docs",
        "minutes": "min read",
        "min": "min",
        "tagline": "Notes from the people who build Ponos: how it runs Claude Code on a backlog, and what we learn doing it.",
        "index_title": "Blog — Ponos",
        "index_description": "Articles on running Claude Code on your backlog with Ponos: tickets, worktrees, pull requests, and what we learn doing it.",
        "empty": "No article yet.",
        "signature": "A Hermez product",
        "read_also": "Keep reading",
        "switch": "FR",
        "switch_label": "Lire cette page en français",
        "toggle": "Switch between light and dark",
        "feed": "Atom feed",
        "licence": "Ponos — MIT licence",
        "section_of": "Articles",
    },
    "fr": {
        "blog": "Blog",
        "home": "Ponos",
        "docs": "Docs",
        "minutes": "min de lecture",
        "min": "min",
        "tagline": "Les notes de ceux qui font Ponos : comment il fait tourner Claude Code sur un backlog, et ce qu'on y apprend.",
        "index_title": "Blog — Ponos",
        "index_description": "Des articles sur Claude Code lancé sur ton backlog avec Ponos : tickets, worktrees, pull requests, et ce qu'on y apprend.",
        "empty": "Pas encore d'article.",
        "signature": "Un produit Hermez",
        "read_also": "À lire aussi",
        "switch": "EN",
        "switch_label": "Read this page in English",
        "toggle": "Basculer entre clair et sombre",
        "feed": "Flux Atom",
        "licence": "Ponos — licence MIT",
        "section_of": "Articles",
    },
}


@dataclass
class Article:
    lang: str
    slug: str
    title: str
    description: str
    published: str
    updated: str
    cover: str
    cover_alt: str
    tags: list[str]
    translation: str
    category: str
    body: str
    source: Path = field(repr=False, default=Path())

    @property
    def path(self) -> str:
        return f"{_prefix(self.lang)}blog/{self.slug}/"

    @property
    def url(self) -> str:
        return f"{SITE}/{self.path}"

    @property
    def minutes(self) -> int:
        text = re.sub(r"```.*?```", "", self.body, flags=re.S)
        return max(1, round(len(re.findall(r"\w+", text)) / 200))


def _prefix(lang: str) -> str:
    return "" if lang == "en" else f"{lang}/"


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def format_date(iso: str, lang: str) -> str:
    day = date.fromisoformat(iso)
    month = MONTHS[lang].split()[day.month - 1]
    if lang == "fr":
        return f"{'1er' if day.day == 1 else day.day} {month} {day.year}"
    return f"{month} {day.day}, {day.year}"


# -- le frontmatter -----------------------------------------------------------------


def parse(source: Path, lang: str) -> Article:
    raw = source.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n(.*)\Z", raw, flags=re.S)
    if not match:
        raise SystemExit(f"{source}: il manque le frontmatter (--- … ---) en tête")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise SystemExit(f"{source}: ligne de frontmatter illisible : {line!r}")
        meta[key.strip()] = value.strip().strip("\"'")
    for required in ("title", "description", "date"):
        if not meta.get(required):
            raise SystemExit(f"{source}: le frontmatter n'a pas de `{required}`")
    if meta.get("lang", lang) != lang:
        raise SystemExit(f"{source}: `lang: {meta['lang']}` dans le dossier {lang}/")
    for key in ("date", "updated"):
        if meta.get(key):
            try:
                date.fromisoformat(meta[key])
            except ValueError:
                raise SystemExit(f"{source}: `{key}` doit s'écrire AAAA-MM-JJ") from None
    tags = [
        t.strip().strip("\"'") for t in meta.get("tags", "").strip("[]").split(",") if t.strip()
    ]
    return Article(
        lang=lang,
        slug=source.stem,
        title=meta["title"],
        description=meta["description"],
        published=meta["date"],
        updated=meta.get("updated", ""),
        cover=meta.get("cover", ""),
        cover_alt=meta.get("cover_alt", ""),
        tags=tags,
        translation=meta.get("translation", ""),
        category=meta.get("category", ""),
        body=match.group(2).strip() + "\n",
        source=source,
    )


def load() -> dict[str, list[Article]]:
    found: dict[str, list[Article]] = {lang: [] for lang in LANGS}
    for lang in LANGS:
        for source in sorted((CONTENT / lang).glob("*.md")):
            found[lang].append(parse(source, lang))
        found[lang].sort(key=lambda a: (a.published, a.slug), reverse=True)
    for lang, articles in found.items():
        for article in articles:
            if article.translation:
                other = "fr" if lang == "en" else "en"
                if not any(a.slug == article.translation for a in found[other]):
                    raise SystemExit(
                        f"{article.source}: `translation: {article.translation}` n'existe pas en {other}"
                    )
    return found


# -- Markdown -------------------------------------------------------------------------


def slugify(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = html.unescape(text)
    folded = (
        text.replace("é", "e").replace("è", "e").replace("ê", "e").replace("à", "a")
        .replace("ç", "c").replace("ô", "o").replace("î", "i").replace("û", "u")
        .replace("ù", "u").replace("â", "a")
    )  # fmt: skip
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def asset_url(url: str) -> str:
    """Une image écrite `mascot/og.png` s'entend depuis la racine du site, pas depuis la page."""
    return url if re.match(r"([a-z][a-z0-9+.-]*:|/|#)", url, flags=re.I) else "/" + url


def safe_url(url: str) -> str:
    return "#" if re.match(r"\s*(javascript|data|vbscript):", url, flags=re.I) else url


def inline(text: str) -> str:
    """Code, images, liens, gras, italique — et le reste est échappé."""
    spans: list[str] = []

    def stash(value: str) -> str:
        spans.append(value)
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"(`+)(.+?)\1", lambda m: stash(f"<code>{_e(m.group(2).strip())}</code>"), text)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)",
        lambda m: stash(
            f'<img src="{_e(asset_url(safe_url(m.group(2))))}" alt="{_e(m.group(1))}" loading="lazy">'
        ),
        text,
    )
    text = _e(text)

    def link(m: re.Match[str]) -> str:
        href = html.unescape(m.group(2))
        external = re.match(r"https?://", href) and not href.startswith(SITE)
        rel = ' rel="noopener"' if external else ""
        return stash(f'<a href="{_e(safe_url(href))}"{rel}>{m.group(1)}</a>')

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<em>\1</em>", text)
    for _ in range(2):  # un lien peut en contenir un autre morceau mis de côté
        text = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)
    return text


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def markdown(source: str) -> str:
    lines = source.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = re.match(r"```\s*([\w+-]*)", line)
        if fence:
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            lang = f' class="language-{fence.group(1)}"' if fence.group(1) else ""
            out.append(f"<pre><code{lang}>{_e(chr(10).join(code))}\n</code></pre>")
            continue
        heading = re.match(r"(#{1,4})\s+(.*?)\s*#*$", line)
        if heading:
            level = max(2, len(heading.group(1)))  # le h1 est celui de l'en-tête
            body = inline(heading.group(2))
            anchor = f' id="{slugify(body)}"' if level == 2 else ""
            out.append(f"<h{level}{anchor}>{body}</h{level}>")
            i += 1
            continue
        if re.match(r"(-{3,}|\*{3,})\s*$", line):
            out.append("<hr>")
            i += 1
            continue
        if line.startswith(">"):
            quote: list[str] = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            note = re.match(r"\[!NOTE\]\s*(.*)", quote[0])
            if note:
                rest = markdown("\n".join(quote[1:]))
                out.append(
                    '<aside class="note"><p class="note-title">'
                    f"{inline(note.group(1) or 'Note')}</p><div>{rest}</div></aside>"
                )
            else:
                paragraphs = [p for p in "\n".join(quote).split("\n\n") if p.strip()]
                cite = ""
                if len(paragraphs) > 1 and paragraphs[-1].startswith("—"):
                    cite = f"<footer>{inline(paragraphs.pop()[1:].strip())}</footer>"
                text = "".join(f"<p>{inline(' '.join(p.split()))}</p>" for p in paragraphs)
                out.append(f"<blockquote>{text}{cite}</blockquote>")
            continue
        if re.match(r"\s*([-*]|\d+\.)\s+", line):
            ordered = bool(re.match(r"\s*\d+\.", line))
            marker = r"\s*\d+\.\s+" if ordered else r"\s*[-*]\s+"
            items: list[str] = []
            while i < len(lines) and lines[i].strip():
                if re.match(marker, lines[i]):
                    items.append(re.sub(marker, "", lines[i], count=1))
                elif re.match(r"\s*([-*]|\d+\.)\s+", lines[i]):
                    break
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(
                f"<{tag}>" + "".join(f"<li>{inline(item)}</li>" for item in items) + f"</{tag}>"
            )
            continue
        if "|" in line and i + 1 < len(lines) and re.match(r"\s*\|?\s*:?-{3,}", lines[i + 1]):
            head = _cells(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1
            out.append(
                "<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in rows)
                + "</tbody></table>"
            )  # fmt: skip
            continue
        if line.lstrip().startswith("<"):  # du HTML brut, tel quel
            block: list[str] = []
            while i < len(lines) and lines[i].strip():
                block.append(lines[i])
                i += 1
            out.append("\n".join(block))
            continue
        paragraph: list[str] = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not re.match(r"(```|#{1,4}\s|>|\s*([-*]|\d+\.)\s+)", lines[i])
        ):
            paragraph.append(lines[i].strip())
            i += 1
        text = " ".join(paragraph)
        figure = re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)", text)
        if figure:  # une image seule est une figure large, sa légende est son titre
            caption = (
                f"<figcaption>{inline(figure.group(3))}</figcaption>" if figure.group(3) else ""
            )
            out.append(
                f'<figure class="wide"><div><img src="{_e(asset_url(safe_url(figure.group(2))))}" alt="{_e(figure.group(1))}" loading="lazy"></div>{caption}</figure>'
            )
        else:
            out.append(f"<p>{inline(text)}</p>")
    return "\n".join(out)


# -- les pages ------------------------------------------------------------------------


def _asset(path: str) -> str:
    return path if path.startswith("http") else f"{SITE}/{path}"


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")


ORG = {"@type": "Organization", "name": "Hermez", "url": "https://hermez.dev"}


def _head(
    *,
    lang: str,
    title: str,
    description: str,
    path: str,
    alternates: dict[str, str],
    og_type: str,
    image: str,
    image_alt: str,
    json_ld: list[dict[str, object]],
    extra: str = "",
) -> str:
    url = f"{SITE}/{path}"
    tags = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(title)}</title>",
        f'<meta name="description" content="{_e(description)}">',
        f'<link rel="canonical" href="{url}">',
    ]
    for code, target in alternates.items():
        tags.append(f'<link rel="alternate" hreflang="{code}" href="{SITE}/{target}">')
    tags += [
        f'<link rel="alternate" type="application/atom+xml" title="{_e(WORDS[lang]["feed"])}" '
        f'href="{SITE}/{_prefix(lang)}blog/feed.xml">',
        '<link rel="icon" type="image/svg+xml" href="/mascot/favicon.svg?v=ecran">',
        '<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48">',
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
        f'<meta property="og:type" content="{og_type}">',
        '<meta property="og:site_name" content="Ponos">',
        f'<meta property="og:title" content="{_e(title)}">',
        f'<meta property="og:description" content="{_e(description)}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:locale" content="{lang}">',
        f'<meta property="og:image" content="{_e(image)}">',
        f'<meta property="og:image:alt" content="{_e(image_alt)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{_e(title)}">',
        f'<meta name="twitter:description" content="{_e(description)}">',
        f'<meta name="twitter:image" content="{_e(image)}">',
        f'<meta name="twitter:image:alt" content="{_e(image_alt)}">',
    ]
    if extra:
        tags.append(extra)
    for data in json_ld:
        tags.append(
            f'<script type="application/ld+json">\n{_json({"@context": "https://schema.org", **data})}\n</script>'
        )
    tags += [
        "<script>",
        "  /* Avant le premier rendu, comme la page d'accueil : le choix du visiteur, sinon le système. */",
        '  try { var kept = localStorage.getItem("ponos-theme");',
        '    var dark = kept ? kept === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;',
        '    document.documentElement.classList.toggle("dark", dark); } catch (error) {}',
        "</script>",
        '<link rel="stylesheet" href="/tokens.css">',
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        '<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600&display=swap" rel="stylesheet">',
        '<link rel="stylesheet" href="/blog/blog.css">',
        '<script src="https://umami.cardona.digital/nx.js" defer data-website-id="a3af4ed4-63b2-4732-93a2-a43d156910ec" data-domains="the-ponos.app"></script>',
    ]
    return "\n".join(tags)


def _chrome(lang: str, switch_href: str, content: str) -> str:
    w = WORDS[lang]
    home = f"/{_prefix(lang)}"
    doc, repo, changelog = OTHER_LINKS[lang]
    toggle = (
        '<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2m-7.07-2.93 '
        '1.41-1.41m11.32-11.32 1.41-1.41M2 12h2m16 0h2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41"/></svg>'
        '<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>'
    )
    return f"""<body>
<header class="nav">
  <div class="wrap nav-in">
    <a class="brand" href="{home}" aria-label="Ponos, {"home" if lang == "en" else "accueil"}">
      <img src="/mascot/favicon.svg?v=ecran" alt="" width="28" height="28">
      Ponos
    </a>
    <nav class="nav-links" aria-label="Site">
      <a class="btn btn-ghost btn-sm" href="{home}blog/" aria-current="page">{w["blog"]}</a>
      <a class="btn btn-outline btn-sm" href="{DOCS_URL}">{w["docs"]}</a>
      <a class="btn btn-ghost btn-sm lang-switch" href="{switch_href}" hreflang="{"fr" if lang == "en" else "en"}" lang="{"fr" if lang == "en" else "en"}" aria-label="{_e(w["switch_label"])}">{w["switch"]}</a>
      <button class="btn btn-ghost btn-icon theme-toggle" id="theme-toggle" type="button" aria-label="{_e(w["toggle"])}">{toggle}</button>
    </nav>
  </div>
</header>

<main>
{content}
</main>

<footer>
  <div class="wrap foot">
    <div>{w["licence"]} · © 2026 <a href="https://hermez.dev" target="_blank" rel="noopener">{w["signature"]}</a></div>
    <nav aria-label="Elsewhere">
      <a href="{home}blog/">{w["blog"]}</a>
      <a href="{DOCS_URL}">{doc}</a>
      <a href="https://github.com/hermez-agency/ponos">{repo}</a>
      <a href="https://github.com/hermez-agency/ponos/blob/main/CHANGELOG.md">{changelog}</a>
      <a href="/{_prefix(lang)}blog/feed.xml">{w["feed"]}</a>
      <a href="/llms.txt">llms.txt</a>
      <a href="{home_other(lang)}" hreflang="{"fr" if lang == "en" else "en"}" lang="{"fr" if lang == "en" else "en"}">{"Français" if lang == "en" else "English"}</a>
    </nav>
  </div>
</footer>

<script>
  document.getElementById('theme-toggle').addEventListener('click', function () {{
    var dark = document.documentElement.classList.toggle('dark');
    try {{ localStorage.setItem('ponos-theme', dark ? 'dark' : 'light'); }} catch (error) {{}}
  }});
</script>
</body>"""


def home_other(lang: str) -> str:
    return "/fr/" if lang == "en" else "/"


def _card(a: Article) -> str:
    w = WORDS[a.lang]
    image = f"/{a.cover or DEFAULT_COVER}"
    return (
        f'<a class="card" href="/{a.path}">\n'
        f'  <img src="{_e(image)}" alt="" loading="lazy" width="1200" height="630">\n'
        f'  <div class="card-body">\n'
        f'    <p class="card-product">Ponos</p>\n'
        f'    <p class="card-title">{_e(a.title)}</p>\n'
        f'    <p class="card-meta"><time datetime="{a.published}">{format_date(a.published, a.lang)}</time>'
        f" · {a.minutes} {w['min']}</p>\n"
        f"  </div>\n</a>"
    )


def article_page(a: Article, all_articles: dict[str, list[Article]]) -> str:
    w = WORDS[a.lang]
    other_lang = "fr" if a.lang == "en" else "en"
    twin = (
        next((t for t in all_articles[other_lang] if t.slug == a.translation), None)
        if a.translation
        else None
    )
    # Une traduction se déclare d'un côté ou de l'autre ; l'autre l'hérite.
    if twin is None:
        twin = next((t for t in all_articles[other_lang] if t.translation == a.slug), None)
    alternates: dict[str, str] = {}
    if twin:
        for article in (a, twin):
            alternates[article.lang] = article.path
        alternates["x-default"] = (a if a.lang == "en" else twin).path
    image = _asset(a.cover or DEFAULT_COVER)
    image_alt = a.cover_alt or a.title
    home = f"{SITE}/{_prefix(a.lang)}"
    posting: dict[str, object] = {
        "@type": "BlogPosting",
        "mainEntityOfPage": {"@type": "WebPage", "@id": a.url},
        "headline": a.title,
        "description": a.description,
        "image": [image],
        "datePublished": a.published,
        "dateModified": a.updated or a.published,
        "inLanguage": a.lang,
        "author": ORG,
        "publisher": {
            **ORG,
            "logo": {"@type": "ImageObject", "url": f"{SITE}/apple-touch-icon.png"},
        },
        "keywords": ", ".join(a.tags),
        "url": a.url,
    }
    crumbs: dict[str, object] = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Ponos", "item": home},
            {"@type": "ListItem", "position": 2, "name": w["blog"], "item": f"{home}blog/"},
            {"@type": "ListItem", "position": 3, "name": a.title, "item": a.url},
        ],
    }
    extra = f'<meta property="article:published_time" content="{a.published}">\n'
    if a.updated:
        extra += f'<meta property="article:modified_time" content="{a.updated}">\n'
    extra += "\n".join(f'<meta property="article:tag" content="{_e(t)}">' for t in a.tags)
    head = _head(
        lang=a.lang, title=f"{a.title} — Ponos", description=a.description, path=a.path,
        alternates=alternates, og_type="article", image=image, image_alt=image_alt,
        json_ld=[posting, crumbs], extra=extra.strip(),
    )  # fmt: skip
    cover = ""
    if a.cover:
        cover = (
            f'<figure class="wide"><div><img src="/{_e(a.cover)}" alt="{_e(image_alt)}" width="1200" height="630">'
            "</div></figure>\n"
        )
    tags = "".join(f"<span>{_e(t)}</span>" for t in a.tags)
    category = (
        f'<span aria-hidden="true">·</span><span>{_e(a.category)}</span>' if a.category else ""
    )
    updated = ""
    if a.updated and a.updated != a.published:
        label = "Updated" if a.lang == "en" else "Mis à jour le"
        updated = f'<span aria-hidden="true">·</span><span>{label} <time datetime="{a.updated}">{format_date(a.updated, a.lang)}</time></span>'
    more = [x for x in all_articles[a.lang] if x.slug != a.slug][:3]
    cards = ""
    if more:
        cards = (
            f'<section class="wrap more" aria-labelledby="more"><h2 id="more">{w["read_also"]}</h2>'
            f'<div class="cards">{"".join(_card(x) for x in more)}</div></section>'
        )
    body = f"""<div class="crumbs wrap"><a href="/{_prefix(a.lang)}blog/">← {w["blog"]}</a></div>
<article class="prose">
<header>
  <p class="product"><img src="/mascot/favicon.svg?v=ecran" alt="" width="20" height="20"><span>Ponos</span>{category}</p>
  <h1>{_e(a.title)}</h1>
  <p class="lead">{_e(a.description)}</p>
  <p class="byline"><span class="by">Hermez</span><span aria-hidden="true">·</span><time datetime="{a.published}">{format_date(a.published, a.lang)}</time>{updated}<span aria-hidden="true">·</span><span>{a.minutes} {w["minutes"]}</span></p>
</header>
{cover}{markdown(a.body)}
<footer class="article-foot">{tags}<span class="signature">{w["signature"]}</span></footer>
</article>
{cards}"""
    switch = f"/{twin.path}" if twin else f"/{_prefix(other_lang)}blog/"
    return f'<!doctype html>\n<html lang="{a.lang}">\n<head>\n{head}\n</head>\n{_chrome(a.lang, switch, body)}\n'


def index_page(lang: str, all_articles: dict[str, list[Article]]) -> str:
    w = WORDS[lang]
    articles = all_articles[lang]
    path = f"{_prefix(lang)}blog/"
    home = f"{SITE}/{_prefix(lang)}"
    blog: dict[str, object] = {
        "@type": "Blog",
        "name": w["index_title"],
        "description": w["index_description"],
        "url": f"{SITE}/{path}",
        "inLanguage": lang,
        "publisher": ORG,
        "blogPost": [
            {
                "@type": "BlogPosting",
                "headline": a.title,
                "url": a.url,
                "datePublished": a.published,
            }
            for a in articles
        ],
    }
    crumbs: dict[str, object] = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Ponos", "item": home},
            {"@type": "ListItem", "position": 2, "name": w["blog"], "item": f"{SITE}/{path}"},
        ],
    }
    image = f"{SITE}/{DEFAULT_COVER}"
    head = _head(
        lang=lang, title=w["index_title"], description=w["index_description"], path=path,
        alternates={"en": "blog/", "fr": "fr/blog/", "x-default": "blog/"}, og_type="website",
        image=image, image_alt="Ponos", json_ld=[blog, crumbs],
    )  # fmt: skip
    cards = "".join(_card(a) for a in articles) or f"<p>{w['empty']}</p>"
    body = f"""<div class="wrap blog-head">
  <h1>{w["blog"]}</h1>
  <p class="lead">{_e(w["tagline"])}</p>
</div>
<section class="wrap" aria-label="{w["section_of"]}"><div class="cards">{cards}</div></section>"""
    switch = f"/{_prefix('fr' if lang == 'en' else 'en')}blog/"
    return f'<!doctype html>\n<html lang="{lang}">\n<head>\n{head}\n</head>\n{_chrome(lang, switch, body)}\n'


def feed(lang: str, articles: list[Article]) -> str:
    w = WORDS[lang]
    base = f"{SITE}/{_prefix(lang)}blog/"
    updated = max((a.updated or a.published for a in articles), default="2026-01-01")
    entries = []
    for a in articles:
        entries.append(
            f"""  <entry>
    <title>{_e(a.title)}</title>
    <link href="{a.url}"/>
    <id>{a.url}</id>
    <published>{a.published}T00:00:00Z</published>
    <updated>{a.updated or a.published}T00:00:00Z</updated>
    <author><name>Hermez</name><uri>https://hermez.dev</uri></author>
    <summary>{_e(a.description)}</summary>
{"".join(f'    <category term="{_e(t)}"/>' + chr(10) for t in a.tags)}  </entry>"""
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="{lang}">
  <title>{_e(w["index_title"])}</title>
  <subtitle>{_e(w["tagline"])}</subtitle>
  <link href="{base}feed.xml" rel="self"/>
  <link href="{base}"/>
  <id>{base}</id>
  <updated>{updated}T00:00:00Z</updated>
  <author><name>Hermez</name><uri>https://hermez.dev</uri></author>
{chr(10).join(entries)}
</feed>
"""


def _twin(a: Article, all_articles: dict[str, list[Article]]) -> Article | None:
    other = all_articles["fr" if a.lang == "en" else "en"]
    return next((t for t in other if t.slug == a.translation or t.translation == a.slug), None)


def sitemap(all_articles: dict[str, list[Article]]) -> str:
    def entry(loc: str, alternates: dict[str, str], lastmod: str = "") -> str:
        links = "".join(
            f'\n    <xhtml:link rel="alternate" hreflang="{k}" href="{SITE}/{v}"/>'
            for k, v in alternates.items()
        )
        mod = f"\n    <lastmod>{lastmod}</lastmod>" if lastmod else ""
        return f"  <url>\n    <loc>{SITE}/{loc}</loc>{mod}{links}\n  </url>"

    both = {"en": "", "fr": "fr/", "x-default": ""}
    blog = {"en": "blog/", "fr": "fr/blog/", "x-default": "blog/"}
    entries = [entry("", both), entry("fr/", both), entry("blog/", blog), entry("fr/blog/", blog)]
    for lang in LANGS:
        for a in all_articles[lang]:
            twin = _twin(a, all_articles)
            alternates: dict[str, str] = {}
            if twin:
                alternates = {
                    a.lang: a.path,
                    twin.lang: twin.path,
                    "x-default": (a if a.lang == "en" else twin).path,
                }
            entries.append(entry(a.path, alternates, a.updated or a.published))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )


def llms_block(all_articles: dict[str, list[Article]]) -> str:
    lines = [LLMS_START, "## Blog", ""]
    lines.append(
        f"- [Blog]({SITE}/blog/): articles on running Claude Code on a backlog with Ponos; Atom feed at {SITE}/blog/feed.xml"
    )
    lines.append(
        f"- [Blog en français]({SITE}/fr/blog/): the same blog, in French; Atom feed at {SITE}/fr/blog/feed.xml"
    )
    for lang in LANGS:
        for a in all_articles[lang]:
            lines.append(f"- [{a.title}]({a.url}) ({lang}, {a.published}): {a.description}")
    lines.append(LLMS_END)
    return "\n".join(lines)


def llms(all_articles: dict[str, list[Article]]) -> str:
    text = (DOCS / "llms.txt").read_text(encoding="utf-8")
    block = llms_block(all_articles)
    if LLMS_START in text:
        return re.sub(
            re.escape(LLMS_START) + r".*?" + re.escape(LLMS_END), lambda _: block, text, flags=re.S
        )
    return text.rstrip("\n") + "\n\n" + block + "\n"


def outputs() -> dict[Path, str]:
    articles = load()
    files: dict[Path, str] = {}
    for lang in LANGS:
        folder = DOCS / _prefix(lang) / "blog"
        files[folder / "index.html"] = index_page(lang, articles)
        files[folder / "feed.xml"] = feed(lang, articles[lang])
        for a in articles[lang]:
            files[folder / a.slug / "index.html"] = article_page(a, articles)
    files[DOCS / "sitemap.xml"] = sitemap(articles)
    files[DOCS / "llms.txt"] = llms(articles)
    return files


def stale_pages(files: dict[Path, str]) -> list[Path]:
    """Les pages d'article que plus aucun source ne produit (un article retiré)."""
    kept = set(files)
    found: list[Path] = []
    for lang in LANGS:
        folder = DOCS / _prefix(lang) / "blog"
        if folder.is_dir():
            found += [p for p in folder.glob("*/index.html") if p not in kept]
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="ne rien écrire ; échouer si le build commité est périmé",
    )
    args = parser.parse_args()
    files = outputs()
    stale = stale_pages(files)
    behind = [
        p for p, text in files.items() if not p.exists() or p.read_text(encoding="utf-8") != text
    ]
    if args.check:
        if behind or stale:
            for path in [*behind, *stale]:
                print(f"périmé : {path.relative_to(ROOT)}", file=sys.stderr)
            print("python3 scripts/build_blog.py, puis commite le résultat", file=sys.stderr)
            return 1
        return 0
    for path in stale:
        path.unlink()
        path.parent.rmdir()
    for path in behind:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[path], encoding="utf-8")
        print(f"écrit : {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
