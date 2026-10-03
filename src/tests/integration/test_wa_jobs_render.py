#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — la pantalla de Trabajos, ejecutada de verdad.
#
"""Una función que falta no es un error de sintaxis.

El guarda de `node --check` lee el guion y dice si el navegador lo puede *analizar*. No dice si
funciona: una llamada a algo que no existe analiza perfectamente y revienta al primer clic. Eso
pasó dos veces el mismo día partiendo este fichero en dos —`_jobsEvery` y `_jobsRefreshCall` se
quedaron por el camino— y la primera la encontró el usuario con la sección en blanco y un
`ReferenceError` en la consola.

Así que esto la **ejecuta**: carga el paquete del panel en node contra un DOM de mentira y dibuja
las tres pestañas con datos de mentira. Si algo llama a lo que no existe, sale aquí y no en una
pantalla.

Es la misma familia de fallo que el arnés ya cazó en otras secciones: una función que existe y
revienta antes de dibujar nada, una fila que enseña el dato de al lado, un desplegable vacío.
Ninguno se ve leyendo el fuente.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from tests.conftest import _login                       # noqa: E402
from tests.helpers import node_run, panel_bundle        # noqa: E402


def _modern_node():
    node = shutil.which('node')
    if not node:
        return None
    try:
        out = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=20)
    except Exception:                                    # pragma: no cover - sin node
        return None
    try:
        mayor = int((out.stdout or '').strip().lstrip('v').split('.')[0])
    except (TypeError, ValueError):
        return None
    return node if mayor >= 16 else None


pytestmark = pytest.mark.skipif(not _modern_node(), reason='no node >= 16 on PATH')


#: Un trabajo, un temporizador y una fila de historial, con lo justo para que cada pintor tenga
#: algo que dibujar. Inventados a propósito: lo que se prueba es el guion, no los datos.
_JOBS = [{'id': 'j1', 'package': 'dcim', 'kind': 'dcim_catalog', 'label': 'Un catálogo',
          'detail': '3', 'state': 'running', 'started': 1000.0, 'done': 3, 'total': 10,
          'error': '', 'steps': []}]
_TIMERS = [
    {'id': 'health:cable_drift', 'package': 'health', 'kind': 'dcim',
     'label': 'Contraste de cableado', 'detail': 'Contrasta los cables declarados',
     'setting': 'dcim|notify_cabling', 'enabled': True, 'scheduled': True, 'state': 'running',
     'every': 1800, 'last_run': 900.0, 'next_run': 2700.0, 'overdue': False,
     'lease': 'cable_scan', 'holder': 'web-1', 'host': 'pod-a', 'expires': 9e9,
     'holding': True},
    # El caso que estaba mal en la pantalla: el arriendo caducado de un trabajo lento.
    {'id': 'health:cert_expiry', 'package': 'health', 'kind': 'certs',
     'label': 'Caducidad de certificados', 'detail': 'Recorre los certificados',
     'setting': 'certs|notify_expiry', 'enabled': False, 'scheduled': True, 'state': 'idle',
     'every': 86400, 'last_run': 100.0, 'next_run': 0, 'overdue': False,
     'lease': 'cert_scan', 'holder': 'web-2', 'host': 'pod-b', 'expires': 200.0,
     'holding': False},
    # Y uno sin arriendo: corre en todas las réplicas.
    {'id': 'monitoring:cycle', 'package': 'monitoring', 'kind': 'monitor',
     'label': 'Sin arriendo', 'detail': '', 'setting': '', 'enabled': True,
     'scheduled': True, 'state': 'running', 'every': 300, 'last_run': 0, 'next_run': 0,
     'overdue': True, 'lease': '', 'holder': None, 'host': None, 'expires': None,
     'holding': None},
]

#: Lo que la pantalla pide y el arnés no tiene: las tres respuestas de la API, ya puestas.
_PREPARA = '''
__out = {};
_jobsData = %(jobs)s;
_jobsPast = {jobs: [{uid: 'h1', kind: 'backup', name: 'Copia', state: 'done',
                     started_at: 10, ended_at: 20}], total: 1, kept: true, limits: {}};
_jobsTimers = %(timers)s;
'''


@pytest.fixture(scope='module')
def bundle():
    """El paquete del panel, una vez por módulo.

    Levantar el panel entero por prueba serían siete arranques para leer siete veces el mismo
    guion — que es exactamente lo que esta pantalla existe para no hacer.
    """
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var,
                  pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    return panel_bundle(c)


def _dibuja(paquete, pestana: str) -> dict:
    """Pintar una pestaña entera y devolver lo que salió.

    El argumento es el **paquete**, no el cliente: la primera versión se llamaba `client` y por
    dentro usaba la variable global `bundle` —que es la función de la fixture, no su valor—, así
    que la primera llamada reventó con un `TypeError` sin sentido. Nadie la había llamado aún.
    """
    prueba = _PREPARA % {
        'jobs': json.dumps({'jobs': _JOBS, 'summary': {'running': 1, 'failed': 0, 'history': 1},
                            'now': 2000.0}),
        'timers': json.dumps({'timers': _TIMERS,
                              'summary': {'total': 3, 'enabled': 2, 'idle': 1,
                                          'overdue': 1, 'unleased': 1},
                              'now': 2000.0}),
    } + f"""
