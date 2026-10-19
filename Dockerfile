# Ponos in a container — another way to install it, not another program.
#
# The runner is the same Python and the same standard library; what the image
# adds is what install.sh would have found on the machine: git, gh, and Claude
# Code, which is a Node program. The console is not built here: it is committed,
# built, in src/ponos/web/static, so the image needs no npm of its own beyond
# the one Claude Code is installed with.
#
# Everything that has to outlive the container is under four directories, and
# docker-compose.yml gives each a volume: /data (the configuration and the
# state — XDG_CONFIG_HOME and XDG_STATE_HOME), /workspace (the clones of the
# projects), ~/.claude (Claude Code's sign-in and sessions) and ~/.config/gh.
#
# PONOS_CONTAINER tells the runner where it is: no systemd, no auto-update — a
# new version is a new image — and a console that listens to the network behind
# an installation code. See README, "Docker".

FROM node:22-bookworm-slim AS node

FROM python:3.13-slim

ENV PONOS_CONTAINER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    HOME=/home/ponos \
    XDG_CONFIG_HOME=/data/config \
    XDG_STATE_HOME=/data/state \
    CLAUDE_CONFIG_DIR=/home/ponos/.claude \
    DISABLE_AUTOUPDATER=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git openssh-client tini \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends gh \
 && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force

# Not root: Claude Code refuses bypassPermissions to root. And the directories
# the volumes mount on exist, owned by the user, so a fresh named volume starts
# out writable by it.
RUN useradd --create-home --uid 1000 --shell /bin/bash ponos \
 && mkdir -p /data /workspace /home/ponos/.claude /home/ponos/.config/gh \
 && chown -R ponos:ponos /data /workspace /home/ponos

# What the code imports beyond the standard library — nothing yet — into the
# image's own Python: a container is never updated in place, so there is no
# per-version environment to make (see environment.py).
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --require-hashes -r /app/requirements.txt

COPY src /app/src
COPY config.example.toml /app/config.example.toml
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
COPY bin/ponos.in /app/bin/ponos.in
RUN sed -e "s|@APP_DIR@|/app|" -e "s|@PYTHON@|$(command -v python3)|" /app/bin/ponos.in \
      > /usr/local/bin/ponos \
 && chmod 755 /usr/local/bin/ponos /app/docker/entrypoint.sh

USER ponos
WORKDIR /workspace
EXPOSE 8787

# The console answers: /healthz needs no key and says nothing else. A minute of
# grace, for a first start that writes its configuration and draws its token.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8787/healthz || exit 1

ENTRYPOINT ["tini", "-g", "--", "/app/docker/entrypoint.sh"]
