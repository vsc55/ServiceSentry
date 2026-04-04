#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para ConfigStore y ConfigControl."""

import json
import os
import tempfile

import pytest

from lib.config.config_control import ConfigControl
from lib.config.config_store import ConfigStore
from lib.config.config_type_return import ConfigTypeReturn


class TestConfigStore:

    def test_is_exist_file_none(self):
        cs = ConfigStore(None)
        assert cs.is_exist_file is False

    def test_is_exist_file_nonexistent(self):
        cs = ConfigStore("/nonexistent/path/file.json")
        assert cs.is_exist_file is False

    def test_read_and_save(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({"key": "value"}, f)
            tmp_path = f.name
        try:
            cs = ConfigStore(tmp_path)
            assert cs.is_exist_file is True
            data = cs.read()
            assert data == {"key": "value"}
        finally:
            os.unlink(tmp_path)

    def test_save_creates_file(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tmp_path = f.name
        try:
            cs = ConfigStore(tmp_path)
            assert cs.save({"hello": "world"}) is True
            # Verificar que el archivo se escribió correctamente
            with open(tmp_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            assert data == {"hello": "world"}
        finally:
            os.unlink(tmp_path)

    def test_read_nonexistent_returns_default(self):
        cs = ConfigStore("/nonexistent/file.json")
        assert cs.read(def_return="default") == "default"

    def test_read_nonexistent_returns_none(self):
        cs = ConfigStore("/nonexistent/file.json")
        assert cs.read() is None

    def test_is_writable_file_none(self):
        """File None no es writable."""
        cs = ConfigStore(None)
        assert cs.is_writable_file is False

    def test_is_writable_file_empty(self):
        """File vacío no es writable."""
        cs = ConfigStore("")
        assert cs.is_writable_file is False

    def test_is_writable_file_existing(self):
        """Archivo existente con permisos es writable."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tmp_path = f.name
        try:
            cs = ConfigStore(tmp_path)
            assert cs.is_writable_file is True
        finally:
            os.unlink(tmp_path)

    def test_is_writable_file_nonexistent_writable_dir(self):
        """Archivo no existente en directorio con permisos es writable."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cs = ConfigStore(os.path.join(tmp_dir, 'new_file.json'))
            assert cs.is_writable_file is True

    def test_is_writable_file_nonexistent_dir(self):
        """Archivo en directorio inexistente no es writable."""
        cs = ConfigStore("/nonexistent_dir_xyz/file.json")
        assert cs.is_writable_file is False

    def test_save_empty_file_path(self):
        """save() con file vacío retorna False."""
        cs = ConfigStore(None)
        assert cs.save({"key": "value"}) is False

    def test_save_non_serializable_data(self):
        """save() con datos no JSON-serializables retorna False."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tmp_path = f.name
        try:
            cs = ConfigStore(tmp_path)
            assert cs.save({"obj": object()}) is False
        finally:
            os.unlink(tmp_path)

    def test_read_invalid_json(self):
        """read() con JSON inválido retorna el valor por defecto."""
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False,
            encoding='utf-8'
        ) as f:
            f.write("{invalid json content!!!")
            tmp_path = f.name
        try:
            cs = ConfigStore(tmp_path)
            assert cs.read() is None
            assert cs.read(def_return="fallback") == "fallback"
        finally:
            os.unlink(tmp_path)

    def test_save_formatted_json(self):
        """save() escribe JSON con indentación y soporte unicode."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tmp_path = f.name
        try:
            cs = ConfigStore(tmp_path)
            cs.save({"nombre": "José", "café": True})
            with open(tmp_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Verificar indentación (4 espacios)
            assert '    "nombre"' in content
            # Verificar que no usa escape ASCII para caracteres unicode
            assert "José" in content
            assert "café" in content
        finally:
            os.unlink(tmp_path)

    def test_file_property_getter_setter(self):
        """Propiedad file se puede leer y escribir."""
        cs = ConfigStore("/initial/path.json")
        assert cs.file == "/initial/path.json"
        cs.file = "/new/path.json"
        assert cs.file == "/new/path.json"


class TestConfigControl:

    def setup_method(self):
        self.cc = ConfigControl(None)
        self.cc.data = {'level1': {'level2': 'OK', 'number': 42}, 'enabled': True}

    def test_get_conf_simple_key(self):
        assert self.cc.get_conf('enabled') is True

    def test_get_conf_nested_list(self):
        assert self.cc.get_conf(['level1', 'level2']) == 'OK'

    def test_get_conf_nested_tuple(self):
        assert self.cc.get_conf(('level1', 'level2')) == 'OK'

    def test_get_conf_not_found_returns_default(self):
        assert self.cc.get_conf('nonexistent', 'default') == 'default'

    def test_get_conf_deep_not_found(self):
        assert self.cc.get_conf(['level1', 'level2', 'level3'], 'nope') == 'nope'

    def test_get_conf_r_type_list(self):
        assert self.cc.get_conf('nonexistent', r_type=ConfigTypeReturn.LIST) == []

    def test_get_conf_r_type_dict(self):
        assert self.cc.get_conf('nonexistent', r_type=ConfigTypeReturn.DICT) == {}

    def test_get_conf_r_type_int(self):
        assert self.cc.get_conf('nonexistent', r_type=ConfigTypeReturn.INT) == 0

    def test_get_conf_r_type_bool(self):
        assert self.cc.get_conf('nonexistent', r_type=ConfigTypeReturn.BOOL) is False

    def test_get_conf_r_type_str(self):
        assert self.cc.get_conf('nonexistent', r_type=ConfigTypeReturn.STR) == ''

    def test_get_conf_returns_dict_for_intermediate(self):
        result = self.cc.get_conf('level1')
        assert isinstance(result, dict)
        assert result['level2'] == 'OK'

    def test_is_exist_conf_true(self):
        assert self.cc.is_exist_conf(['level1', 'level2']) is True

    def test_is_exist_conf_true_tuple(self):
        assert self.cc.is_exist_conf(('level1', 'level2')) is True

    def test_is_exist_conf_false(self):
        assert self.cc.is_exist_conf(['level1', 'level3']) is False

    def test_is_exist_conf_string(self):
        assert self.cc.is_exist_conf('level1') is True

    def test_is_exist_conf_with_split(self):
        assert self.cc.is_exist_conf('level1:level2', ':') is True

    def test_set_conf_simple(self):
        assert self.cc.set_conf('new_key', 'new_val') is True
        assert self.cc.get_conf('new_key') == 'new_val'

    def test_set_conf_nested(self):
        assert self.cc.set_conf(['a', 'b', 'c'], 'deep') is True
        assert self.cc.get_conf(['a', 'b', 'c']) == 'deep'

    def test_set_conf_with_split(self):
        assert self.cc.set_conf('x:y:z', 'val', ':') is True
        assert self.cc.get_conf(['x', 'y', 'z']) == 'val'

    def test_set_conf_overwrite(self):
        self.cc.set_conf('enabled', False)
        assert self.cc.get_conf('enabled') is False

    def test_set_conf_empty_key_returns_false(self):
        assert self.cc.set_conf(None, 'val') is False
        assert self.cc.set_conf('', 'val') is False

    def test_set_conf_data_dict(self):
        external = {'a': 1}
        result = self.cc.set_conf('b', 2, data_dict=external)
        assert isinstance(result, dict)
        assert result == {'a': 1, 'b': 2}


class TestConfigControlConvertFindKey:

    def test_string_to_list(self):
        result = ConfigControl.convert_find_key_to_list("hello world")
        assert result == ["hello", "world"]

    def test_string_with_split(self):
        result = ConfigControl.convert_find_key_to_list("a:b:c", ":")
        assert result == ["a", "b", "c"]

    def test_list_input(self):
        result = ConfigControl.convert_find_key_to_list(["a", "b"])
        assert result == ["a", "b"]

    def test_tuple_input(self):
        result = ConfigControl.convert_find_key_to_list(("a", "b"))
        assert result == ["a", "b"]

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError):
            ConfigControl.convert_find_key_to_list(123)

    def test_list_is_copy(self):
        original = ["a", "b"]
        result = ConfigControl.convert_find_key_to_list(original)
        result.append("c")
        assert len(original) == 2


class TestConfigControlIsChanged:

    def test_changed_initially_with_none(self):
        # __init__ llama self.data = init_data, que activa el setter y establece _update.
        # Como _load es None y _update está establecido, is_changed retorna True.
        cc = ConfigControl(None)
        assert cc.is_changed is True

    def test_changed_after_data_set(self):
        cc = ConfigControl(None)
        cc.data = {"key": "value"}
        assert cc.is_changed is True

    def test_not_changed_after_read(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({"key": "value"}, f)
            tmp_path = f.name
        try:
            cc = ConfigControl(tmp_path)
            cc.read()
            assert cc.is_changed is False
        finally:
            os.unlink(tmp_path)

    def test_changed_after_read_then_modify(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({"key": "value"}, f)
            tmp_path = f.name
        try:
            cc = ConfigControl(tmp_path)
            cc.read()
            cc.data = {"key": "modified"}
            assert cc.is_changed is True
        finally:
            os.unlink(tmp_path)

    def test_not_changed_after_save(self):
        """Tras save() exitoso, is_changed es False."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tmp_path = f.name
        try:
            cc = ConfigControl(tmp_path)
            cc.data = {"key": "value"}
            assert cc.is_changed is True
            cc.save()
            assert cc.is_changed is False
        finally:
            os.unlink(tmp_path)


class TestConfigControlIsLoad:

    def test_not_loaded_initially(self):
        cc = ConfigControl(None)
        assert cc.is_load is False

    def test_loaded_after_read(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({"a": 1}, f)
            tmp_path = f.name
        try:
            cc = ConfigControl(tmp_path)
            cc.read()
            assert cc.is_load is True
        finally:
            os.unlink(tmp_path)

    def test_not_loaded_after_read_nonexistent(self):
        """read() de archivo inexistente deja is_load en False."""
        cc = ConfigControl("/nonexistent/file.json")
        cc.read()
        assert cc.is_load is False

    def test_loaded_after_save(self):
        """save() exitoso establece is_load en True."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tmp_path = f.name
        try:
            cc = ConfigControl(tmp_path)
            cc.data = {"key": "value"}
            assert cc.is_load is False
            cc.save()
            assert cc.is_load is True
        finally:
            os.unlink(tmp_path)


class TestConfigControlSaveAndRead:

    def test_save_and_read_cycle(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tmp_path = f.name
        try:
            cc = ConfigControl(tmp_path)
            cc.data = {"test": [1, 2, 3], "nested": {"a": True}}
            cc.save()

            cc2 = ConfigControl(tmp_path)
            cc2.read()
            assert cc2.get_conf('test') == [1, 2, 3]
            assert cc2.get_conf(['nested', 'a']) is True
        finally:
            os.unlink(tmp_path)

    def test_save_failed_does_not_update_timestamps(self):
        """save() fallido no actualiza _load ni _update."""
        cc = ConfigControl(None)
        cc.data = {"key": "value"}
        assert cc.is_load is False
        cc.save()  # Falla porque file es None
        assert cc.is_load is False


class TestConfigControlIsData:

    def test_is_data_false_initially(self):
        """Sin init_data, is_data es False."""
        cc = ConfigControl(None)
        assert cc.is_data is False

    def test_is_data_true_after_set(self):
        """Tras asignar datos, is_data es True."""
        cc = ConfigControl(None)
        cc.data = {"key": "value"}
        assert cc.is_data is True

    def test_is_data_true_with_empty_dict(self):
        """Un dict vacío es dato válido (no None)."""
        cc = ConfigControl(None)
        cc.data = {}
        assert cc.is_data is True

    def test_is_data_false_after_set_none(self):
        """Asignar None deja is_data en False."""
        cc = ConfigControl(None)
        cc.data = {"key": "value"}
        assert cc.is_data is True
        cc.data = None
        assert cc.is_data is False

    def test_is_data_with_init_data(self):
        """init_data en constructor establece is_data."""
        cc = ConfigControl(None, init_data={"init": True})
        assert cc.is_data is True

    def test_data_returns_empty_dict_when_none(self):
        """data retorna {} cuando _data es None."""
        cc = ConfigControl(None)
        assert cc.data == {}
        assert cc.is_data is False


class TestConfigControlReadOptions:

    def test_read_return_data_true(self):
        """read(return_data=True) retorna los datos."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({"key": "value"}, f)
            tmp_path = f.name
        try:
            cc = ConfigControl(tmp_path)
            result = cc.read(return_data=True)
            assert result == {"key": "value"}
        finally:
            os.unlink(tmp_path)

    def test_read_return_data_false(self):
        """read(return_data=False) retorna None pero carga los datos."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({"key": "value"}, f)
            tmp_path = f.name
        try:
            cc = ConfigControl(tmp_path)
            result = cc.read(return_data=False)
            assert result is None
            # Pero los datos están cargados
            assert cc.is_data is True
            assert cc.is_load is True
            assert cc.get_conf('key') == 'value'
        finally:
            os.unlink(tmp_path)

    def test_read_nonexistent_sets_none(self):
        """read() de archivo inexistente: is_data False, is_load False."""
        cc = ConfigControl("/nonexistent/file.json")
        cc.read()
        assert cc.is_data is False
        assert cc.is_load is False
        assert cc.is_changed is False

    def test_read_with_def_return(self):
        """read() de archivo inexistente con def_return usa ese valor."""
        cc = ConfigControl("/nonexistent/file.json")
        result = cc.read(def_return={"default": True})
        assert result == {"default": True}
        assert cc.is_data is True
        assert cc.is_load is True
