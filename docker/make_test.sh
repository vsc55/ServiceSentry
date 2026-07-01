#!/usr/bin/env bash
# ServiceSentry — local test stack helper. Two stacks (isolated projects/volumes):
#   • test (default) — one worker/syslog/events each (microservices-test.yml)
#   • ha             — 2 replicas of worker/events/syslog to see leader/standby
#                      + failover (ha-test.yml)
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
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# Stack selector: `ha` as the first arg switches to the HA stack (isolated project
# name so the two stacks don't share volumes/containers).
STACK="test"
if [ "${1:-}" = "ha" ]; then STACK="ha"; shift; fi
if [ "$STACK" = "ha" ]; then
  FILE="docker/docker-compose.ha-test.yml"; PROJECT="ss-ha"
else
  FILE="docker/docker-compose.microservices-test.yml"; PROJECT="ss-test"
fi

# Prefer Docker Compose v2 (`docker compose`), fall back to v1 (`docker-compose`).
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  echo "ERROR: Docker Compose not found (need 'docker compose' or 'docker-compose')." >&2
  exit 1
fi
DC+=(-p "$PROJECT" -f "$FILE")

info() {
  cat <<EOF

ServiceSentry ${STACK^^} stack is up.
  Panel   : http://localhost:8080   (login: admin / admin)
  Control : SS_CONTROL_TOKEN=test-control-token (poke enabled between containers)
EOF
  if [ "$STACK" = "ha" ]; then
    cat <<EOF
  HA      : 2 replicas of worker/events/syslog -> Services tab shows Leader/Standby.
            Prove failover: docker kill <worker Leader> -> a standby takes over in ~30s.
EOF
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

usage="Usage: $0 [ha] [up|start|logs|ps|down|clean|rebuild]"

case "${1:-up}" in
  up)
    # Build + start detached, then follow logs FROM THE START (so you don't miss
    # the build/startup output). Ctrl+C only detaches the logs; the stack stays up.
    "${DC[@]}" up --build -d
    info
    echo "── Following logs (Ctrl+C detaches; the stack keeps running) ──────────"
    "${DC[@]}" logs -f
    ;;
  start)   "${DC[@]}" up --build -d && info ;;
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
  rebuild) "${DC[@]}" up --build -d --force-recreate && info ;;
  *) echo "$usage" >&2; exit 1 ;;
esac
