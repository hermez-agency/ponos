#!/bin/sh
# Install Ponos.
#
#   curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ponos/main/install.sh | sh
#
# Environment variables:
#   TR_REPO       source repository        (default: SalvadorCardona/ponos)
#   TR_REF        branch or tag            (default: main; a tag pins the version,
#                                          a branch is followed by the auto-update)
#   TR_SRC        local folder to copy     (install from a clone, no network,
#                                          and no auto-update: there is no remote)
#   TR_INTERVAL   seconds between runs     (default: 1800, i.e. 30 min)
#   TR_NO_SERVICE=1   do not install the systemd units (timer nor console)
#   TR_NO_WEB=1       install the console's unit, but leave it stopped
set -eu

TR_REPO="${TR_REPO:-SalvadorCardona/ponos}"
TR_REF="${TR_REF:-main}"
TR_INTERVAL="${TR_INTERVAL:-1800}"

APP_ROOT="$HOME/.local/share/ponos"
# A link to the version in use, app-<commit> beside it — see update.py.
APP_DIR="$APP_ROOT/app"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/ponos"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ponos"
CONFIG="$CONFIG_DIR/config.toml"
UNIT_DIR="$HOME/.config/systemd/user"

BOLD=""; DIM=""; GREEN=""; YELLOW=""; RESET=""
if [ -t 1 ]; then
    BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); GREEN=$(printf '\033[32m')
    YELLOW=$(printf '\033[33m'); RESET=$(printf '\033[0m')
fi

