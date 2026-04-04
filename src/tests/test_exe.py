#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para la clase Exec."""

import pytest
from unittest.mock import patch, MagicMock
from lib.exe import Exec, EnumLocationExec


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
        assert e.timeout == 30


class TestExecProperties:

    def test_set_host(self):
        e = Exec()
        e.host = "192.168.1.1"
        assert e.host == "192.168.1.1"

    def test_set_port(self):
        e = Exec()
        e.port = 2222
        assert e.port == 2222

    def test_set_user(self):
        e = Exec()
        e.user = "admin"
        assert e.user == "admin"

    def test_set_password(self):
        e = Exec()
        e.password = "secret"
        assert e.password == "secret"

    def test_set_timeout(self):
        e = Exec()
        e.timeout = 60.0
        assert e.timeout == 60.0

    def test_set_location(self):
        e = Exec()
        e.location = EnumLocationExec.remote
        assert e.location == EnumLocationExec.remote


class TestExecSetRemote:

    def test_set_remote_defaults(self):
        e = Exec()
        e.set_remote(host="server1")
        assert e.host == "server1"
        assert e.port == 22
        assert e.user == "root"

    def test_set_remote_custom(self):
        e = Exec()
        e.set_remote(host="server1", port=2222, user="admin", password="pass", timeout=10)
        assert e.host == "server1"
        assert e.port == 2222
        assert e.user == "admin"
        assert e.password == "pass"
        assert e.timeout == 10

    def test_set_remote_timeout_none_keeps_default(self):
        e = Exec()
        original_timeout = e.timeout
        e.set_remote(host="server1", timeout=None)
        assert e.timeout == original_timeout


class TestExecEmptyResult:

    def test_empty_result_no_exception(self):
        result = Exec._empty_result()
        assert result == {'out': None, 'err': None, 'code': None, 'exception': None}

    def test_empty_result_with_exception(self):
        ex = ValueError("test")
        result = Exec._empty_result(ex)
        assert result['exception'] is ex
        assert result['out'] is None


class TestExecLocal:

    @patch('lib.exe.subprocess.run')
    def test_execute_local_with_python(self, mock_run):
        """Ejecutar un comando que retorna stdout."""
        mock_run.return_value = MagicMock(stdout="42\n", stderr="", returncode=0)
        stdout, stderr, exit_code, exception = Exec.execute(command='echo 42')
        assert exception is None
        assert "42" in stdout
        assert exit_code == 0
        mock_run.assert_called_once()

    @patch('lib.exe.subprocess.run')
    def test_execute_local_stderr(self, mock_run):
        """Verificar que se captura stderr."""
        mock_run.return_value = MagicMock(stdout="", stderr="error\n", returncode=0)
        stdout, stderr, exit_code, exception = Exec.execute(command='some_cmd')
        assert exception is None
        assert "error" in stderr

    @patch('lib.exe.subprocess.run')
    def test_execute_local_exit_code(self, mock_run):
        """Verificar exit code no-cero."""
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=1)
        stdout, stderr, exit_code, exception = Exec.execute(command='fail_cmd')
        assert exit_code == 1

    def test_execute_empty_command(self):
        """Comando vacío retorna todo None."""
        stdout, stderr, exit_code, exception = Exec.execute(command="")
        assert stdout is None
        assert stderr is None
        assert exit_code is None

    def test_execute_invalid_command(self):
        """Comando inválido retorna excepción."""
        stdout, stderr, exit_code, exception = Exec.execute(
            command="/nonexistent/command_12345"
        )
        assert exception is not None


class TestExecStaticMethod:

    @patch('lib.exe.subprocess.run')
    def test_static_execute_local(self, mock_run):
        """execute() estático sin host usa ejecución local."""
        mock_run.return_value = MagicMock(stdout="hello\n", stderr="", returncode=0)
        stdout, _, exit_code, _ = Exec.execute(command='echo hello')
        assert "hello" in stdout
        assert exit_code == 0

    @patch('lib.exe.Exec.start')
    def test_static_execute_with_host_sets_remote(self, mock_start):
        """execute() con host configura modo remoto."""
        mock_start.return_value = ("out", "err", 0, None)
        Exec.execute(command="ls", host="server1", port=22, user="root", password="pass")
        mock_start.assert_called_once()


class TestExecStart:

    def test_start_no_command(self):
        """start() sin comando retorna todo None desde _empty_result de __execute_local."""
        e = Exec(command="")
        out, err, code, exc = e.start()
        assert out is None
        assert err is None
        assert code is None

    @patch('lib.exe.subprocess.run')
    def test_start_local(self, mock_run):
        mock_run.return_value = MagicMock(stdout="99\n", stderr="", returncode=0)
        e = Exec(command='echo 99')
        out, err, code, exc = e.start()
        assert "99" in out
        assert code == 0

    def test_start_remote_without_setup(self):
        """start() en modo remoto sin servidor falla con excepción."""
        e = Exec(command="echo test")
        e.location = EnumLocationExec.remote
        e.host = "nonexistent_host_12345"
        e.port = 22
        e.user = "test"
        out, err, code, exc = e.start()
        assert exc is not None
