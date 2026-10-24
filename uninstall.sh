#!/bin/sh
# Uninstall ponos.
#   curl -LsSf https://raw.githubusercontent.com/hermez-agency/ponos/main/uninstall.sh | sh
# Add TR_PURGE=1 to remove the configuration, logs and history as well.
set -eu

say() { printf '==> %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

BIN="$HOME/.local/bin/ponos"
UNIT_DIR="$HOME/.config/systemd/user"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/ponos"

# The Tailscale doors outlive every unit: tailscaled keeps the serve and Funnel
# configuration until it is told otherwise, and only the binary knows which
# ones are ours — so it is asked first, while it is still there.
if [ -x "$BIN" ] && have tailscale; then
    say "Taking down the Tailscale doors"
    "$BIN" tailscale disable >/dev/null 2>&1 || true
fi

if have systemctl; then
    say "Stopping the timer and the console"
    systemctl --user disable --now ponos.timer >/dev/null 2>&1 || true
    systemctl --user stop ponos.service >/dev/null 2>&1 || true
    systemctl --user disable --now ponos-web.service >/dev/null 2>&1 || true
    systemctl --user disable --now ponos-tailscale.service >/dev/null 2>&1 || true
fi
# The drop-ins are yours (credentials, an Environment=), but they only ever
# configure units that are going: left behind, they would dress the next
# install's units with whatever they said.
rm -f "$UNIT_DIR/ponos.timer" \
      "$UNIT_DIR/ponos.service" \
      "$UNIT_DIR/ponos-web.service" \
      "$UNIT_DIR/ponos-tailscale.service"
rm -rf "$UNIT_DIR"/ponos*.service.d "$UNIT_DIR"/ponos*.timer.d
have systemctl && { systemctl --user daemon-reload >/dev/null 2>&1 || true; }

# A Mac's launchd agents: unloaded before their plist goes, or launchd keeps
# starting a binary that is no longer there.
AGENTS="$HOME/Library/LaunchAgents"
for label in app.ponos.run app.ponos.web; do
    [ -f "$AGENTS/$label.plist" ] || continue
    say "Unloading $label"
    have launchctl && { launchctl unload -w "$AGENTS/$label.plist" >/dev/null 2>&1 || true; }
    rm -f "$AGENTS/$label.plist"
done

# The console install.sh started with nohup, where neither systemd nor launchd
# keeps it. Its PID is checked against its command line first: after a restart
# the number may well be somebody else's.
PIDFILE="$STATE/web/serve.pid"
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE" 2>/dev/null || true)
    case "$PID" in
        ''|*[!0-9]*) ;;
        *)
            if ps -p "$PID" -o args= 2>/dev/null | grep -q ponos; then
                say "Stopping the console started in the background"
                kill "$PID" 2>/dev/null || true
            fi
            ;;
    esac
    rm -f "$PIDFILE"
fi

# The ponos:// handler, both schemes the installer gave it, and the icons.
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
if [ -f "$DATA/applications/ponos-url-handler.desktop" ]; then
    say "Unregistering ponos:// links"
    rm -f "$DATA/applications/ponos-url-handler.desktop"
    have update-desktop-database && { update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true; }
fi
# xdg-mime can set a default, not remove one: the line is taken out of the
# file it wrote it to.
MIMEAPPS="${XDG_CONFIG_HOME:-$HOME/.config}/mimeapps.list"
if [ -f "$MIMEAPPS" ] && grep -q 'ponos-url-handler\.desktop' "$MIMEAPPS"; then
    sed -e '/^x-scheme-handler\/ponos=/d' -e '/^x-scheme-handler\/ticket-runner=/d' \
        "$MIMEAPPS" > "$MIMEAPPS.ponos" \
        && mv "$MIMEAPPS.ponos" "$MIMEAPPS"
fi
ICONS="$DATA/icons/hicolor"
for size in 48 64 128 256; do
    rm -f "$ICONS/${size}x${size}/apps/ponos.png"
done
have gtk-update-icon-cache && [ -d "$ICONS" ] && { gtk-update-icon-cache -q -t "$ICONS" >/dev/null 2>&1 || true; }

if [ -d "$STATE/worktrees" ] && [ -n "$(ls -A "$STATE/worktrees" 2>/dev/null)" ]; then
    say "Worktrees left in $STATE/worktrees"
    printf '    they still belong to their repositories: run "ponos clean --force"\n'
    printf '    before uninstalling, or "git worktree prune" in each repository.\n'
fi

say "Removing files"
rm -f "$BIN"
# Migration filet: the alias install.sh left for the name before the rename.
rm -f "$HOME/.local/bin/ticket-runner"
rm -rf "$HOME/.local/share/ponos"

if [ "${TR_PURGE:-0}" = "1" ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/ponos" "$STATE"
    say "Configuration, logs and history removed"
else
    say "Configuration and history kept (TR_PURGE=1 to remove them)"
fi

printf '\nPonos is uninstalled.\n'
printf 'Branches already pushed are left untouched.\n'