_jobsTab = {json.dumps(pestana)};
__out.html = _jobsHtml(_jobsData);
"""
    return node_run(paquete, prueba)


class TestLasTresPestanasSeDibujan:
    """La prueba que faltaba. `node --check` dice que el guion se puede analizar; esto dice que
    se puede ejecutar, que no es lo mismo y es lo que le importa a quien abre la página."""

    @pytest.mark.parametrize('pestana', ['live', 'past', 'timers'])
    def test_sin_reventar(self, bundle, pestana):
        out = node_run(bundle, _PREPARA % {
            'jobs': json.dumps({'jobs': _JOBS, 'summary': {'running': 1}, 'now': 2000.0}),
            'timers': json.dumps({'timers': _TIMERS, 'summary': {}, 'now': 2000.0}),
        } + f"_jobsTab = {json.dumps(pestana)}; __out.html = _jobsHtml(_jobsData);")
        assert out.get('html'), f'la pestaña {pestana} no dibujó nada'

    def test_y_el_boton_de_refrescar_sabe_a_quien_llamar(self, bundle):
        """`_jobsRefreshCall` se perdió al partir el fichero en dos: se llamaba desde la
        cabecera y su definición se había ido con el bloque que se movió. La sección quedaba en
        blanco con un `ReferenceError`, y ningún guarda de sintaxis podía verlo."""
        out = node_run(bundle, '''
            __out = {};
            _jobsTab = 'live';   __out.vivo    = _jobsRefreshCall();
            _jobsTab = 'past';   __out.pasado  = _jobsRefreshCall();
            _jobsTab = 'timers'; __out.temps   = _jobsRefreshCall();
        ''')
        assert out['vivo'] == 'renderJobs()'
        assert out['pasado'] == '_jobsPastRefresh()'
        assert out['temps'] == '_jobsTimersRefresh()'


class TestLaFichaDeUnTemporizador:

    def test_dice_cada_cuanto_y_no_hace_cuanto(self, bundle):
        """`_jobsEvery` se perdió igual que la otra. Y antes de perderse decía «hace 30 min»
        sobre algo que pasa CADA treinta minutos, porque reutilicé el formateador de tiempo
        transcurrido — dos palabras que convierten una frecuencia en un pasado."""
        out = node_run(bundle, '''
            __out = {};
            __out.seg  = _jobsEvery(30);
            __out.min  = _jobsEvery(1800);
            __out.hora = _jobsEvery(86400);
            __out.nada = _jobsEvery(0);
        ''')
        assert '30' in out['seg'] and 'hace' not in out['seg'].lower()
        assert '30' in out['min']
        assert out['nada'] == ''

    def test_las_tres_respuestas_de_donde_corre(self, bundle):
        """Sin arriendo, con arriendo vivo y con arriendo caducado son **tres** cosas distintas,
        y juntar dos borra la única diferencia que importa en un despliegue con réplicas."""
        out = node_run(bundle, '''
            __out = {};
            __out.todas    = _jobsTimerWhere({lease: '', state: 'running'});
            __out.viva     = _jobsTimerWhere({lease: 'k', host: 'pod-a', holding: true,
                                              state: 'running'});
            __out.caducada = _jobsTimerWhere({lease: 'k', host: 'pod-b', holding: false,
                                              state: 'idle'});
            __out.nadie    = _jobsTimerWhere({lease: 'k', host: '', holder: '',
                                              state: 'running'});
        ''')
        assert 'pod-a' in out['viva'] and 'text-muted' not in out['viva']
        assert 'pod-b' in out['caducada'] and 'text-muted' in out['caducada']
        assert 'pod' not in out['todas']
        assert 'text-warning' in out['nadie'], 'el único caso que es noticia no se marca'

    def test_un_cron_que_corre_no_sale_como_detenido(self, bundle):
        """Era lo que enseñaba la pantalla y era falso: el hilo despierta cada treinta segundos,
        está vivo, y lo único apagado es lo que hace al despertar."""
        out = node_run(bundle, """
            __out = {};
            __out.idle   = _jobsTimerRow({state: 'idle', label: 'X', every: 60,
                                          setting: 'a|b', lease: ''}, 0);
            __out.parado = _jobsTimerRow({state: 'stopped', label: 'X', every: 60,
                                          lease: ''}, 0);
            __out.activo = _jobsTimerRow({state: 'running', label: 'X', every: 60,
                                          next_run: 100, lease: ''}, 70);
        """)
        assert out['idle'] != out['parado'], 'un cron sin efecto se pinta igual que uno parado'
        assert out['activo'] != out['idle']

    def test_los_segundos_solo_salen_cuando_importan(self, bundle):
        """Por debajo de una hora entra el segundo, que es justo cuando se mira el segundo. Por
        encima sobra: una cifra que cambia sesenta veces por minuto en algo que falta medio día
        es ruido que se acaba ignorando — y con ello la fila entera."""
        out = node_run(bundle, """
            __out = {};
            __out.seg   = _jobsCountdown(24);
            __out.corto = _jobsCountdown(160);
            __out.largo = _jobsCountdown(83900);
            __out.cero  = _jobsCountdown(0);
        """)
        assert out['seg'] == '24 s'
        assert out['corto'] == '2 min 40 s'
        assert 's' not in out['largo'].replace('h', ''), f"salen segundos en {out['largo']!r}"
        assert out['cero'] and not any(c.isdigit() for c in out['cero'])

    def test_el_retraso_se_dice_como_retraso(self, bundle):
        """Reutilicé el formateador de tiempo transcurrido —que ya lleva dentro la palabra
        «hace»— y le pegué un signo delante: salió «+hace 8 min» en la pantalla."""
        out = node_run(bundle, '__out = {}; __out.tarde = _jobsLate(2520);')
        assert 'hace' not in out['tarde'].lower()
        assert '42' in out['tarde']

    def test_el_intervalo_no_repite_la_palabra_de_la_cabecera(self, bundle):
        """La columna se llama «Cada». Decirlo otra vez en cada fila es la misma palabra cinco
        veces en vertical, y roba el sitio que necesita el número."""
        out = node_run(bundle, """
            __out = {};
            __out.media  = _jobsEvery(1800);
            __out.dia    = _jobsEvery(86400);
            __out.nada   = _jobsEvery(0);
        """)
        assert out['media'] == '30 min'
        assert out['dia'] == '24 h', 'un día se dice 24 h, no «1 día(s)»'
        assert out['nada'] == ''


class TestLaPestanaSobreviveAlF5:
    """Reportado desde la pantalla: se abre Temporizadores, se pulsa F5 y vuelve «En marcha»."""

    def test_se_recuerda_la_que_estaba_delante(self, bundle):
        out = node_run(bundle, """
            __out = {};
            localStorage.setItem('ss_active_subtab_jobs', 'timers');
            __out.recordada = _jobsSavedTab();
            localStorage.setItem('ss_active_subtab_jobs', 'past');
            __out.otra = _jobsSavedTab();
        """)
        assert out['recordada'] == 'timers'
        assert out['otra'] == 'past'

    def test_y_una_basura_guardada_no_rompe_la_seccion(self, bundle):
        """Lo que hay en el almacenamiento lo escribió una versión anterior, u otra pestaña, o
        alguien a mano. Una pestaña que no existe deja la sección en blanco."""
        out = node_run(bundle, """
            __out = {};
            localStorage.setItem('ss_active_subtab_jobs', 'inventada');
            __out.basura = _jobsSavedTab();
            localStorage.removeItem('ss_active_subtab_jobs');
            __out.vacio = _jobsSavedTab();
        """)
        assert out['basura'] == 'live' and out['vacio'] == 'live' 

    def test_y_el_numero_lleva_su_marca_para_correr_solo(self, bundle):
        """La celda viaja con `data-ss-next` para que el tic no repinte la tabla entera cada
        segundo: repintar cinco filas por segundo tira el foco y cierra cualquier menú abierto."""
        out = node_run(bundle, """
            __out = {};
            __out.vivo  = _jobsTimerNext({state: 'running', every: 600, next_run: 1600}, 1000);
            __out.tarde = _jobsTimerNext({state: 'running', overdue: true, every: 600,
                                          next_run: 900}, 2000);
            __out.nada  = _jobsTimerNext({state: 'idle', every: 600, next_run: 0,
                                          setting: 'a|b'}, 1000);
        """)
        assert 'data-ss-next="1600"' in out['vivo'] and 'data-ss-every="600"' in out['vivo']
        assert 'data-ss-late' in out['tarde']
        assert 'data-ss-next' not in out['nada'], 'un cron sin próxima vuelta no cuenta nada'


class TestLaTablaEsLaQueSePropuso:
    """Una clase en el marcado no dibuja nada si ninguna regla la recoge.

    Reportado tres veces desde la pantalla, con la maqueta al lado: «no estás añadiendo bordes,
    ni la zona de títulos, ni los colores». Y era cierto — el marcado nombraba una tabla y la
    hoja no le daba ni marco ni banda de cabecera, así que las filas flotaban sobre el fondo de
    la pestaña. Un nombre de clase que no existe en el CSS no se ve leyendo la plantilla y no lo
    puede ver `node --check`: la página se dibuja entera, simplemente sin lo que se pedía.

    Así que esto dibuja la tabla y comprueba las dos mitades: que el marcado pide las piezas, y
    que la hoja de estilos **las define**.
    """

    #: Lo que la maqueta elegida tiene y una `<table>` suelta no: un marco que la separa de lo
    #: que hay alrededor, una banda para los títulos de columna y píldoras suaves de estado.
    _PIEZAS = ('ss-panel', 'ss-timer-table', 'ss-timer-head', 'ss-pill')

    def test_el_marcado_pide_las_piezas(self, bundle):
        html = _dibuja(bundle, 'timers')['html']
        for pieza in self._PIEZAS:
            assert pieza in html, f'la tabla se dibuja sin «{pieza}»'

    def test_y_la_hoja_de_estilos_las_define(self):
        raiz = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        css = io.open(os.path.join(raiz, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'),
                      encoding='utf-8').read()
        for pieza in self._PIEZAS + ('ss-pill-warn', 'ss-timer-dot-off'):
            assert f'.{pieza}' in css, f'«{pieza}» se usa en la plantilla y no existe en el CSS'

    def test_y_la_tabla_no_repinta_la_superficie_que_la_sostiene(self):
        """Lo que dejó los colores mal con las reglas ya escritas.

        Una `.table` de Bootstrap trae `--bs-table-bg: var(--bs-body-bg)` y lo pinta en **cada
        celda**: el fondo de la página por encima de la superficie del marco y de la banda de la
        cabecera, celda a celda. El CSS estaba y la librería lo cubría.
        """
        raiz = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        css = io.open(os.path.join(raiz, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'),
                      encoding='utf-8').read()
        assert '.ss-timer-table { --bs-table-bg: transparent; }' in css
        # Y el marco con superficie propia: sin ella, el borde no tiene contra qué contrastar.
        assert 'background: var(--ss-panel-bg);' in css
        for ficha in ('--ss-panel-bg', '--ss-panel-head-bg'):
            assert css.count(ficha + ':') >= 2, f'«{ficha}» no está en los dos temas'

    def test_el_estado_no_se_dice_con_un_distintivo_macizo(self, bundle):
        """Un `text-bg-warning` sólido en una tabla de cinco filas grita más que el propio
        retraso, y el ámbar deja de significar algo cuando se gasta en lo que no lo necesita."""
        out = node_run(bundle, """
            __out = {};
            __out.tarde = _jobsTimerNext({state: 'running', overdue: true, every: 600,
                                          next_run: 900}, 3420);
            __out.sin   = _jobsTimerNext({state: 'idle', every: 600, next_run: 0,
                                          setting: 'a|b'}, 1000);
        """)
        assert 'ss-pill ss-pill-warn' in out['tarde']
        assert 'text-bg-warning' not in out['tarde']
        assert 'ss-pill' in out['sin'] and 'badge' not in out['sin']

    def test_los_colores_son_del_tema_y_no_los_de_un_distintivo(self, bundle):
        """`bg-success` es un verde de fondo de distintivo —pensado para llevar letras blancas
        encima— y de punto de siete píxeles se lee apagado; `--bs-primary` es el azul de los
        botones y en una barra de 3 px pesa más que el número que tiene al lado. Reportado desde
        la pantalla con la maqueta delante: «el diseño es correcto, pero los colores no»."""
        out = node_run(bundle, """
            __out = {};
            __out.vivo = _jobsTimerRow({state: 'running', label: 'X', every: 60,
                                        next_run: 100, lease: ''}, 70);
        """)
        assert 'bg-success' not in out['vivo'] and 'bg-secondary' not in out['vivo']
        assert 'ss-timer-dot-on' in out['vivo']

        raiz = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        css = io.open(os.path.join(raiz, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'),
                      encoding='utf-8').read()
        # Y los dos temas, que es donde se cae: una ficha definida sólo en uno deja el otro
        # dibujando con el color de nadie.
        for ficha in ('--ss-timer-on', '--ss-timer-late', '--ss-timer-bar', '--ss-timer-track'):
            assert css.count(ficha + ':') >= 2, f'«{ficha}» no está en los dos temas'


class TestLaCabeceraEsLaDeLaPestanaQueMiras:
    """Se quedó quieta cuando la sección pasó de una lista a tres.

    El título decía «Trabajos» y los dos contadores —*en marcha* y *con error*— eran de la
    primera lista, **mientras mirabas Temporizadores**. Un número que habla de otra pantalla es
    la misma clase de error que el «Apagado» sobre un cron que corre: no sobra, contesta otra
    pregunta. La línea de ayuda de debajo sí cambiaba con la pestaña desde el primer día.
    """

    _PREP = """
        __out = {};
        _jobsData = {jobs: [], summary: {running: 2, failed: 1, history: 8}, now: 0};
        _jobsPast = {jobs: [], total: 8, kept: true, limits: {}};
        _jobsTimers = {timers: [], summary: {overdue: 1}, now: 0};
        ['live', 'past', 'timers'].forEach(p => {
            _jobsTab = p; __out[p] = _jobsHead(_jobsData.summary);
        });
        _jobsTimers.summary.overdue = 3;
        _jobsTab = 'timers'; __out.tres = _jobsHead(_jobsData.summary);
    """

    def test_cada_pestana_pone_su_nombre(self, bundle):
        out = node_run(bundle, self._PREP)
        assert 'Jobs' in out['live']
        assert 'history' in out['past'].lower()
        assert 'Timers' in out['timers']
        # Y su propio icono: tres relojes distintos para tres preguntas distintas.
        iconos = {out[p].split('bi bi-')[1].split('"')[0] for p in ('live', 'past', 'timers')}
        assert len(iconos) == 3, f'dos pestañas comparten icono: {iconos}'

    def test_y_los_contadores_no_se_cuelan_de_una_a_otra(self, bundle):
        out = node_run(bundle, self._PREP)
        assert 'running' in out['live'] and 'failed' in out['live']
        assert 'running' not in out['timers'], 'la cifra de trabajos sigue en Temporizadores'
        assert 'overdue' in out['timers']
        assert 'running' not in out['past'] and 'overdue' not in out['past']

    def test_el_historial_no_repite_una_cifra_que_ya_esta_dos_veces(self, bundle):
        """Cuántos hay lo dice la pestaña y cuántos se guardan lo dice el pie de la tabla."""
        out = node_run(bundle, self._PREP)
        # Sin las etiquetas: `<h5>` lleva un cinco, y la primera versión de esta prueba lo contó
        # como una cifra de la cabecera.
        texto = re.sub(r'<[^>]+>', ' ', out['past'])
        assert not any(c.isdigit() for c in texto), texto

    def test_y_uno_atrasado_no_se_dice_en_plural(self, bundle):
        """Las palabras se ponen a mano porque el arnés habla **inglés**, y en inglés
        «overdue» es la misma en singular y en plural.

        La primera versión de esta prueba miraba la salida tal cual y pasaba igual con la rama
        del singular borrada: no comprobaba nada. Se vio mutando el código, que es para lo que
        se mutan las guardas. `t()` lee de `I18N`, así que basta con escribir ahí dos palabras
        que de verdad se distingan.
        """
        out = node_run(bundle, """
            __out = {};
            I18N.jobs_overdue_one = 'atrasado';
            I18N.jobs_overdue_n   = 'atrasados';
            _jobsTab = 'timers';
            _jobsData = {jobs: [], summary: {}, now: 0};
            _jobsTimers = {timers: [], summary: {overdue: 1}, now: 0};
            __out.uno = _jobsHead({});
            _jobsTimers.summary.overdue = 3;
            __out.tres = _jobsHead({});
        """)
        assert '1 atrasado<' in out['uno'] or '1 atrasado ' in out['uno'], out['uno']
        assert 'atrasados' not in out['uno'], 'un atrasado se dice en plural'
        assert 'atrasados' in out['tres']
