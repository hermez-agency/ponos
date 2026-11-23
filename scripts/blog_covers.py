#!/usr/bin/env python3
"""Les illustrations des articles du blog : une image par article, générée à la main, une fois.

    python3 scripts/blog_covers.py                 génère ce qui manque (une entrée de blog/covers.json sans fichier)
    python3 scripts/blog_covers.py <slug>          génère l'illustration d'un article, si elle manque
    python3 scripts/blog_covers.py <slug> --force  la régénère
    python3 scripts/blog_covers.py --variants      écrit les déclinaisons de celles qui existent, sans appeler le modèle

La clé est `OPENROUTER_API_KEY`, dans l'environnement : elle ne s'écrit dans aucun
fichier du dépôt. Le modèle est `black-forest-labs/flux.2-flex`, surchargeable par
`OPENROUTER_IMAGE_MODEL`.

Pourquoi à la main plutôt qu'au build : le site est servi tel quel, `build_blog.py`
reste en bibliothèque standard et sans réseau, et une illustration est un choix
qu'on relit (cohérence de la série, pas de texte parasite) avant de la commiter. Ce
script écrit les images dans `docs/blog/covers/` ; `build_blog.py` les lit dans
`blog/covers.json` — une entrée par article, rangée sous le slug de sa version
anglaise, que la version française partage — et refuse un fichier déclaré qui manque.

Les déclinaisons sont celles de `hermez.dev` : AVIF et WebP à 480 et 960 px, que
`<picture>` sert aux cartes et à l'article, et `-og.jpg`, un JPEG 1200 × 630 recadré
pour l'image de partage. `ffmpeg` les écrit : Pillow n'est pas une dépendance du dépôt.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERS = ROOT / "blog" / "covers.json"
OUT = ROOT / "docs" / "blog" / "covers"
ENDPOINT = "https://openrouter.ai/api/v1/images/generations"
MODEL = os.environ.get("OPENROUTER_IMAGE_MODEL", "black-forest-labs/flux.2-flex")

WIDTHS = (480, 960)
FORMATS = ("avif", "webp")
SHARE = (1200, 630)
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

# Le suffixe commun à tous les prompts : c'est lui qui fait tenir les images ensemble
# comme une série. Les couleurs sont celles de la marque (`docs/tokens.css`) : l'orange
# #e46212 sur le fond sombre du thème, quelques neutres chauds. Pas de texte — aucun
# modèle d'image ne l'écrit correctement — ni de personnage : la mascotte est réservée
# à l'affiche générale.
STYLE = (
    "Flat vector editorial illustration, geometric and abstract, bold simple shapes with "
    "thin connecting lines, generous negative space, solid dark warm charcoal background "
    "(#1c1917), a single brand orange (#e46212) for the main shapes, a few warm stone grey "
    "and cream neutrals (#a8a29e, #e7e5e4) as secondary shapes, no gradients, no glow, "
    "no 3D, readable on both light and dark pages, "
    "no text, no letters, no numbers, no logos, no people, no characters, no robot, "
    "wide banner composition."
)


def shared(file: str) -> list[str]:
    stem = Path(file).stem
    return [f"{stem}-{w}.{f}" for w in WIDTHS for f in FORMATS] + [f"{stem}-og.jpg"]


def generate(slug: str, prompt: str, key: str) -> str:
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": f"{prompt}. {STYLE}",
            "resolution": "1K",
            "aspect_ratio": "16:9",
        }
    ).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"OpenRouter {error.code} : {error.read().decode()[:300]}") from None
    image = (payload.get("data") or [{}])[0]
    if not image.get("b64_json"):
        raise SystemExit(f"Réponse sans image : {json.dumps(payload)[:300]}")
    extension = EXTENSIONS.get(image.get("media_type", "image/png"))
    if not extension:
        raise SystemExit(
            f"Le modèle a renvoyé du {image.get('media_type')}, inutilisable en <img> : "
            "OPENROUTER_IMAGE_MODEL en choisit un autre."
        )
    name = f"{slug}.{extension}"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_bytes(base64.b64decode(image["b64_json"]))
    cost = (payload.get("usage") or {}).get("cost")
    print(f"écrit : {(OUT / name).relative_to(ROOT)}" + (f" (${cost:.4f})" if cost else ""))
    return name


def write_variants(file: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg manque : il écrit les déclinaisons (AVIF, WebP, JPEG)")
    source, stem = OUT / file, Path(file).stem
    base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    for width in WIDTHS:
        scale = ["-frames:v", "1", "-vf", f"scale={width}:-2:flags=lanczos"]
        subprocess.run(
            [*base, *scale, "-c:v", "libaom-av1", "-still-picture", "1", "-crf", "34",
             str(OUT / f"{stem}-{width}.avif")],
            check=True,
        )  # fmt: skip
        subprocess.run(
            [*base, *scale, "-c:v", "libwebp", "-quality", "78", str(OUT / f"{stem}-{width}.webp")],
            check=True,
        )  # fmt: skip
    # Recadrée au centre : un 16:9 perd un peu en haut et en bas pour tenir en 1,91:1.
    w, h = SHARE
    crop = f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}"
    subprocess.run(
        [*base, "-frames:v", "1", "-vf", crop, "-q:v", "3", str(OUT / f"{stem}-og.jpg")],
        check=True,
    )  # fmt: skip
    print(f"déclinaisons de {file} : {', '.join(shared(file))}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("slugs", nargs="*", help="les articles (le slug anglais) ; tous par défaut")
    parser.add_argument("--force", action="store_true", help="régénérer même si l'image existe")
    parser.add_argument("--variants", action="store_true", help="ne refaire que les déclinaisons")
    args = parser.parse_args()
    covers: dict[str, dict[str, object]] = json.loads(COVERS.read_text(encoding="utf-8"))
    unknown = [s for s in args.slugs if s not in covers]
    if unknown:
        print(f"absent de blog/covers.json : {', '.join(unknown)}", file=sys.stderr)
        return 1
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key and not args.variants:
        print("OPENROUTER_API_KEY manque dans l'environnement", file=sys.stderr)
        return 1
    done = 0
    for slug in args.slugs or list(covers):
        entry = covers[slug]
        file = str(entry.get("file") or "")
        present = bool(file) and (OUT / file).exists()
        if args.variants:
            if present:
                write_variants(file)
                done += 1
            continue
        if present and not args.force:
            print(f"{slug} : déjà là (--force pour la refaire)")
            continue
        entry["file"] = file = generate(slug, str(entry["prompt"]), key)
        write_variants(file)
        COVERS.write_text(json.dumps(covers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        done += 1
    print(f"{done} illustration(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
