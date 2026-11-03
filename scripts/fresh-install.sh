#!/bin/sh
# Install Ponos on a bare machine, the way a stranger does, and check what they get.
#
#   docker run --rm -v "$PWD:/repo:ro" ubuntu:24.04 sh /repo/scripts/fresh-install.sh
#
# The CI's job `fresh-install` (.github/workflows/install.yml) runs exactly
# that. The two suites test the runner from a checkout, and the image installs
# it its own way: neither has ever run install.sh as it is published — piped
# into sh, by somebody who is not root, on an Ubuntu with no systemd session
# and no python3-venv, with nothing but curl, git and python3. Ten minutes of
# such a container found a fresh installation offered to go back from main to
# the last release, its workspace folder missing, its state files readable by
# all and `ponos doctor` red: none of which a test from a checkout can see.
#
# /repo is a clone of this repository, with its history and its tags (the
# CI's checkout has `fetch-depth: 0`). Its commit becomes `main` of a bare
# repository, and git is told that github.com/hermez-agency/ponos is that
# repository: install.sh then makes its real `git clone --depth 1`, and
# `ponos update --check` its real fetch of the tags — of the commit under
# test, and without the network. The network is still asked for one thing:
# the packages of the version's environment, from PyPI, as on any machine.
#
# Run as root, it prepares the machine and runs itself again as `ponos`, an
# ordinary user; that second half is the installation and its four checks:
#   1. install.sh, with no answer to give and no browser to open;
#   2. the console answers GET /api/setup, and nobody has claimed it yet;
#   3. `ponos doctor` says no problem but those a fresh installation has by
#      construction: Claude Code is not installed here, and the board's
#      Notion token is the console's first connection;
#   4. `ponos update --check` answers, and never offers an older version than
#      the one installed.
# Each check says what it found and the next one still runs: one run of the
# job shows every defect at once, and fails at the end if there was one.
set -eu

SOURCE=/srv/ponos.git
REPOSITORY=https://github.com/hermez-agency/ponos.git
# What doctor may still count as a problem here: the codes of `health/`,
# matched on their first part — the group of the check.
ACCEPTED="claude notion"

say()  { printf '\n==> %s\n' "$1"; }
fail() { printf '\nfresh install: %s\n' "$1" >&2; exit 1; }
FAILED=0
wrong() { printf '\n✗ %s\n' "$1" >&2; FAILED=$((FAILED + 1)); }

if [ "$(id -u)" = 0 ]; then
    say "A bare Ubuntu: curl, git and python3, nothing else"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl git python3 >/dev/null
    python3 --version

    say "The commit under test, as github.com/hermez-agency/ponos"
    # /repo belongs to whoever ran docker, not to root: git refuses to read
    # a repository of somebody else's unless told to.
    git config --system --add safe.directory '*'
    commit=$(git -C /repo rev-parse HEAD)
    git clone --quiet --bare --no-local /repo "$SOURCE"
    git -C "$SOURCE" update-ref refs/heads/main "$commit"
    git -C "$SOURCE" symbolic-ref HEAD refs/heads/main
    chmod -R a+rX "$SOURCE"
    git config --system url."file://$SOURCE".insteadOf "$REPOSITORY"
    echo "main = $commit, tags: $(git -C "$SOURCE" tag --list 'v*' | tr '\n' ' ')"

    useradd --create-home --shell /bin/bash ponos
    exec su - ponos -c "PONOS_COMMIT=$commit sh /repo/scripts/fresh-install.sh"
fi

export PATH="$HOME/.local/bin:$PATH"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/ponos"

say "1. install.sh, piped into sh"
# As `curl … | sh` runs it: the script on stdin, no terminal to answer on.
TR_NO_OPEN=1 sh </repo/install.sh
installed=$(git -C "$HOME/.local/share/ponos/app" rev-parse HEAD)
[ "$installed" = "$PONOS_COMMIT" ] || fail "installed $installed rather than $PONOS_COMMIT"

say "2. The console answers on /api/setup"
answer=""
for _ in $(seq 30); do
    answer=$(curl -fsS http://127.0.0.1:8787/api/setup 2>/dev/null) && break
    sleep 1
done
if [ -z "$answer" ]; then
    cat "$STATE/web/serve.log" >&2 || true
    wrong "nothing answers on http://127.0.0.1:8787/api/setup"
else
    echo "$answer"
    printf '%s' "$answer" | python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin)["claimed"] is False else 1)' \
        || wrong "a fresh console is already claimed"
fi

# The console asks for the newest version as it starts, and the first fetch of
# a shallow clone deepens it: a second fetch meanwhile — doctor's, or update's
# — finds shallow.lock and cannot tell. That collision is a defect of its own;
# what is checked here is what each of them answers, so they come after it.
for _ in $(seq 120); do
    [ -s "$STATE/update.json" ] && break
    sleep 1
done

say "3. ponos doctor"
ponos doctor || true
# The same checks doctor makes, read by their code rather than by their
# sentence: the sentences are written for a person, and change.
app=$(cd -P "$HOME/.local/share/ponos/app" && pwd)
python="$app/.venv/bin/python"
[ -x "$python" ] || python=python3
PYTHONPATH="$app/src" "$python" - "$ACCEPTED" <<'PY' || wrong "ponos doctor has problems a fresh installation should not have"
import sys

from ponos import config, health

accepted = set(sys.argv[1].split())
checks = health.run(config.load(), remote=True)
unexpected = [
    check for check in checks if check.state == health.ERROR and check.group not in accepted
]
for check in unexpected:
    print(f"unexpected: {check.code} — {check.text(check.title)}: {check.text(check.said)}")
sys.exit(1 if unexpected else 0)
PY

say "4. ponos update --check"
if ! ponos update --check; then
    wrong "ponos update --check could not tell"
else
    cat "$STATE/update.json"
    echo
    offered=$(python3 -c 'import json, sys; status = json.load(open(sys.argv[1])); print(status["current"], status["latest"])' "$STATE/update.json")
    current=${offered% *}
    latest=${offered#* }
    # An update moves forward or not at all: whatever is offered descends from
    # what is installed, in the full history the bare repository keeps.
    if [ -n "$latest" ] && [ "$latest" != "$current" ] \
        && ! git -C "$SOURCE" merge-base --is-ancestor "$current" "$latest"; then
        wrong "ponos update offers to go back, from $current to $latest"
    fi
fi

[ "$FAILED" = 0 ] || fail "$FAILED check(s) failed — each one is said above"
printf '\nfresh install: everything a stranger gets is in place.\n'
