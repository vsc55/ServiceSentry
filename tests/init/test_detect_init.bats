#!/usr/bin/env bats
# Tests for the detect_init() function used by install.sh / update.sh / uninstall.sh.
# Commands are mocked via PATH to keep tests hermetic.

REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"

setup() {
    MOCK_DIR="$(mktemp -d)"
    # Extract detect_init() verbatim from install.sh so we test the real function.
    DETECT_FN="$(sed -n '/^detect_init() {/,/^}/p' "$REPO_ROOT/install.sh")"
}

teardown() {
    rm -rf "$MOCK_DIR"
}

@test "detect_init: returns 'systemd' when systemctl is available" {
    printf '#!/bin/sh\nexit 0\n' > "$MOCK_DIR/systemctl"
    chmod +x "$MOCK_DIR/systemctl"

    result="$(PATH="$MOCK_DIR:$PATH" bash -c "$DETECT_FN; detect_init")"
    [ "$result" = "systemd" ]
}

@test "detect_init: returns 'openrc' when systemctl --version fails but rc-service exists" {
    # systemctl exists but --version returns non-zero → detect_init skips systemd branch.
    printf '#!/bin/sh\n[ "$1" = "--version" ] && exit 1; exit 0\n' > "$MOCK_DIR/systemctl"
    chmod +x "$MOCK_DIR/systemctl"
    printf '#!/bin/sh\nexit 0\n' > "$MOCK_DIR/rc-service"
    chmod +x "$MOCK_DIR/rc-service"

    result="$(PATH="$MOCK_DIR:$PATH" bash -c "$DETECT_FN; detect_init")"
    [ "$result" = "openrc" ]
}

@test "detect_init: returns 'unknown' when neither systemctl nor rc-service is found" {
    # Empty mock dir: no systemctl, no rc-service, no /sbin/openrc-run on CI.
    result="$(PATH="$MOCK_DIR" bash -c "$DETECT_FN; detect_init")"
    [ "$result" = "unknown" ]
}
