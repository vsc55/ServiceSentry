#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module check execution mixin for WebAdmin."""

import os


class _ChecksMixin:
    """Run module checks via Monitor and return serialisable results."""

    def _run_checks(self, requested) -> tuple[dict, list[str]]:
        """Execute module checks and return serialisable results.

        *requested* is either the string ``"all"`` or a list of module
        names.  Returns ``(results_dict, error_list)``.
        """
        import sys

        from lib import Monitor

        if self._modules_dir and self._modules_dir not in sys.path:
            sys.path.insert(0, self._modules_dir)
        parent = os.path.dirname(self._modules_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        dir_base = os.path.dirname(self._modules_dir)
        monitor = Monitor(dir_base, self._config_dir,
                          self._modules_dir, self._var_dir)

        if requested == 'all':
            module_names = monitor._get_enabled_modules()
        else:
            module_names = [m for m in requested if isinstance(m, str)]

        results: dict = {}
        errors: list[str] = []

        for mod_name in module_names:
            try:
                success, result_name, result_data = monitor.check_module(mod_name)
                if success and result_data is not None:
                    monitor._process_module_result(result_name, result_data)
                    monitor.status.save()  # save after each module so polling can read partial results
                    items: dict = {}
                    for key in result_data.list:
                        items[key] = {
                            'status': result_data.get_status(key),
                            'message': result_data.get_message(key),
                        }
                    results[mod_name] = items
                else:
                    errors.append(mod_name)
            except Exception as exc:
                errors.append(f'{mod_name}: {exc}')
        return results, errors
