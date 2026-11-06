#!/bin/sh
# What the container does when it starts — the image's install.sh, run each time.
#
# A configuration when the volume has none yet: the example, with the three
# lines a container answers differently — the projects under /workspace, the
# console listening to the network Docker gives it (the installation code
# guards it until somebody claims it, see web/setup.py), and a run every minute,
# since a pass with nothing to do is one request to the board. And a fourth:
# the provider, when the only way to Claude given is an Anthropic key: the
# sessions are billed to it rather than waiting for a sign-in nobody will type.
#
# Then git signed in through gh when a token was given, so a push goes out as
# the account the pull requests are opened as. And then the two halves of a
# runner: the loop of runs the systemd timer would start (`ponos run --every`),
# and the console in the foreground, whose logs are the container's — the
# installation code among them.
#
# Given a command, the container runs that instead: `docker compose run ponos
# ponos doctor`, or the CI's test suite.
set -eu

config="${PONOS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/ponos/config.toml}"
if [ ! -f "$config" ]; then
    mkdir -p "$(dirname "$config")"
    umask 077
    provider=
    [ -n "${ANTHROPIC_API_KEY:-}" ] && [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && provider=api_key
    sed -e 's|^workspace_root = .*|workspace_root = "/workspace"|' \
        -e 's|^host = "127.0.0.1"|host = "0.0.0.0"|' \
        -e 's|^interval_seconds = 1800|interval_seconds = 60|' \
        -e "s|^provider = \"\"|provider = \"$provider\"|" \
        /app/config.example.toml > "$config"
    echo "ponos: configuration created in $config"
fi

if [ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
    gh auth setup-git >/dev/null 2>&1 || echo "ponos: gh auth setup-git failed — pushes may be refused"
fi

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

ponos run --every &
exec ponos service run --host 0.0.0.0
