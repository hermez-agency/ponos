# Le blog de Ponos

Les articles sont des fichiers Markdown (`blog/content/<lang>/<slug>.md`) ; `python3 scripts/build_blog.py` écrit le site dans `docs/`. Le format d'un article est dans `CONTRIBUTING.md`, « The site's blog ».

## L'illustration d'un article

Chaque article a sa propre illustration, au même style que les autres : vectorielle, plate, géométrique et abstraite, l'orange de Ponos sur fond sombre, sans texte, sans logo, sans personnage. La mascotte reste réservée à l'affiche générale (`docs/mascot/og.png`), qui est aussi l'image de partage de l'accueil et le repli d'un article sans illustration. La version FR et la version EN d'un article partagent la même image.

Pour en ajouter une :

1. Ajoute une entrée à `blog/covers.json`, sous le **slug anglais** de l'article :

   ```json
   "mon-article": {
     "alt": { "en": "Abstract illustration: …", "fr": "Illustration abstraite : …" },
     "prompt": "Ce que l'image montre, en anglais, sans le style",
     "file": ""
   }
   ```

   Le `prompt` dit le sujet de l'article par des formes (un hub relié à des nœuds, une carte qui avance sur une voie…). Le style commun, qui fait tenir les images en série, est ajouté par le script (`STYLE` dans `scripts/blog_covers.py`) : ne le recopie pas.
2. Génère l'image, avec la clé OpenRouter dans l'environnement (jamais dans un fichier du dépôt ; dans Ponos, c'est l'entrée `open_router` du coffre-fort) :

   ```sh
   OPENROUTER_API_KEY=… python3 scripts/blog_covers.py mon-article
   ```

   Le script écrit `docs/blog/covers/mon-article.jpg`, ses déclinaisons AVIF et WebP à 480 et 960 px, et `mon-article-og.jpg` (1200 × 630, l'image de partage), puis remplit `file`. Le modèle est `black-forest-labs/flux.2-flex`, ou `OPENROUTER_IMAGE_MODEL`. `ffmpeg` doit être installé.
3. **Relis l'image** : cohérence avec les autres, aucun texte parasite, rien qui ressemble à un personnage. Si elle rate, change le prompt et relance avec `--force` ; une image ne se commite qu'une fois relue.
4. Écris `alt` en anglais et en français : il décrit ce que l'image montre, pas l'article.
5. `python3 scripts/build_blog.py`, puis commite `blog/covers.json`, `docs/blog/covers/` et les pages écrites.

Le build ne génère rien et n'appelle aucun service : il refuse seulement une illustration déclarée dont un fichier manque (`python3 scripts/blog_covers.py --variants` réécrit les déclinaisons depuis l'image). Un article sans entrée, ou dont `file` est vide, garde l'affiche de la mascotte.
