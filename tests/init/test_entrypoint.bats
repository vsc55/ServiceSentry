#!/usr/bin/env bats
# Tests for docker/entrypoint.sh SS_SERVICE_ROLE dispatch.
# A mock python3 in tests/init/helpers/ intercepts all python3 calls:
#   - "python3 -" (heredoc config write) → exits 0 silently.
#   - "python3 main.py <args>"           → echoes the call so tests can assert args.

REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
HELPERS="$BATS_TEST_DIRNAME/helpers"

setup_file() {
    chmod +x "$BATS_TEST_DIRNAME/helpers/python3"
}

@test "entrypoint: SS_SERVICE_ROLE=web passes --web args to python3" {
    run env SS_SERVICE_ROLE=web SS_WEB_HOST=0.0.0.0 SS_WEB_PORT=8080 \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--web"* ]]
    [[ "$output" == *"--web-host"* ]]
    [[ "$output" == *"--web-port"* ]]
}

@test "entrypoint: SS_SERVICE_ROLE=worker passes --monitor to python3" {
    run env SS_SERVICE_ROLE=worker \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--monitor"* ]]
}

@test "entrypoint: SS_SERVICE_ROLE=syslog honours SS_SYSLOG_HOST/PORT" {
    run env SS_SERVICE_ROLE=syslog SS_SYSLOG_HOST=10.0.0.5 SS_SYSLOG_PORT=5514 \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--syslog"* ]]
    [[ "$output" == *"--syslog-host"* ]]
    [[ "$output" == *"--syslog-port"* ]]
}

@test "entrypoint: SS_SERVICE_ROLE=invalid exits 1" {
    run env SS_SERVICE_ROLE=invalid \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 1 ]
}

@test "entrypoint: SS_VERBOSE=true adds --verbose flag" {
    run env SS_SERVICE_ROLE=web SS_VERBOSE=true \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--verbose"* ]]
}

@test "entrypoint: SS_VERBOSE=false does not add --verbose flag" {
    run env SS_SERVICE_ROLE=worker SS_VERBOSE=false \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" != *"--verbose"* ]]
}

@test "entrypoint: SS_LOG_LEVEL adds --log-level flag" {
    run env SS_SERVICE_ROLE=worker SS_LOG_LEVEL=info \
        PATH="$HELPERS:$PATH" \
        sh "$REPO_ROOT/docker/entrypoint.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--log-level"* ]]
}
