from unittest.mock import MagicMock


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

    # Status vacio
    status = ConfigControl(None)
    status.data = {}
    mock_monitor.status = status

    # send_message no hace nada
    mock_monitor.send_message = MagicMock()

    # check_status siempre retorna False (no enviar mensajes en tests)
    mock_monitor.check_status = MagicMock(return_value=False)

    return mock_monitor
