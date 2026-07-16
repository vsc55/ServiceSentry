import os
from unittest.mock import MagicMock


def _load_env_test():
    """Auto-load a local (gitignored) ``tests/.env.test`` into ``os.environ`` before collection,
    so simply *having* the file makes its variables available to the **whole** suite — no manual
    ``source`` needed. Values already set in the real environment win (CI / inline exports
    override the file). Absent file → no-op. Only uses ``os``, so it adds no import cost."""
    path = os.path.join(os.path.dirname(__file__), 'tests', '.env.test')
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                os.environ.setdefault(key.strip(), val.strip())
    except FileNotFoundError:
        pass


_load_env_test()


def create_mock_monitor(module_config=None):
    """Crea un mock de Monitor que pasa isinstance(val, Monitor).

    :param module_config: dict con la configuracion del modulo (acceso via config_modules.get_conf).
    :returns: MagicMock con spec=Monitor.
    """
    # Importar tarde evita que pytest/debugpy cargue toda la app en el arranque
    # solo por descubrir conftest.
    from lib import Monitor
    from lib.config import ConfigControl
    from lib.debug import Debug, DebugLevel

    if module_config is None:
        module_config = {}

    mock_monitor = MagicMock(spec=Monitor)
    mock_monitor.debug = Debug(False, DebugLevel.error)

    # ConfigControl mock para config_modules
    config = ConfigControl(None)
    config.data = module_config
    mock_monitor.config_modules = config

    # Config general (vacía) + dir_modules real, para que ModuleBase._msg cargue los
    # ficheros lang/*.json reales del módulo (idioma por defecto → en_EN) en los tests.
    full_config = ConfigControl(None)
    full_config.data = {}
    mock_monitor.config = full_config
    mock_monitor.dir_modules = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchfuls')

    # Status vacio
    status = ConfigControl(None)
    status.data = {}
    mock_monitor.status = status

    # send_message no hace nada
    mock_monitor.send_message = MagicMock()

    # check_status siempre retorna False (no enviar mensajes en tests)
    mock_monitor.check_status = MagicMock(return_value=False)

    return mock_monitor
