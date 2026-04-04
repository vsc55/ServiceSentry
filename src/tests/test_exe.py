#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para la clase Exec, ExecConfig y ExecResult."""

from unittest.mock import MagicMock, patch

import pytest

from lib.exe import EnumLocationExec, Exec, ExecConfig, ExecResult


class TestExecResult:

    def test_default_values(self):
        r = ExecResult()
        assert r.out is None
        assert r.err is None
        assert r.code is None
        assert r.exception is None

    def test_with_values(self):
        r = ExecResult(out="hello", err="", code=0)
        assert r.out == "hello"
        assert r.err == ""
        assert r.code == 0
        assert r.exception is None

    def test_with_exception(self):
        ex = ValueError("test")
        r = ExecResult(exception=ex)
        assert r.exception is ex


class TestExecConfig:

    def test_default_values(self):
        cfg = ExecConfig()
        assert cfg.command == ""
        assert cfg.location == EnumLocationExec.local
        assert cfg.host == ""
        assert cfg.port == 22
        assert cfg.user == "root"
        assert cfg.password is None
        assert cfg.key_file is None
        assert cfg.timeout == 30

    def test_custom_values(self):
        cfg = ExecConfig(command="ls", host="server1", port=2222, user="admin", password="pass")
        assert cfg.command == "ls"
        assert cfg.host == "server1"
        assert cfg.port == 2222
        assert cfg.user == "admin"
        assert cfg.password == "pass"


class TestEnumLocationExec:

    def test_local_value(self):
        assert EnumLocationExec.local == "local"

    def test_remote_value(self):
        assert EnumLocationExec.remote == "remote"


class TestExecInit:

    def test_default_location_local(self):
        e = Exec()
        assert e.location == EnumLocationExec.local

    def test_init_with_command(self):
        e = Exec(command="echo hello")
        assert e.command == "echo hello"

    def test_default_command_empty(self):
        e = Exec()
        assert e.command == ""

    def test_default_timeout(self):
        e = Exec()
        assert e.config.timeout == 30

    def test_config_is_exec_config(self):
        e = Exec()
        assert isinstance(e.config, ExecConfig)


class TestExecProperties:

    def test_set_location(self):
        e = Exec()
        e.location = EnumLocationExec.remote
        assert e.location == EnumLocationExec.remote
        assert e.config.location == EnumLocationExec.remote

    def test_set_command(self):
        e = Exec()
        e.command = "echo test"
        assert e.command == "echo test"
        assert e.config.command == "echo test"

    def test_default_key_file_none(self):
        e = Exec()
        assert e.config.key_file is None

    def test_config_host_default(self):
        e = Exec()
        assert e.config.host == ""

    def test_config_port_default(self):
        e = Exec()
        assert e.config.port == 22

    def test_config_user_default(self):
        e = Exec()
        assert e.config.user == "root"


class TestExecSetRemote:

    def test_set_remote_defaults(self):
        e = Exec()
        e.set_remote(host="server1")
        assert e.config.host == "server1"
        assert e.config.port == 22
        assert e.config.user == "root"
        assert e.config.location == EnumLocationExec.remote

    def test_set_remote_custom(self):
        e = Exec()
        e.set_remote(host="server1", port=2222, user="admin", password="pass", timeout=10)
        assert e.config.host == "server1"
        assert e.config.port == 2222
        assert e.config.user == "admin"
        assert e.config.password == "pass"
        assert e.config.timeout == 10

    def test_set_remote_with_key_file(self):
        e = Exec()
        e.set_remote(host="server1", user="admin", key_file="/home/user/.ssh/id_rsa")
        assert e.config.key_file == "/home/user/.ssh/id_rsa"
        assert e.config.password is None

    def test_set_remote_key_file_default_none(self):
        e = Exec()
        e.set_remote(host="server1")
        assert e.config.key_file is None

    def test_set_remote_timeout_none_keeps_default(self):
        e = Exec()
        original_timeout = e.config.timeout
        e.set_remote(host="server1", timeout=None)
        assert e.config.timeout == original_timeout


