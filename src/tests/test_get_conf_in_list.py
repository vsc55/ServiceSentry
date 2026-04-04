#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para ModuleBase.get_conf_in_list — validación del match/case por tipos."""

from enum import IntEnum

import pytest

from tests.conftest import create_mock_monitor


class FakeConfigOptions(IntEnum):
    enabled = 1
    host = 100


class TestGetConfInListTypes:
    """Verifica que get_conf_in_list maneja correctamente cada tipo de opt_find."""

    def setup_method(self):
        from watchfuls.ping import Watchful
        self.Watchful = Watchful

    def _make_watchful(self, config=None):
        if config is None:
            config = {
                'watchfuls.ping': {
                    'list': {
                        'dev1': {
                            'enabled': True,
                            'label': 'MyDevice',
                            'timeout': 10,
                            'attempt': 3,
                        }
                    }
                }
            }
        return self.Watchful(create_mock_monitor(config))

    def test_opt_find_enum(self):
        """IntEnum opt_find usa .name como clave de búsqueda."""
        w = self._make_watchful()
        from watchfuls.ping import ConfigOptions
        result = w.get_conf_in_list(ConfigOptions.label, 'dev1', 'default')
        assert result == 'MyDevice'

    def test_opt_find_str(self):
        """str opt_find se usa directamente como clave."""
        w = self._make_watchful()
        result = w.get_conf_in_list('label', 'dev1', 'default')
        assert result == 'MyDevice'

    def test_opt_find_list(self):
        """list opt_find se usa como ruta de claves."""
        w = self._make_watchful()
        result = w.get_conf_in_list(['label'], 'dev1', 'default')
        assert result == 'MyDevice'

    def test_opt_find_int(self):
        """int opt_find se convierte a str."""
        config = {
            'watchfuls.ping': {
                'list': {
                    'dev1': {
                        '42': 'found_it',
                    }
                }
            }
        }
        w = self._make_watchful(config)
        result = w.get_conf_in_list(42, 'dev1', 'default')
        assert result == 'found_it'

    def test_opt_find_float(self):
        """float opt_find se convierte a str."""
        config = {
            'watchfuls.ping': {
                'list': {
                    'dev1': {
                        '3.14': 'pi_value',
                    }
                }
            }
        }
        w = self._make_watchful(config)
        result = w.get_conf_in_list(3.14, 'dev1', 'default')
        assert result == 'pi_value'

    def test_opt_find_tuple(self):
        """tuple opt_find se convierte a list."""
        w = self._make_watchful()
        result = w.get_conf_in_list(('label',), 'dev1', 'default')
        assert result == 'MyDevice'

    def test_opt_find_invalid_type_raises_type_error(self):
        """Tipo no soportado (set, bytes, etc.) lanza TypeError."""
        w = self._make_watchful()
        with pytest.raises(TypeError, match="opt_find is not valid type"):
            w.get_conf_in_list(set(), 'dev1', 'default')

    def test_opt_find_none_raises_type_error(self):
        """None como opt_find lanza TypeError (no es Enum, str, list, int, float, tuple)."""
        w = self._make_watchful()
        with pytest.raises(TypeError, match="opt_find is not valid type"):
            w.get_conf_in_list(None, 'dev1', 'default')

    def test_opt_find_bytes_raises_type_error(self):
        """bytes como opt_find lanza TypeError."""
        w = self._make_watchful()
        with pytest.raises(TypeError, match="opt_find is not valid type"):
            w.get_conf_in_list(b'key', 'dev1', 'default')

    def test_opt_find_enum_not_found_returns_default(self):
        """Enum que no existe en config retorna default."""
        w = self._make_watchful()
        result = w.get_conf_in_list(FakeConfigOptions.host, 'dev1', 'fallback')
        assert result == 'fallback'

    def test_opt_find_str_not_found_returns_default(self):
        """str que no existe en config retorna default."""
        w = self._make_watchful()
        result = w.get_conf_in_list('nonexistent', 'dev1', 'fallback')
        assert result == 'fallback'

    def test_opt_find_bool_matches_int_branch(self):
        """bool es subclase de int, así que match int() lo captura."""
        config = {
            'watchfuls.ping': {
                'list': {
                    'dev1': {
                        'True': 'bool_as_key',
                    }
                }
            }
        }
        w = self._make_watchful(config)
        # bool(True) -> case int() -> str(True) -> "True"
        result = w.get_conf_in_list(True, 'dev1', 'default')
        assert result == 'bool_as_key'