say()  { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$1"; }
ok()   { printf '    %s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '    %s!%s %s\n' "$YELLOW" "$RESET" "$1"; }
die()  { printf '%serror:%s %s\n' "$BOLD" "$RESET" "$1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- 1. dependencies --------------------------------------------------------
say "Checking dependencies"
have python3 || die "python3 is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "python3 >= 3.11 is required (tomllib has been part of the standard library since then)"
ok "python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

have git || die "git is required"
ok "git found"

if have claude; then
    ok "claude $(claude --version 2>/dev/null | head -1)"
else
    warn "claude missing — install Claude Code, or no ticket can ever be handled"
fi

if have gh; then
    if gh auth status >/dev/null 2>&1; then
        ok "gh authenticated"
    else
        warn "gh found but not authenticated: gh auth login"
    fi
else
    warn "gh missing — branches will be pushed, but no pull request opened"
fi

# --- 2. sources -------------------------------------------------------------
# Each version in a directory of its own, and `app` moved onto it in one rename:
# a pass the timer starts meanwhile runs on the old version or on the new one,
# never on a mixture of the two. The version replaced is kept, for what still
# runs on it and for going back.
mkdir -p "$APP_ROOT" "$BIN_DIR"
STAGE="$APP_ROOT/app.partial"
rm -rf "$STAGE"
if [ -n "${TR_SRC:-}" ]; then
    say "Copying sources from $TR_SRC"
    have tar || die "tar is required"
    [ -d "$TR_SRC/src/ponos" ] || die "$TR_SRC does not contain src/ponos"
    mkdir -p "$STAGE"
    # `node_modules` is the console's build-time dependency and is measured in
    # hundreds of megabytes; what the console actually serves is already built
    # and committed under src/ponos/web/static.
    tar -C "$TR_SRC" --exclude='.git' --exclude='__pycache__' --exclude='node_modules' \
        -cf - . | tar -C "$STAGE" -xf -
    LABEL="copy-$(date +%s)"
    WHAT="a copy: it will not update itself"
else
    # A clone rather than a tarball: it is what lets the runner answer "am I
    # still on the latest version" with one git fetch, once an hour, and update
    # itself when the answer is no. Shallow, because no run ever reads history.
    say "Cloning $TR_REPO ($TR_REF)"
    GIT_TERMINAL_PROMPT=0 git clone --quiet --depth 1 --branch "$TR_REF" \
        "https://github.com/$TR_REPO.git" "$STAGE" \
        || die "clone failed (private repository, or no such branch?)"
    LABEL="$(git -C "$STAGE" rev-parse --short=12 HEAD)"
    WHAT="$(git -C "$STAGE" rev-parse --short HEAD)"
fi
# The same commit installed again gets a name of its own: the directory in use
# is never written over.
[ -e "$APP_ROOT/app-$LABEL" ] && LABEL="$LABEL-$(date +%s)"
mv "$STAGE" "$APP_ROOT/app-$LABEL"
PREVIOUS=""
if [ -L "$APP_DIR" ]; then
    PREVIOUS="$(readlink "$APP_DIR")"
elif [ -e "$APP_DIR" ]; then
    # Installed before versions had directories: that one becomes the previous.
    PREVIOUS="app-before-$(date +%s)"
    mv "$APP_DIR" "$APP_ROOT/$PREVIOUS"
fi
rm -f "$APP_ROOT/.app.link"
ln -s "app-$LABEL" "$APP_ROOT/.app.link"
# `mv` onto a link to a directory would move into it; a rename replaces it.
python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$APP_ROOT/.app.link" "$APP_DIR"
for old in "$APP_ROOT"/app-*; do
    name="${old##*/}"
    [ "$name" = "app-$LABEL" ] || [ "$name" = "${PREVIOUS##*/}" ] || rm -rf "$old"
done
ok "sources in $APP_ROOT/app-$LABEL ($WHAT)"

# --- 3. executable ----------------------------------------------------------
PYTHON="$(command -v python3)"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$APP_DIR/bin/ponos.in" > "$BIN"
chmod +x "$BIN"
ok "command installed: $BIN"

# --- migration filet: an installation from before the rename ---------------
# Ponos was installed as ticket-runner. Its timer and console are stopped and
# their units removed, the variables of their drop-ins renamed, its
# configuration and state moved under the new name (legacy.py says how, and
# that nothing is lost), its old sources removed, and the old command kept as
# a hidden alias that says so and runs ponos. Removed with the filet.
OLD_NAME=ticket-runner
OLD_UNITS="$OLD_NAME.timer $OLD_NAME.service $OLD_NAME-web.service"
if have systemctl && [ -e "$UNIT_DIR/$OLD_NAME.timer" ]; then
    say "Moving the $OLD_NAME installation over to ponos"
    systemctl --user disable --now $OLD_UNITS >/dev/null 2>&1 || true
    for unit in $OLD_UNITS; do
        rm -f "$UNIT_DIR/$unit"
        new_unit=$(printf '%s' "$unit" | sed "s/^$OLD_NAME/ponos/")
        if [ -d "$UNIT_DIR/$unit.d" ] && [ ! -e "$UNIT_DIR/$new_unit.d" ]; then
            mv "$UNIT_DIR/$unit.d" "$UNIT_DIR/$new_unit.d"
            sed -i 's/TICKET_RUNNER_/PONOS_/g' "$UNIT_DIR/$new_unit.d"/*.conf 2>/dev/null || true
        fi
    done
    systemctl --user daemon-reload || true
    ok "$OLD_NAME units removed"
fi
PYTHONPATH="$APP_DIR/src" "$PYTHON" -c 'from ponos import legacy; legacy.directories(print)' \
    | sed 's/^ponos: /    /'
if [ -d "$HOME/.local/share/$OLD_NAME" ]; then
    rm -rf "$HOME/.local/share/$OLD_NAME"
    rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/$OLD_NAME-url-handler.desktop"
    sed -e "s|@BIN@|$BIN|g" "$APP_DIR/bin/former-name.in" > "$BIN_DIR/$OLD_NAME"
    chmod +x "$BIN_DIR/$OLD_NAME"
    ok "old sources removed, $OLD_NAME kept as an alias of ponos"
fi
mkdir -p "$CONFIG_DIR"

# --- 4. configuration -------------------------------------------------------
if [ -f "$CONFIG" ]; then
    ok "existing configuration kept: $CONFIG"
else
    cp "$APP_DIR/config.example.toml" "$CONFIG"
    chmod 600 "$CONFIG"
    ok "configuration created: $CONFIG"

    # The token and the database are the only two things this script cannot
    # work out on its own — so ask, while a terminal is still there to answer.
    if (exec 3</dev/tty) 2>/dev/null; then
        printf '\n    %sNotion integration token%s (https://www.notion.so/my-integrations)\n' "$BOLD" "$RESET"
        printf '    %s(press enter to fill it in later)%s > ' "$DIM" "$RESET"
        read -r token </dev/tty || token=""
        if [ -n "$token" ]; then
            # Into secrets.env, created 0600 beside the configuration: a
            # secret is never written in config.toml.
            PYTHONPATH="$APP_DIR/src" "$PYTHON" - "$CONFIG" "$token" <<'PY'
import sys, pathlib
from ponos import config
path = config.secrets_path(pathlib.Path(sys.argv[1]))
config.write_secrets(path, {config.SECRETS[("notion", "token")]: sys.argv[2].strip()})
PY
            ok "token saved in $(dirname "$CONFIG")/secrets.env"
        fi
        # Nothing needs to exist in Notion yet: give a page shared with the
        # integration and `init` builds the four databases under it.
        printf '    %sURL of a Notion page to build the board under%s\n' "$BOLD" "$RESET"
        printf '    %s(share it with your integration first: the page ... menu -> Connections)%s > ' "$DIM" "$RESET"
        read -r page </dev/tty || page=""
        if [ -n "$page" ] && [ -n "$token" ]; then
            printf '\n'
            "$BIN" init "$page" || warn "run it again once the page is shared: ponos init <url>"
        elif [ -n "$page" ]; then
            warn "no token yet - then: ponos init $page --token ntn_..."
        fi
        printf '\n'
    fi
fi

# The address the console answers on — read from the configuration rather than
# assumed, so a machine that moved the port is told where its own console is.
# The second word says how it is opened: "claimed" when somebody chose a token
# or a sign-in, "open" while its first connection is still waiting for one.
# Read by the runner's own loader: the token and the password are not in the
# file, they are in secrets.env or the environment.
CONSOLE_STATE=$(PYTHONPATH="$APP_DIR/src" "$PYTHON" - "$CONFIG" <<'PY'
import pathlib, sys
from ponos import config
try:
    web = config.load(pathlib.Path(sys.argv[1])).web
except (config.ConfigError, OSError, ValueError):
    web = config.Web()
chosen = web.token or (web.email and web.password)
print("http://%s:%d %s" % (web.host, web.port, "claimed" if chosen else "open"))
PY
)
CONSOLE=${CONSOLE_STATE% *}
CONSOLE_CLAIMED=${CONSOLE_STATE##* }

# --- 5. clickable session links ---------------------------------------------
# Registers ponos:// with the desktop, so the Session cell of a ticket
# opens a terminal already inside that Claude Code session.
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
if [ -d "$APP_DIR/desktop" ]; then
    say "Registering ponos:// links"
    mkdir -p "$DESKTOP_DIR"
    sed -e "s|@BIN@|$BIN|g" \
        "$APP_DIR/desktop/ponos-url-handler.desktop.in" \
        > "$DESKTOP_DIR/ponos-url-handler.desktop"
    have update-desktop-database && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1
    if have xdg-mime; then
        # The second scheme is a migration filet: links written before the
        # rename are still in their Notion cells.
        xdg-mime default ponos-url-handler.desktop x-scheme-handler/ponos x-scheme-handler/ticket-runner \
            >/dev/null 2>&1 && ok "ponos:// links open a terminal on the session" \
            || warn "could not register ponos:// with the desktop"
    fi
fi

# The mascot, cut out on a transparent background, in the sizes a desktop asks
# for: the notifications and the dock both look it up by the name `ponos`.
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
if [ -d "$APP_DIR/src/ponos/icons" ]; then
    for size in 48 64 128 256; do
        mkdir -p "$ICON_DIR/${size}x${size}/apps"
        cp "$APP_DIR/src/ponos/icons/ponos-$size.png" "$ICON_DIR/${size}x${size}/apps/ponos.png"
    done
    have gtk-update-icon-cache && gtk-update-icon-cache -q -t "$ICON_DIR" >/dev/null 2>&1
fi

# --- 6. timer and console ---------------------------------------------------
if [ "${TR_NO_SERVICE:-0}" != "1" ] && have systemctl; then
    # The interval lives in the configuration, so that changing it later is one
    # number and "ponos enable" rather than a reinstall. TR_INTERVAL
    # only seeds it, on a configuration that does not set it yet.
    INTERVAL=$(python3 - "$CONFIG" "$TR_INTERVAL" <<'PY'
import pathlib, re, sys, tomllib
path, seed = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text()
with path.open("rb") as handle:
    current = tomllib.load(handle).get("runner", {}).get("interval_seconds")
if current is None:
    text = re.sub(r"^(\[runner\]\n)", rf"\g<1>interval_seconds = {int(seed)}\n", text, count=1, flags=re.M)
    path.write_text(text)
    current = int(seed)
print(int(current))
PY
)
    say "Installing the timer (one run every ${INTERVAL}s)"
    mkdir -p "$UNIT_DIR"
    ACCURACY=30s
    [ "$INTERVAL" -lt 60 ] && ACCURACY=1s
    # The login PATH is copied into the unit: a systemd service has neither
    # ~/.local/bin nor node in its own, so it would find neither claude nor npm.
    sed -e "s|@BIN@|$BIN|g" -e "s|@PATH@|$PATH|g" \
        "$APP_DIR/systemd/ponos.service.in" > "$UNIT_DIR/ponos.service"
    sed -e "s|@INTERVAL@|$INTERVAL|g" -e "s|@ACCURACY@|$ACCURACY|g" \
        "$APP_DIR/systemd/ponos.timer.in" > "$UNIT_DIR/ponos.timer"
    sed -e "s|@BIN@|$BIN|g" -e "s|@PATH@|$PATH|g" \
        "$APP_DIR/systemd/ponos-web.service.in" > "$UNIT_DIR/ponos-web.service"
    # Written and left off: publishing the MCP endpoint is `ponos tailscale enable`.
    sed -e "s|@BIN@|$BIN|g" -e "s|@PATH@|$PATH|g" \
        "$APP_DIR/systemd/ponos-tailscale.service.in" > "$UNIT_DIR/ponos-tailscale.service"
    systemctl --user daemon-reload
    systemctl --user enable --now ponos.timer >/dev/null 2>&1 \
        && ok "ponos.timer enabled" \
        || warn "enable it by hand: systemctl --user enable --now ponos.timer"
    # The console starts with the rest. What it opens is loopback — behind that
    # port sits a runner that starts Claude Code sessions with bypassPermissions,
    # so it is reachable from this machine and from nowhere else, and widening
    # `web.host` remains the decision it always was. A board you have to remember
    # to start by hand is a board you end up not looking at; TR_NO_WEB=1 keeps
    # the unit installed and stopped.
    if [ "${TR_NO_WEB:-0}" != "1" ]; then
        if systemctl --user enable --now ponos-web.service >/dev/null 2>&1; then
            CONSOLE_UP=1
            ok "ponos-web.service enabled — $CONSOLE"
        else
            warn "start it by hand: systemctl --user enable --now ponos-web"
        fi
    fi
    # Without lingering, the timer stops when the session closes.
    if have loginctl && [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
        warn "to keep it running with no session open: sudo loginctl enable-linger $USER"
    fi
else
    warn "no unit installed — run passes with “ponos run”, the console with “ponos serve”"
fi

# --- 7. summary -------------------------------------------------------------
printf '\n%sinstallation complete.%s\n\n' "$BOLD" "$RESET"
printf '  Build the Notion board (skip if you just did):\n\n    %sponos init <page-url>%s\n\n' "$BOLD" "$RESET"
printf '  Check everything is in place:\n\n    %sponos doctor%s\n\n' "$BOLD" "$RESET"
printf '  %sconfiguration%s  %s\n' "$DIM" "$RESET" "$CONFIG"
printf '  %sready tickets%s  ponos list\n' "$DIM" "$RESET"
printf '  %sone run%s        ponos run\n' "$DIM" "$RESET"
printf '  %sfollow along%s   ponos logs -f\n' "$DIM" "$RESET"
# The console is up, so what is worth printing is the address that opens it.
# Which address depends on what it is waiting for: a console nobody has claimed
# opens on its first connection, and the token would only skip the page that
# asks for the password. Otherwise the token is printed with it, since the one
# drawn on first start is otherwise readable only from a state file nobody would
# think to look in.
TOKEN=""
if [ "${CONSOLE_UP:-0}" = "1" ] && [ "$CONSOLE_CLAIMED" = "claimed" ]; then
    TOKEN=$("$BIN" serve --print-token 2>/dev/null || true)
fi
if [ "${CONSOLE_UP:-0}" = "1" ] && [ "$CONSOLE_CLAIMED" = "open" ]; then
    printf '  %sweb console%s    %s   %s(set your password there — nothing to paste)%s\n' \
        "$DIM" "$RESET" "$CONSOLE" "$DIM" "$RESET"
elif [ -n "$TOKEN" ]; then
    printf '  %sweb console%s    %s/?token=%s\n' "$DIM" "$RESET" "$CONSOLE" "$TOKEN"
else
    printf '  %sweb console%s    ponos serve   %s(board, CLI and chat, on %s)%s\n' "$DIM" "$RESET" "$DIM" "$CONSOLE" "$RESET"
fi
printf '  %stold on Telegram%s  ponos notify --pair   %s(and answer with one word)%s\n' "$DIM" "$RESET" "$DIM" "$RESET"
printf '  %sversion%s        kept up to date on its own — ponos update\n\n' "$DIM" "$RESET"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) printf '  %s!%s add %s to your PATH: echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> ~/.bashrc\n\n' "$YELLOW" "$RESET" "$BIN_DIR" ;;
esac
