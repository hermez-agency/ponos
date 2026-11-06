"""« Tentatives » : un ticket essayé deux fois, côte à côte, sous deux tickets frères.

Le modèle « une PR par ticket » est tout ce que le runner sait faire — sa
branche, son worktree, sa session, sa PR, sa fusion — et il n'y touche pas : la
seconde tentative est un *autre ticket*, un clone du premier, qui suit le
chemin ordinaire en entier. Rien n'a été ajouté à la livraison pour qu'elle
sache qu'il y a deux PR ; c'est ce qui fait de ce découpage le plus petit.

Le clone naît au moment où la première tentative est réclamée (pas avant : un
ticket qui ne démarre pas n'en fait pas naître un second), une seule fois — la
case `twin` des deux frères se renvoie l'un à l'autre, et un ticket qui a déjà
un frère n'en refait pas. Le clone vaut une tentative (`attempts = 1`) : il n'en
engendre pas à son tour.

Aucune comparaison ici : les deux PR attendent chacune sa validation. La
fermeture croisée (fusionner l'une ferme l'autre) est le ticket suivant.
"""

from __future__ import annotations

from . import tickets

MAXIMUM = 2


def wanted(attempts: object) -> int:
    """Le nombre de tentatives demandé, ramené à ce que Ponos sait faire : 1 ou 2."""
    try:
        number = int(str(attempts).strip() or 1)
    except ValueError:
        return 1
    return max(1, min(number, MAXIMUM))


def sibling(page: str) -> tickets.Record | None:
    """Le ticket frère, créé à partir de celui-ci s'il en demande deux et n'en a pas encore.

    None quand le ticket n'est pas dans la base, n'a pas demandé de seconde
    tentative, ou a déjà son frère (qui n'est alors pas renvoyé : il existe).
    """
    record = tickets.of_page(page)
    if record is None or record.attempts < 2 or record.twin:
        return None
    twin = tickets.create(
        f"{record.title} (tentative 2)",
        project=record.project,
        role=record.role,
        goal=record.goal,
        kind=record.kind,
        subtype=record.subtype,
        mission=record.mission,
        model=record.model,
        on_change=record.on_change,
        priority=record.priority,
        plan_first=record.plan_first,
        scheduled=record.scheduled,
        status="ready",
        attempts=1,
        twin=record.id,
        after=record.after,
    )
    tickets.update(record.id, twin=twin.id)
    return twin
