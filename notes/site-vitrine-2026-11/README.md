# Site vitrine, novembre 2026 — avant / après

Le ticket PON-705 (audit design, constats S1 à S6) : `docs/index.html` et
`docs/fr/index.html` raccourcis d'un tiers. Captures pleine page, en clair et
mouvement réduit (le hero au repos), prises dans Chrome headless : bureau à
1440 px de large (réduites ici à 720), téléphone à 390 px.

| Page      | Bureau 1440 px, avant | après   | Téléphone 390 px, avant | après   |
|-----------|----------------------:|--------:|------------------------:|--------:|
| `/`       | 9 565 px              | 6 191 px (−35 %) | 16 330 px      | 9 731 px (−40 %) |
| `/fr/`    | 9 780 px              | 6 309 px (−35 %) | 16 697 px      | 9 957 px (−40 %) |

- `before-en-desktop.jpg`, `after-en-desktop.jpg`, `before-en-phone.jpg`, `after-en-phone.jpg`
- `before-fr-desktop.jpg`, `after-fr-desktop.jpg`, `before-fr-phone.jpg`, `after-fr-phone.jpg`

Le compte de la preuve (« 663 des 716 pull requests ») a été fait le
23 novembre 2026 : les pull requests du dépôt dont la branche commence par
`ticket/`, celles que le runner ouvre.

```sh
gh pr list --repo hermez-agency/ponos --state all --limit 3000 --json headRefName \
  --jq '[.[] | select(.headRefName | startswith("ticket/"))] | length'
```
