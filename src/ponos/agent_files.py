"""Ce qu'un outil d'agent dépose dans un worktree, gardé hors des commits.

Les instructions d'un dépôt sont ce qui rend une session fiable, mais
`CLAUDE.md`, `skills-lock.json` et `.claude/` nomment l'outil dans des dépôts
publics. La convention de Ponos est donc `AGENTS.md`, un nom que la plupart des
agents lisent ; Claude Code, lui, ne lit que `CLAUDE.md`. Plutôt que de
demander au dépôt de garder les deux, Ponos pose dans le worktree un
`CLAUDE.md` d'une ligne, `@AGENTS.md` — l'import de Claude Code —, que rien ne
commite. Un dépôt qui a les deux fichiers garde les siens : le prompt et la
relecture y lisent `AGENTS.md` d'abord.

**`info/exclude`, pas `.gitignore`.** Le `.gitignore` est au projet, et le
modifier ferait un changement de plus dans chaque PR. `info/exclude` est à la
copie locale : git le lit dans le répertoire commun du dépôt, partagé par tous
ses worktrees (il n'y en a pas par worktree), si bien que le bloc posé vaut
aussi pour la copie principale — où il n'ignore que des fichiers d'outil non
suivis, jamais un fichier que le dépôt suit. Il est délimité et réécrit à
l'identique : poser deux fois ne l'écrit qu'une.

**Refuser avant le push, pas réparer.** Une exclusion n'arrête pas un
`git add -f`. Ce qu'une branche ajoute sous ces chemins est donc relu commit
par commit avant le push : un fichier retiré par un commit suivant resterait
lisible dans l'historique poussé. Seul ce que la branche *ajoute* est refusé :
modifier ou retirer un `CLAUDE.md` que le dépôt suit déjà est son affaire — le
ticket de nettoyage qui le renomme en `AGENTS.md` en est un.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from . import git

INSTRUCTIONS = "AGENTS.md"
CLAUDE = "CLAUDE.md"
# Le CLAUDE.md que Ponos pose : l'import, et rien d'autre à lire.
POINTER = f"@{INSTRUCTIONS}\n"

# Ce que Claude Code (ou ses outils de skills) écrit dans un dépôt, en motifs
# `info/exclude` ancrés à la racine.
EXCLUDED = ("/.claude/", "/skills-lock.json", f"/{CLAUDE}", "/CLAUDE.local.md")

BEGIN = "# >>> ponos: agent files stay out of commits"
END = "# <<< ponos"


def _block() -> str:
    return "\n".join([BEGIN, *EXCLUDED, END]) + "\n"


def exclude_file(worktree: Path) -> Path | None:
    """Le fichier `info/exclude` que git lit pour ce worktree — None hors d'un dépôt."""
    found = git.git(["rev-parse", "--git-path", "info/exclude"], worktree)
    if not found.ok or not found.out:
        return None
    path = Path(found.out)
    return path if path.is_absolute() else worktree / path


def exclude(worktree: Path) -> bool:
    """Pose le bloc des exclusions dans `info/exclude` — True quand il a été écrit."""
    path = exclude_file(worktree)
    if path is None:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    kept: list[str] = []
    inside = False
    for line in text.splitlines():
        if line == BEGIN:
            inside = True
        elif line == END and inside:
            inside = False
        elif not inside:
            kept.append(line)
    head = "\n".join(kept).rstrip("\n")
    written = (head + "\n\n" if head else "") + _block()
    if written == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(written, encoding="utf-8")
    return True


def _tracked(worktree: Path, name: str) -> bool:
    return git.git(["ls-files", "--error-unmatch", "--", name], worktree).ok


def point_to_instructions(worktree: Path) -> bool:
    """Un `CLAUDE.md` qui importe `AGENTS.md`, quand le dépôt n'a que ce dernier.

    True quand il est posé. Un `CLAUDE.md` que le dépôt suit n'est jamais
    touché ; un `CLAUDE.md` non suivi est le nôtre d'une pose précédente, ou
    celui qu'une session a laissé : il est refait, et retiré quand `AGENTS.md`
    a disparu.
    """
    pointer = worktree / CLAUDE
    if _tracked(worktree, CLAUDE):
        return False
    if not (worktree / INSTRUCTIONS).is_file():
        if pointer.is_file() and pointer.read_text(encoding="utf-8") == POINTER:
            pointer.unlink()
        return False
    pointer.write_text(POINTER, encoding="utf-8")
    return True


def prepare(worktree: Path) -> bool:
    """Le worktree prêt pour une session : exclusions posées, `AGENTS.md` lu. True : pointeur posé."""
    exclude(worktree)
    return point_to_instructions(worktree)


def is_agent_file(path: str) -> bool:
    """Ce chemin, relatif à la racine du dépôt, est-il un fichier d'outil d'agent ?"""
    path = path.strip().strip('"')
    for pattern in EXCLUDED:
        name = pattern.strip("/")
        if pattern.endswith("/"):
            if path == name or path.startswith(name + "/"):
                return True
        elif fnmatch(path, name):
            return True
    return False


def committed(worktree: Path, base: str) -> list[str]:
    """Les fichiers d'outil qu'un commit de la branche ajoute, depuis sa base — triés, sans doublon."""
    for reference in (f"origin/{base}", base):
        listed = git.git(
            ["log", "--diff-filter=ACR", "--name-only", "--format=", f"{reference}..HEAD"],
            worktree,
        )
        if listed.ok:
            return sorted({line for line in listed.out.splitlines() if is_agent_file(line)})
    return []
