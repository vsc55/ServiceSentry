#!/usr/bin/env bash
# ServiceSentry — local microservices TEST stack helper.
# Builds the image from the Dockerfile and runs the split topology
# (web + worker + syslog + events) on a shared MariaDB, no Traefik.
#
#   ./docker/make_test.sh            # build + start (detached)
#   ./docker/make_test.sh logs       # follow logs
#   ./docker/make_test.sh ps         # container status
#   ./docker/make_test.sh down       # stop + remove containers
#   ./docker/make_test.sh clean      # + remove volumes (wipes the test DB)
#   ./docker/make_test.sh rebuild    # rebuild image + recreate containers
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FILE="docker/docker-compose.microservices-test.yml"
cd "$ROOT"

# Prefer Docker Compose v2 (`docker compose`), fall back to v1 (`docker-compose`).
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  echo "ERROR: Docker Compose not found (need 'docker compose' or 'docker-compose')." >&2
  exit 1
fi

info() {
  cat <<EOF

ServiceSentry TEST stack is up.
  Panel   : http://localhost:8080   (login: admin / admin)
  Syslog  : UDP/TCP 514, TLS 6514
  Control : SS_CONTROL_TOKEN=test-control-token (poke enabled between containers)

  Logs    : ./docker/make_test.sh logs
  Status  : ./docker/make_test.sh ps
  Stop    : ./docker/make_test.sh down
  Wipe    : ./docker/make_test.sh clean   (also removes the test DB volume)
EOF
}

case "${1:-up}" in
  up)      "${DC[@]}" -f "$FILE" up --build -d && info ;;
  logs)    "${DC[@]}" -f "$FILE" logs -f ;;
  ps)      "${DC[@]}" -f "$FILE" ps ;;
  down)    "${DC[@]}" -f "$FILE" down ;;
  clean)   "${DC[@]}" -f "$FILE" down -v --remove-orphans ;;
  rebuild) "${DC[@]}" -f "$FILE" up --build -d --force-recreate && info ;;
  *) echo "Usage: $0 [up|logs|ps|down|clean|rebuild]" >&2; exit 1 ;;
esac
