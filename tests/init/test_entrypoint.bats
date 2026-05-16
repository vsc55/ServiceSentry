#!/usr/bin/env bats
# Tests for docker/entrypoint.sh SERVICE_ROLE dispatch.
# A mock python3 in tests/init/helpers/ intercepts all python3 calls:
#   - "python3 -" (heredoc config write) → exits 0 silently.
#   - "python3 main.py <args>"           → echoes the call so tests can assert args.

REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
HELPERS="$BATS_TEST_DIRNAME/helpers"

setup_file() {
    chmod +x "$BATS_TEST_DIRNAME/helpers/python3"
}

@test "entrypoint: SERVICE_ROLE=web passes --web args to python3" {
    run env SERVICE_ROLE=web WEB_HOST=0.0.0.0 WEB_PORT=8080 \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--web"* ]]
    [[ "$output" == *"--web-host"* ]]
    [[ "$output" == *"--web-port"* ]]
}

@test "entrypoint: SERVICE_ROLE=worker passes --daemon to python3" {
    run env SERVICE_ROLE=worker \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--daemon"* ]]
}

@test "entrypoint: SERVICE_ROLE=invalid exits 1" {
    run env SERVICE_ROLE=invalid \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 1 ]
}

@test "entrypoint: VERBOSE=true adds --verbose flag" {
    run env SERVICE_ROLE=web VERBOSE=true \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--verbose"* ]]
}

@test "entrypoint: VERBOSE=false does not add --verbose flag" {
    run env SERVICE_ROLE=worker VERBOSE=false \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" != *"--verbose"* ]]
}