class TestExecEmptyResult:

    def test_empty_result_no_exception(self):
        result = Exec._empty_result()
        assert isinstance(result, ExecResult)
        assert result.out is None
        assert result.err is None
        assert result.code is None
        assert result.exception is None

    def test_empty_result_with_exception(self):
        ex = ValueError("test")
        result = Exec._empty_result(ex)
        assert result.exception is ex
        assert result.out is None


class TestExecLocal:

    @patch('lib.exe.subprocess.run')
    def test_execute_local_with_python(self, mock_run):
        """Ejecutar un comando que retorna stdout."""
        mock_run.return_value = MagicMock(stdout="42\n", stderr="", returncode=0)
        result = Exec.execute(command='echo 42')
        assert isinstance(result, ExecResult)
        assert result.exception is None
        assert "42" in result.out
        assert result.code == 0
        mock_run.assert_called_once()

    @patch('lib.exe.subprocess.run')
    def test_execute_local_stderr(self, mock_run):
        """Verificar que se captura stderr."""
        mock_run.return_value = MagicMock(stdout="", stderr="error\n", returncode=0)
        result = Exec.execute(command='some_cmd')
        assert result.exception is None
        assert "error" in result.err

    @patch('lib.exe.subprocess.run')
    def test_execute_local_exit_code(self, mock_run):
        """Verificar exit code no-cero."""
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=1)
        result = Exec.execute(command='fail_cmd')
        assert result.code == 1

    def test_execute_empty_command(self):
        """Comando vacío retorna todo None."""
        result = Exec.execute(command="")
        assert result.out is None
        assert result.err is None
        assert result.code is None

    def test_execute_invalid_command(self):
        """Comando inválido retorna excepción."""
        result = Exec.execute(command="/nonexistent/command_12345")
        assert result.exception is not None


class TestExecStaticMethod:

    @patch('lib.exe.subprocess.run')
    def test_static_execute_local(self, mock_run):
        """execute() estático sin host usa ejecución local."""
        mock_run.return_value = MagicMock(stdout="hello\n", stderr="", returncode=0)
        result = Exec.execute(command='echo hello')
        assert "hello" in result.out
        assert result.code == 0

    @patch('lib.exe.Exec.start')
    def test_static_execute_with_host_sets_remote(self, mock_start):
        """execute() con host configura modo remoto."""
        mock_start.return_value = ExecResult(out="out", err="err", code=0)
        Exec.execute(command="ls", host="server1", port=22, user="root", password="pass")
        mock_start.assert_called_once()

    @patch('lib.exe.Exec.start')
    def test_static_execute_with_key_file(self, mock_start):
        """execute() with key_file sets it in remote config."""
        mock_start.return_value = ExecResult(out="out", err="err", code=0)
        Exec.execute(command="ls", host="server1", user="root",
                     key_file="/home/user/.ssh/id_rsa")
        mock_start.assert_called_once()

    @patch('lib.exe.subprocess.run')
    def test_static_execute_local_with_timeout(self, mock_run):
        """execute() local sin host pero con timeout lo aplica."""
        mock_run.return_value = MagicMock(stdout="ok\n", stderr="", returncode=0)
        result = Exec.execute(command="echo ok", timeout=5)
        assert isinstance(result, ExecResult)


class TestExecStart:

    def test_start_no_command(self):
        """start() sin comando retorna ExecResult vacío."""
        e = Exec(command="")
        result = e.start()
        assert isinstance(result, ExecResult)
        assert result.out is None
        assert result.err is None
        assert result.code is None

    @patch('lib.exe.subprocess.run')
    def test_start_local(self, mock_run):
        mock_run.return_value = MagicMock(stdout="99\n", stderr="", returncode=0)
        e = Exec(command='echo 99')
        result = e.start()
        assert isinstance(result, ExecResult)
        assert "99" in result.out
        assert result.code == 0

    def test_start_remote_without_setup(self):
        """start() en modo remoto sin servidor falla con excepción."""
        e = Exec(command="echo test")
        e.location = EnumLocationExec.remote
        e.config.host = "nonexistent_host_12345"
        e.config.port = 22
        e.config.user = "test"
        result = e.start()
        assert isinstance(result, ExecResult)
        assert result.exception is not None
