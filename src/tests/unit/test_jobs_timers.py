#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — once hilos corriendo por detrás y ninguno aparecía en ninguna parte.
#
"""Lo que despierta solo: cada cuánto, y —con varias réplicas— en cuál de ellas.

La lista de al lado contesta *qué se está haciendo*: un trabajo con principio, progreso y fin.
Un temporizador no es eso. Duerme el noventa y nueve por ciento del tiempo y no tiene un total
del que ser una fracción, y meterlo en aquella lista dejaría cinco filas permanentes en
«ejecutando» que nunca avanzan, arruinando la pantalla que existe para ver qué se está haciendo
ahora.

Lo que estas pruebas sujetan:

* que la lista se **declare** y no se nombre — un paquete nuevo aparece diciéndolo, no editando
  la pantalla;
* que «cuándo corrió» salga del **arriendo** y no de la memoria del proceso, porque en una
  réplica que no es la líder la memoria vale cero y eso se lee como «no ha corrido nunca» en vez
  de como «no lo corro yo»;
* y que **sin arriendo** no sea lo mismo que **con arriendo y sin dueño**: uno corre en todas
  las réplicas y el otro no corre en ninguna.

Sin Flask: el colector recibe un objeto con lo que pregunta, y nada más.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.jobs import timers as T                              # noqa: E402


class _Arriendos:
    """El doble de la tienda de arriendos.

    Expone `leases()` y **no** `list_leaders()`: el colector dejó de usar el segundo el día que
    se vio que descartar los caducados era tirar el único «cuándo corrió» que se ve entre
    contenedores. Un doble con el método viejo dejaría estas pruebas pasando por la rama de
    excepción del colector — verdes y sin comprobar nada.
    """

    def __init__(self, filas):
        self._filas = filas

    def leases(self):
        return self._filas


class _Wa:
    """Lo justo que el colector le pregunta al panel."""

    def __init__(self, leaders=()):
        self._service_leader_store = _Arriendos(list(leaders))


def _fila(**kw):
    base = {'id': 'x', 'kind': 'k', 'label': 'Algo', 'enabled': True, 'every': 600,
            'lease': 'llave'}
    base.update(kw)
    return base


class TestUnaFilaDiceLaVerdad:

    def test_lo_que_falta_no_se_inventa(self):
        r = T.normalise('paq', {'id': 'x'}, {}, now=1000.0)
        assert r['every'] == 0 and r['last_run'] == 0.0
        assert r['next_run'] == 0.0, 'inventó una próxima vuelta sin saber cada cuánto'
        assert r['overdue'] is False

    def test_el_id_lleva_el_paquete_delante(self):
        """Dos paquetes pueden llamar `scan` a lo suyo. Sin el prefijo, la pantalla pintaría
        una fila sobre la otra."""
        assert T.normalise('salud', {'id': 'scan'}, {}, now=0)['id'] == 'salud:scan'

    def test_apagado_no_es_lo_mismo_que_dormido(self):
        r = T.normalise('p', _fila(enabled=False, every=60), {}, now=1000.0)
        assert r['enabled'] is False
        assert r['next_run'] == 0.0, 'un temporizador apagado no tiene próxima vuelta'


class TestCuandoCorrioSaleDelArriendo:
    """El arriendo se renueva en cada vuelta del que lo sostiene, así que es el único «cuándo
    corrió» que se ve desde **otro contenedor**."""

    def test_manda_sobre_lo_que_diga_el_paquete(self):
        lideres = {'llave': {'instance_id': 'web-2', 'host': 'pod-b',
                             'expires_at': 9e9, 'renewed_at': 5000.0}}
        r = T.normalise('p', _fila(last_run=111.0), lideres, now=5100.0)
        assert r['last_run'] == 5000.0, 'se creyó la memoria de este proceso'
        assert r['next_run'] == 5600.0

    def test_y_si_no_hay_arriendo_vale_lo_que_el_paquete_recuerde(self):
        r = T.normalise('p', _fila(lease='', last_run=4000.0), {}, now=4100.0)
        assert r['last_run'] == 4000.0

    def test_una_replica_que_no_es_la_lider_ve_la_vuelta_del_que_si(self):
        """Es el caso de verdad: tres réplicas, una explora. Las otras dos tienen que enseñar
        lo mismo que ella y no un «no ha corrido nunca»."""
        lideres = {'llave': {'instance_id': 'web-1', 'host': 'pod-a',
                             'expires_at': 9e9, 'renewed_at': 7000.0}}
        r = T.normalise('p', _fila(), lideres, now=7050.0)     # sin `last_run` propio
        assert r['last_run'] == 7000.0
        assert r['host'] == 'pod-a'


class TestSinArriendoNoEsSinDueno:

    def test_sin_arriendo_corre_en_todas(self):
        """`None` y no cadena vacía: la pantalla los pinta distinto, y confundirlos borra la
        única diferencia que importa."""
        r = T.normalise('p', _fila(lease=''), {}, now=0)
        assert r['holder'] is None and r['host'] is None and r['expires'] is None

    def test_con_arriendo_y_sin_dueno_no_corre_en_ninguna(self):
        r = T.normalise('p', _fila(lease='llave'), {}, now=0)
        assert r['holder'] == '' and r['holder'] is not None

    def test_el_resumen_cuenta_los_que_corren_en_todas(self):
        filas = [T.normalise('p', _fila(id='a', lease=''), {}, now=0),
                 T.normalise('p', _fila(id='b', lease='k'), {}, now=0),
                 T.normalise('p', _fila(id='c', lease='', enabled=False), {}, now=0)]
        s = T.summary(filas)
        assert s['total'] == 3 and s['enabled'] == 2
        assert s['unleased'] == 1, 'contó también el que está apagado'


class TestAtrasado:

    def test_lo_esta_cuando_lleva_mas_de_lo_debido(self):
        lideres = {'llave': {'instance_id': 'i', 'host': 'h', 'expires_at': 9e9,
                             'renewed_at': 1000.0}}
        r = T.normalise('p', _fila(every=600), lideres, now=1000.0 + 600 + 400)
        assert r['overdue'] is True

    def test_y_no_lo_esta_por_un_poco_de_retraso(self):
        """Media vuelta de margen: un hilo que duerme 600 s no despierta a los 600 exactos, y
        una lista que se pone ámbar por dos segundos de deriva se ignora en una semana."""
        lideres = {'llave': {'instance_id': 'i', 'host': 'h', 'expires_at': 9e9,
                             'renewed_at': 1000.0}}
        r = T.normalise('p', _fila(every=600), lideres, now=1000.0 + 600 + 60)
        assert r['overdue'] is False

    def test_uno_apagado_nunca_esta_atrasado(self):
        lideres = {'llave': {'instance_id': 'i', 'host': 'h', 'expires_at': 9e9,
                             'renewed_at': 1000.0}}
        r = T.normalise('p', _fila(every=60, enabled=False), lideres, now=9e8)
        assert r['overdue'] is False


class TestElOrden:

    def test_primero_lo_atrasado_luego_lo_encendido_luego_lo_apagado(self):
        def _r(label, **kw):
            return dict(T.normalise('p', _fila(id=label, label=label, **kw), {}, now=0))
        filas = [_r('b'), _r('a', enabled=False), _r('c')]
        filas[2]['overdue'] = True
        assert [r['label'] for r in T.ordered(filas)] == ['c', 'b', 'a']

    def test_dentro_de_un_grupo_por_nombre_y_no_por_la_hora(self):
        """Esta lista se lee buscando algo concreto. Un orden que cambia en cada refresco
        obliga a releerla entera."""
        filas = [T.normalise('p', _fila(id=x, label=x), {}, now=0) for x in ('c', 'a', 'b')]
        assert [r['label'] for r in T.ordered(filas)] == ['a', 'b', 'c']


class TestSeDeclaraNoSeNombra:

    def test_el_colector_no_nombra_ningun_paquete(self):
        """Un núcleo que importara cinco planificadores por su nombre es un núcleo que hay que
        editar para enterarse del sexto. Es la misma regla que ya cumple la lista de trabajos."""
        import ast                                                   # noqa: PLC0415
        import io as _io                                             # noqa: PLC0415
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        arbol = ast.parse(_io.open(os.path.join(src, 'lib', 'core', 'jobs', 'timers.py'),
                                   encoding='utf-8').read())
        importados = {n.module or '' for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)}
        for m in importados:
            assert not m.startswith('lib.core.health'), m
            assert not m.startswith('lib.core.backup'), m
        assert 'lib.discovery' in importados, 'dejó de recogerlo por descubrimiento'

    def test_un_paquete_que_revienta_no_se_lleva_la_lista(self):
        """Tres de cuatro vale más que ninguno de cuatro — la misma regla que la lista de
        trabajos, y por el mismo motivo."""
        def _explota(_wa):
            raise RuntimeError('roto')

        def _bien(_wa):
            return [_fila(id='vivo', label='Vivo')]

        original = T.scan
        T.scan = lambda _d: [('malo', _explota), ('bueno', _bien)]
        try:
            filas = T.live(_Wa())
        finally:
            T.scan = original
        assert [r['label'] for r in filas] == ['Vivo']

    def test_el_colector_le_pide_a_la_tienda_lo_que_de_verdad_usa(self):
        """Si el doble tuviera el método que el colector ya no llama, todo esto pasaría por el
        `except` y estaría verde sin comprobar nada."""
        pedidos = []

        class _Espia:
            def leases(self):
                pedidos.append('leases')
                return [{'service_key': 'llave', 'instance_id': 'i', 'host': 'h',
                         'expires_at': 9e9, 'renewed_at': 4242.0, 'live': True}]

        wa = _Wa()
        wa._service_leader_store = _Espia()
        original = T.scan
        T.scan = lambda _d: [('p', lambda _w: [_fila()])]
        try:
            filas = T.live(wa, now=4300.0)
        finally:
            T.scan = original
        assert pedidos == ['leases'], 'el colector no preguntó por los arriendos'
        assert filas[0]['last_run'] == 4242.0

    def test_y_lo_que_no_es_un_diccionario_se_ignora(self):
        original = T.scan
        T.scan = lambda _d: [('raro', lambda _wa: ['una cadena', None, _fila(label='Bien')])]
        try:
            filas = T.live(_Wa())
        finally:
            T.scan = original
        assert [r['label'] for r in filas] == ['Bien']


class TestLoQueLaPantallaEnsenoMal:
    """Cuatro cosas que sólo se vieron mirando la pantalla, no leyendo el código."""

    def test_un_cron_que_corre_no_esta_apagado(self):
        """El hilo despierta cada treinta segundos y está vivo; lo único apagado es lo que hace
        al despertar. «Detenido» tiene que significar que no corre, o manda a alguien a buscar
        un proceso muerto que está perfectamente vivo."""
        r = T.normalise('p', _fila(enabled=False), {}, now=0)
        assert r['state'] == T.IDLE
        assert r['state'] != T.STOPPED
        assert r['scheduled'] is True

    def test_y_uno_que_no_esta_montado_si(self):
        r = T.normalise('p', _fila(scheduled=False), {}, now=0)
        assert r['state'] == T.STOPPED

    def test_un_arriendo_caducado_sigue_diciendo_cuando_corrio(self):
        """Es el caso NORMAL y no la excepción: un escaneo diario con arriendo de una hora lo
        tiene expirado el 96 % del tiempo. Filtrarlo dejaba la pantalla diciendo «todavía no ha
        corrido nunca» sobre algo que corrió esta mañana."""
        caducado = {'llave': {'instance_id': 'i', 'host': 'pod-a', 'expires_at': 100.0,
                              'renewed_at': 90.0, 'live': False}}
        r = T.normalise('p', _fila(every=86400), caducado, now=50000.0)
        assert r['last_run'] == 90.0, 'tiró el dato por estar caducado el arriendo'
        assert r['host'] == 'pod-a'
        assert r['holding'] is False, 'dice que lo sostiene y hace horas que caducó'

    def test_y_uno_vivo_se_distingue_del_caducado(self):
        vivo = {'llave': {'instance_id': 'i', 'host': 'pod-b', 'expires_at': 9e9,
                          'renewed_at': 90.0, 'live': True}}
        assert T.normalise('p', _fila(), vivo, now=100.0)['holding'] is True

    def test_uno_sin_efecto_no_sale_atrasado_para_siempre(self):
        """Su trabajo está desactivado, así que no llega a tomar el arriendo y su última vuelta
        se queda quieta. Sin esta regla saldría en ámbar el resto de la vida del panel."""
        viejo = {'llave': {'instance_id': 'i', 'host': 'h', 'expires_at': 1.0,
                           'renewed_at': 1.0, 'live': False}}
        r = T.normalise('p', _fila(enabled=False, every=60), viejo, now=9e8)
        assert r['overdue'] is False

    def test_el_resumen_separa_los_que_hacen_algo_de_los_que_no(self):
        filas = [T.normalise('p', _fila(id='a'), {}, now=0),
                 T.normalise('p', _fila(id='b', enabled=False), {}, now=0),
                 T.normalise('p', _fila(id='c', scheduled=False), {}, now=0)]
        s = T.summary(filas)
        assert (s['total'], s['enabled'], s['idle']) == (3, 1, 1)


class TestLaClaveDelAjusteNoEsUnTextoParaLeer:
    """Reportado desde la pantalla: «¿esto "certs|notify_expiry" no se tendría que reemplazar?».

    Un temporizador declara **la clave** del ajuste que lo enciende, que es lo correcto: es lo
    que se lee de la configuración y lo único estable entre idiomas. Pero enseñar la clave es
    enseñar la tubería, y lo peor no es que sea fea: es que tampoco dice **dónde** ir a
    encenderlo, porque en Configuración ese campo se llama por su etiqueta y no por su clave.
    """

    def test_la_clave_se_cambia_por_como_se_llama_el_campo_en_configuracion(self):
        assert T.setting_label('es_ES', 'certs|notify_expiry') ==             'Avisar por caducidad de certificados'
        assert T.setting_label('en_EN', 'certs|notify_expiry') == 'Notify on cert expiry'

    def test_y_cada_ajuste_que_declara_un_temporizador_tiene_el_suyo(self):
        """La lista sale de los paquetes, así que un temporizador nuevo puede traer una clave
        sin etiqueta: saldría cruda en la pantalla, y nadie lo vería hasta abrirla."""
        for clave in ('certs|notify_expiry', 'dcim|notify_cabling', 'services|notify_down',
                      'oidc|secret_notify_expiry'):
            for lang in ('es_ES', 'en_EN'):
                assert T.setting_label(lang, clave), f'{clave} sin etiqueta en {lang}'

    def test_un_idioma_sin_la_palabra_cae_al_de_por_defecto(self):
        """Media traducción es lo normal en un fichero de idioma que crece; una celda vacía en
        la tabla, no."""
        assert T.setting_label('xx_XX', 'certs|notify_expiry') == 'Notify on cert expiry'

    def test_y_una_clave_que_nadie_ha_traducido_no_inventa_nada(self):
        assert T.setting_label('es_ES', 'inventado|jamas') == ''
        assert T.setting_label('es_ES', '') == ''

    def test_lo_que_no_se_enciende_en_configuracion_lo_dice_el_paquete(self):
        """Una copia programada es una **tarea** de la pantalla de Copias, no una casilla de la
        configuración: «se enciende en Configuración → …» ahí sería mandar a alguien al sitio
        equivocado. El paquete trae su propio texto y el colector lo respeta."""
        r = T.normalise('backup', _fila(setting='backup|schedule',
                                        setting_label='Copias → una tarea'), {}, now=0)
        assert r['setting_label'] == 'Copias → una tarea'
        assert T.normalise('p', _fila(), {}, now=0)['setting_label'] == ''


class TestElPaqueteSabeMejorCuandoLeToca:
    """Reportado desde la pantalla: «Copias programadas» en ámbar con «Atrasado 41 min»,
    mientras la pantalla de al lado enseñaba tres copias recién hechas.

    La lista calcula «última vuelta + cada cuánto». Para casi todos es la verdad: despiertan,
    hacen su vuelta y renuevan el arriendo. El de las copias toma el arriendo **sólo cuando hay
    trabajo**, así que su marca es «cuándo se copió» y no «cuándo despertó el hilo» — y sumarle
    el tic de diez minutos da un instante sin significado que, con una programación horaria o
    diaria, queda siempre en el pasado.
    """

    def test_lo_declarado_gana_a_la_suma(self):
        r = T.normalise('backup', _fila(every=600, next_run=5000.0), {}, now=1000.0)
        assert r['next_run'] == 5000.0

    def test_y_con_ello_deja_de_salir_atrasado(self):
        """El caso de la captura: el arriendo dice que se copió hace 51 minutos, el tic son 10,
        y la próxima copia es dentro de 9. Sin lo declarado salía «atrasado 41 min»."""
        ahora = 100000.0
        arriendo = {'llave': {'instance_id': 'i', 'host': 'MORIA', 'expires_at': 9e9,
                              'renewed_at': ahora - 51 * 60, 'live': True}}
        sin = T.normalise('backup', _fila(every=600), arriendo, now=ahora)
        assert sin['overdue'] is True, 'sin esto la pantalla no habría mentido'
        con = T.normalise('backup', _fila(every=600, next_run=ahora + 9 * 60),
                          arriendo, now=ahora)
        assert con['overdue'] is False
        assert con['next_run'] == ahora + 9 * 60

    def test_pero_lo_declarado_tambien_puede_estar_atrasado(self):
        """Si la próxima copia ya pasó y no se ha hecho, eso **sí** es noticia — que es para lo
        que sirve la columna."""
        ahora = 100000.0
        r = T.normalise('backup', _fila(every=600, next_run=ahora - 3600), {}, now=ahora)
        assert r['overdue'] is True

    def test_y_sin_declarar_nada_se_sigue_sumando(self):
        """Los otros cuatro temporizadores no declaran nada, y su cuenta no cambia."""
        arriendo = {'llave': {'instance_id': 'i', 'host': 'h', 'expires_at': 9e9,
                              'renewed_at': 900.0, 'live': True}}
        r = T.normalise('p', _fila(every=600), arriendo, now=1000.0)
        assert r['next_run'] == 1500.0


class TestCuantoRetrasoEsNormal:
    """Reportado con la carpeta de copias delante: a la 01:33 la copia que tocaba a la 01:13
    seguía sin hacerse, y la pantalla decía «ahora» sin una sola marca de alarma.

    La regla de siempre —medio periodo— es buena para un temporizador que se despierta y hace
    su vuelta. Deja de serlo cuando la vuelta la decide otro reloj: el de las copias comprueba
    cada diez minutos, así que a los once ya se sabe. Con media hora de margen sobre una copia
    horaria, la pantalla se callaba veinte minutos justo cuando había algo que decir.
    """

    def test_el_paquete_puede_decir_con_que_precision_cumple(self):
        ahora = 100000.0
        # Veinte minutos tarde sobre una copia horaria: con la regla de siempre, silencio.
        vieja = T.normalise('p', _fila(every=3600, next_run=ahora - 20 * 60), {}, now=ahora)
        assert vieja['overdue'] is False, 'sin esto no habría nada que arreglar'
        con = T.normalise('backup', _fila(every=3600, next_run=ahora - 20 * 60, slack=600),
                          {}, now=ahora)
        assert con['overdue'] is True

    def test_pero_un_retraso_que_cabe_en_una_vuelta_no_es_noticia(self):
        """Que una copia se haga a y veinte en vez de a y cuarto es cómo funciona, no un
        fallo: marcarlo en ámbar cada hora enseña a no mirar el ámbar."""
        ahora = 100000.0
        r = T.normalise('backup', _fila(every=3600, next_run=ahora - 5 * 60, slack=600),
                        {}, now=ahora)
        assert r['overdue'] is False

    def test_y_quien_no_lo_diga_sigue_con_la_regla_de_siempre(self):
        ahora = 100000.0
        r = T.normalise('p', _fila(every=3600, next_run=ahora - 31 * 60), {}, now=ahora)
        assert r['overdue'] is True
        r = T.normalise('p', _fila(every=3600, next_run=ahora - 29 * 60), {}, now=ahora)
        assert r['overdue'] is False
