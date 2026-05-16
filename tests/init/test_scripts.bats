#!/usr/bin/env bats
# Tests for install.sh / update.sh / uninstall.sh:
# root-check enforcement and uninstall.sh argument parsing.

REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"

@test "install.sh: exits 1 when not root" {
    run bash "$REPO_ROOT/install.sh"
    [ "$status" -eq 1 ]
    [[ "$output" == *"must be run as root"* ]]
}

@test "update.sh: exits 1 when not root" {
    run bash "$REPO_ROOT/update.sh"
    [ "$status" -eq 1 ]
    [[ "$output" == *"must be run as root"* ]]
}

@test "uninstall.sh: exits 1 when not root" {
    run bash "$REPO_ROOT/uninstall.sh"
    [ "$status" -eq 1 ]
    [[ "$output" == *"must be run as root"* ]]
}

@test "uninstall.sh --help: exits 0 and prints usage" {
    run bash "$REPO_ROOT/uninstall.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" == *"Usage:"* ]]
}

@test "uninstall.sh -h: exits 0 and prints usage" {
    run bash "$REPO_ROOT/uninstall.sh" -h
    [ "$status" -eq 0 ]
    [[ "$output" == *"Usage:"* ]]
}

@test "uninstall.sh --bad-flag: exits 1 with unknown parameter error" {
    run bash "$REPO_ROOT/uninstall.sh" --bad-flag
    [ "$status" -eq 1 ]
    [[ "$output" == *"unknown parameter"* ]]
}
