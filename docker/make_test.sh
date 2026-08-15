#!/usr/bin/env bash
# ServiceSentry — local test stack helper. Two stacks (isolated projects/volumes):
#   • test (default) — one worker/syslog/events each (microservices-test.yml)
#   • ha             — 2 replicas of worker/events/syslog to see leader/standby
#                      + failover, on the image CI published (ha-test.yml)
#   • ha-build       — the same stack, built from the working copy instead
#
# Prefix any command with `ha` to target the HA stack:
#   ./docker/make_test.sh            # test: build + start, then follow logs
#   ./docker/make_test.sh ha         # HA:   build + start, then follow logs
#   ./docker/make_test.sh ha up      # same as above
#   ./docker/make_test.sh start      # build + start detached, don't follow logs
#   ./docker/make_test.sh ha logs    # follow the HA stack's logs
#   ./docker/make_test.sh ps         # container status   (add `ha` for the HA stack)
#   ./docker/make_test.sh down       # stop + remove containers
#   ./docker/make_test.sh clean      # + remove volumes (wipes the DB)
#   ./docker/make_test.sh rebuild    # rebuild image + recreate containers
#
# Which published image the `ha` stack runs is one variable — CI publishes `:test` (built
# beside the suite) and `:build` (built without running it):
#   SS_IMAGE_TAG=build ./docker/make_test.sh ha
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# Stack selector: `ha` as the first arg switches to the HA stack. Each compose file
# declares its own `name:` (ss-test / ss-test-ha), so the raw `docker compose`
# commands and this script share the same isolated project — no `-p` needed here.
STACK="test"
case "${1:-}" in
  ha)       STACK="ha";       shift ;;
  ha-build) STACK="ha-build"; shift ;;
esac
# The HA stack is two flavours over ONE definition: `ha` runs the image CI published (so the
# published artefact is what gets exercised, not just the Dockerfile), and `ha-build` adds an
# override that builds from the working copy — which is what you want while changing code,
# since the published `test` tag knows nothing about it.
case "$STACK" in
  ha)       FILES=("docker/docker-compose.ha-test.yml") ;;
  ha-build) FILES=("docker/docker-compose.ha-test.yml"
                   "docker/docker-compose.ha-test-build.yml") ;;
  *)        FILES=("docker/docker-compose.microservices-test.yml") ;;
esac
# `--build` only where something can be built: the published-image stack has no build
# section to act on and wants a fresh pull instead (the published tags move).
if [ "$STACK" = "ha" ]; then UP_FLAGS=(--pull always); else UP_FLAGS=(--build); fi

# Which published tag the `ha` stack runs — exported ONLY when it is actually set, and never
# defaulted here. Compose takes it from three places in this order: the shell, `docker/.env`,
# and the `${SS_IMAGE_TAG:-test}` default in the compose file. The shell WINS, so defaulting
# it here would silently override a `docker/.env` somebody wrote — the exact failure this
# variable exists to prevent.
[ -n "${SS_IMAGE_TAG:-}" ] && export SS_IMAGE_TAG || true

# Prefer Docker Compose v2 (`docker compose`), fall back to v1 (`docker-compose`).
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  echo "ERROR: Docker Compose not found (need 'docker compose' or 'docker-compose')." >&2
  exit 1
fi
for _f in "${FILES[@]}"; do DC+=(-f "$_f"); done

info() {
  cat <<EOF

ServiceSentry ${STACK^^} stack is up.
  Panel   : http://localhost:8080   (login: admin / admin)
  Control : SS_CONTROL_TOKEN=test-control-token (poke enabled between containers)
EOF
  if [ "$STACK" = "ha" ] || [ "$STACK" = "ha-build" ]; then
    cat <<EOF
  HA      : 2 replicas of worker/events/syslog -> Services tab shows Leader/Standby.
            Prove failover: docker kill <worker Leader> -> a standby takes over in ~30s.
EOF
    if [ "$STACK" = "ha" ]; then
      # Asked of Compose rather than rebuilt from the variable: the answer comes from three
      # places with a precedence, and printing our own guess is how a line that exists to say
      # WHICH image came up ends up naming a different one.
      img="$("${DC[@]}" config --images 2>/dev/null | grep servicesentry | head -1 || true)"
      echo "  Image   : ${img:-unknown}   (SS_IMAGE_TAG=build for the one built without the suite)"
    fi
  else
    echo "  Syslog  : UDP/TCP 514, TLS 6514"
  fi
  cat <<EOF

  Logs    : ./docker/make_test.sh ${STACK/test/} logs
  Status  : ./docker/make_test.sh ${STACK/test/} ps
  Stop    : ./docker/make_test.sh ${STACK/test/} down
  Wipe    : ./docker/make_test.sh ${STACK/test/} clean   (also removes the DB volume)
EOF
}

usage="Usage: $0 [ha|ha-build] [up|start|logs|ps|down|clean|rebuild]"

case "${1:-up}" in
  up)
    # Build + start detached, then follow logs FROM THE START (so you don't miss
    # the build/startup output). Ctrl+C only detaches the logs; the stack stays up.
    "${DC[@]}" up "${UP_FLAGS[@]}" -d
    info
    echo "── Following logs (Ctrl+C detaches; the stack keeps running) ──────────"
    "${DC[@]}" logs -f
    ;;
  start)   "${DC[@]}" up "${UP_FLAGS[@]}" -d && info ;;
  logs)
    if [ -z "$("${DC[@]}" ps -aq)" ]; then
      echo "No containers for the '$STACK' stack yet. Start it first:" >&2
      echo "  ./docker/make_test.sh ${STACK/test/} up" >&2
      exit 0
    fi
    "${DC[@]}" logs -f ;;
  ps)      "${DC[@]}" ps -a ;;
  down)    "${DC[@]}" down ;;
  clean)   "${DC[@]}" down -v --remove-orphans ;;
  rebuild) "${DC[@]}" up "${UP_FLAGS[@]}" -d --force-recreate && info ;;
  *) echo "$usage" >&2; exit 1 ;;
esac
