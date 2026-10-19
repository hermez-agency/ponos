#!/bin/sh
# Uninstall ponos.
#   curl -LsSf https://raw.githubusercontent.com/hermez-agency/ponos/main/uninstall.sh | sh
# Add TR_PURGE=1 to remove the configuration, logs and history as well.
set -eu

say() { printf '==> %s\n' "$1"; }

if command -v systemctl >/dev/null 2>&1; then
    say "Stopping the timer and the console"
    systemctl --user disable --now ponos.timer >/dev/null 2>&1 || true
    systemctl --user disable --now ponos-web.service >/dev/null 2>&1 || true
    systemctl --user disable --now ponos-tailscale.service >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/ponos.timer" \
          "$HOME/.config/systemd/user/ponos.service" \
          "$HOME/.config/systemd/user/ponos-web.service" \
          "$HOME/.config/systemd/user/ponos-tailscale.service"
    systemctl --user daemon-reload || true
fi

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/ponos"
if [ -d "$STATE/worktrees" ] && [ -n "$(ls -A "$STATE/worktrees" 2>/dev/null)" ]; then
    say "Worktrees left in $STATE/worktrees"
    printf '    they still belong to their repositories: run "ponos clean --force"\n'
    printf '    before uninstalling, or "git worktree prune" in each repository.\n'
fi

say "Removing files"
rm -f "$HOME/.local/bin/ponos"
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
