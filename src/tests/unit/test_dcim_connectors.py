#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El catálogo de conectores: por dónde se enchufa cada cosa, con un nombre que se reconoce.

`iec-60320-c14` es lo que dice la biblioteca y no es lo que nadie dice en una sala. `c19` y `c20`
se distinguen en un carácter y son el macho y la hembra de otra cosa —veinte amperios en vez de
diez—, y confundirlos es pedir el latiguillo que no entra.

Lo que se prueba aquí es lo que hace útil el documento: que ofrezca en cada familia lo que puede
ir en ella, que no invente velocidades, y que **no tumbe la sección** si alguien lo rompe — porque
lo que se teclee se sigue guardando con catálogo o sin él.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.core.dcim import connectors                                 # noqa: E402


@pytest.fixture(autouse=True)
def _fresco():
    """El documento se cachea por proceso: cada prueba parte de leerlo."""
    connectors._CACHE = None                    # noqa: SLF001
    connectors._SEEN = ()                       # noqa: SLF001
    yield
    connectors._CACHE = None                    # noqa: SLF001
    connectors._SEEN = ()                       # noqa: SLF001


class TestElDocumento:

    def test_existe_y_trae_conectores(self):
        assert connectors.count() > 50

    def test_es_json_valido_y_con_version(self):
        with open(connectors.FILE, encoding='utf-8') as fh:
            doc = json.load(fh)
        assert int(doc.get('version') or 0) >= 1

    def test_ningun_identificador_repetido(self):
        """Dos filas con el mismo `id` son dos nombres para el mismo conector, y gana el que
        pille el bucle — que es como el mismo puerto se lee distinto en dos pantallas."""
        ids = [c['id'] for c in connectors.all()]
        assert len(ids) == len(set(ids))

    def test_todos_dicen_donde_van(self):
        """Un conector sin familia no se ofrece en ninguna casilla: está escrito y no existe."""
        assert all(c['families'] for c in connectors.all())

    def test_los_grupos_son_los_declarados(self):
        assert {c['group'] for c in connectors.all()} <= set(connectors.GROUPS)

    def test_todos_traen_su_forma(self):
        """Un conector sin dibujo al lado de otros que lo tienen se lee como que le falta algo.
        Que la forma que nombra esté dibujada lo comprueba `tests/meta`, que es donde vive el
        `<svg>`."""
        assert all(c['shape'] for c in connectors.all())

    def test_una_forma_por_CARA_y_no_por_conector(self):
        """No hay ciento veintiocho caras distintas: una C13 y una C15 son la misma boca con
        distinto aguante de temperatura, y un LC/APC y un LC/UPC se distinguen por el color del
        pulido. Ciento veintiocho dibujos serían ciento veintiocho ocasiones de dejarse uno."""
        por_id = {c['id']: c['shape'] for c in connectors.all()}
        assert por_id['iec-60320-c13'] == por_id['iec-60320-c15']
        assert por_id['lc-apc'] == por_id['lc-upc']
        # Y las que se confunden, distinta: diez amperios y veinte no son lo mismo.
        assert por_id['iec-60320-c13'] != por_id['iec-60320-c19']

    def test_sin_forma_en_el_documento_sale_la_generica(self, monkeypatch, tmp_path):
        doc = tmp_path / 'sin.json'
        doc.write_text(json.dumps({'connectors': [{'id': 'x', 'families': ['interfaces']}]}),
                       encoding='utf-8')
        monkeypatch.setattr(connectors, 'FILE', str(doc))
        assert connectors.all()[0]['shape'] == 'other'


class TestLoQueLoHaceUtil:

    def test_cada_familia_ofrece_lo_suyo(self):
        """Una C14 es una toma de entrada y nunca una boca de red: ofrecer las cien en las nueve
        familias sería no haber ordenado nada."""
        fams = connectors.by_family()
        assert 'iec-60320-c14' in [c['id'] for c in fams['power-ports']]
        assert 'iec-60320-c14' not in [c['id'] for c in fams['interfaces']]
        assert 'iec-60320-c19' in [c['id'] for c in fams['power-outlets']]

    def test_estan_los_que_se_pidieron(self):
        ids = {c['id'] for c in connectors.all()}
        assert {'usb-c', 'usb-a', 'displayport', 'iec-60320-c20', 'iec-60320-c19',
                'dc-terminal'} <= ids

    def test_un_conector_puede_ir_en_varias_familias(self):
        """Una `usb-c` es una toma de entrada en un mini-PC y un puerto de consola en un switch,
        y es el mismo conector. Repetirlo serían dos filas que se separan."""
        usb = [c for c in connectors.all() if c['id'] == 'usb-c'][0]
        assert len(usb['families']) > 1

    def test_solo_dice_la_velocidad_donde_el_conector_la_fija(self):
        """Un RJ-45 no dice a cuánto va y una `10gbase-t` sí: inventarle una al primero sería
        afirmar algo que el conector no dice."""
        por_id = {c['id']: c for c in connectors.all()}
        assert por_id['10gbase-t']['speed'] == '10 Gbps'
        assert 'speed' not in por_id['rj-45']
        assert 'speed' not in por_id['iec-60320-c19']

    def test_el_nombre_se_lee_en_el_idioma_que_se_pida(self):
        assert connectors.name('dc-terminal', 'es_ES') == 'Entrada de continua'
        assert connectors.name('dc-terminal', 'en_EN') == 'DC input'
        # Lo que no hace falta traducir viene como cadena y vale para los dos.
        assert connectors.name('usb-c', 'en_EN') == 'USB-C'

    def test_lo_que_no_esta_no_se_inventa(self):
        """Vacío y no el identificador: quien llama decide qué enseñar cuando no se reconoce, y
        lo que se enseña es lo que alguien tecleó."""
        assert connectors.name('conector-raro-de-la-sala') == ''
        assert connectors.name('') == ''

    def test_en_el_orden_del_documento(self):
        """Están escritos de menos a más raro dentro de cada familia, y eso hace que la primera
        opción de la lista sea casi siempre la buena. Ordenar pondría delante lo de la `b`."""
        ids = [c['id'] for c in connectors.by_family()['power-ports']]
        assert ids.index('iec-60320-c14') < ids.index('saf-d-grid')


class TestUnoRotoNoTumbaLaSeccion:

    def test_sin_fichero_salen_cero(self, monkeypatch, tmp_path):
        """Cero conectores es un formulario más pobre y no un formulario que no abre: lo que se
        teclee se sigue guardando."""
        monkeypatch.setattr(connectors, 'FILE', str(tmp_path / 'no-esta.json'))
        assert connectors.all() == [] and connectors.by_family() == {}

    def test_con_basura_dentro_tampoco(self, monkeypatch, tmp_path):
        roto = tmp_path / 'roto.json'
        roto.write_text('{esto no es json', encoding='utf-8')
        monkeypatch.setattr(connectors, 'FILE', str(roto))
        assert connectors.all() == []

    def test_una_fila_sin_id_se_ignora_y_las_demas_no(self, monkeypatch, tmp_path):
        doc = tmp_path / 'medio.json'
        doc.write_text(json.dumps({'connectors': [{'name': 'sin id'},
                                                  {'id': 'usb-c', 'families': ['power-ports']}]}),
                       encoding='utf-8')
        monkeypatch.setattr(connectors, 'FILE', str(doc))
        assert [c['id'] for c in connectors.all()] == ['usb-c']

    def test_se_relee_cuando_cambia(self, monkeypatch, tmp_path):
        """Guardarlo para siempre en memoria convierte «editar un JSON» en «editar un JSON y
        reiniciar», con la trampa de que lo segundo no está escrito en ninguna parte."""
        doc = tmp_path / 'vivo.json'
        doc.write_text(json.dumps({'connectors': [{'id': 'a', 'families': ['interfaces']}]}),
                       encoding='utf-8')
        monkeypatch.setattr(connectors, 'FILE', str(doc))
        assert [c['id'] for c in connectors.all()] == ['a']
        doc.write_text(json.dumps({'connectors': [{'id': 'a', 'families': ['interfaces']},
                                                  {'id': 'b', 'families': ['interfaces']}]}),
                       encoding='utf-8')
        os.utime(doc, (0, 0))                   # otra fecha, para no depender del reloj
        assert [c['id'] for c in connectors.all()] == ['a', 'b']


class TestSePuedeSustituirSinPublicarUnaVersion:
    """Dos documentos y gana el más nuevo, como los perfiles.

    Editar un fichero del disco no vale en un despliegue con contenedor web y contenedor de
    trabajos —comparten la base y no el disco—, ni sobrevive a una actualización, ni viaja en la
    copia de seguridad. Y el número de versión es lo que evita elegir entre que una lista
    mejorada no llegue a quien añadió un conector, o que el conector añadido desaparezca.
    """

    @pytest.fixture()
    def store(self):
        from lib.core.dcim.profiles import ProfileStore
        from lib.db import get_connector
        db = get_connector({'type': 'sqlite', 'path': ':memory:'})
        yield ProfileStore(db, norm=connectors.normalise, scope=connectors.SCOPE)
        try:
            db.close()
        except Exception:                       # pylint: disable=broad-except
            pass

    def test_sin_nada_guardado_manda_el_que_viene(self, store):
        assert connectors.effective(store) == connectors.packaged()

    def test_uno_mas_nuevo_gana(self, store):
        dentro = int(connectors.packaged().get('version') or 0)
        store.save({'version': dentro + 1,
                    'connectors': [{'id': 'mio', 'families': ['interfaces']}]},
                   name=connectors.NAME)
        assert [c['id'] for c in connectors.all(store=store)] == ['mio']

    def test_uno_mas_viejo_no(self, store):
        """Una actualización que publique la 2 supera a un parche local que iba por la 1."""
        store.save({'version': 1, 'connectors': [{'id': 'mio', 'families': ['interfaces']}]},
                   name=connectors.NAME)
        dentro = int(connectors.packaged().get('version') or 0)
        if dentro <= 1:
            pytest.skip('el que viene con el panel todavía va por la 1')
        assert 'mio' not in [c['id'] for c in connectors.all(store=store)]

    def test_sin_version_no_se_guarda(self, store):
        """Es lo único que decide cuál de los dos manda: uno sin ella sería uno que nunca se usa
        y que nadie entiende por qué no se usa."""
        assert store.save({'connectors': [{'id': 'x', 'families': ['interfaces']}]},
                          name=connectors.NAME) == 0

    def test_volver_atras_devuelve_el_que_viene(self, store):
        store.save({'version': 999, 'connectors': [{'id': 'mio', 'families': ['interfaces']}]},
                   name=connectors.NAME)
        assert store.delete(connectors.NAME) is True
        assert connectors.effective(store) == connectors.packaged()

    def test_cada_guardado_deja_version(self, store):
        """De aquí sale lo que se ofrece al decir por dónde se enchufa algo, así que «¿esto quién
        lo cambió?» es la pregunta del mes siguiente."""
        store.save({'version': 900, 'connectors': [{'id': 'a', 'families': ['interfaces']}]},
                   name=connectors.NAME, actor='ana')
        store.save({'version': 901, 'connectors': [{'id': 'b', 'families': ['interfaces']}]},
                   name=connectors.NAME, actor='luis')
        hist = store.revs.history(connectors.NAME, scope=connectors.SCOPE)
        assert [h['by'] for h in hist] == ['luis', 'ana']

    def test_su_historial_no_se_mezcla_con_el_de_los_perfiles(self, store):
        """Misma tabla y `scope` distinto: son dos documentos y uno no puede enseñar las
        versiones del otro."""
        store.save({'version': 900, 'connectors': []}, name=connectors.NAME)
        from lib.core.dcim import profiles
        assert store.revs.history(connectors.NAME, scope=profiles.SCOPE) == []


class TestLoQueSeDescartaSeDice:
    """Un JSON con una familia mal escrita se guardaría igual, no saldría en ninguna casilla, y
    quien lo escribió creería que funcionó. Eso es peor que rechazarlo."""

    def test_una_familia_que_ninguna_pantalla_dibuja_se_tira(self):
        limpio = connectors.normalise({'version': 1, 'connectors': [
            {'id': 'a', 'families': ['interfaces']},
            {'id': 'b', 'families': ['inventada']}]})
        assert [c['id'] for c in limpio['connectors']] == ['a']
        assert any('b' in p for p in connectors.problems(
            {'connectors': [{'id': 'b', 'families': ['inventada']}]}))

    def test_repetido_no_entra_dos_veces(self):
        """Gana el que pille el bucle, que es como el mismo conector se lee distinto en dos
        pantallas según por dónde se recorriera la lista."""
        limpio = connectors.normalise({'version': 1, 'connectors': [
            {'id': 'a', 'families': ['interfaces'], 'name': 'uno'},
            {'id': 'a', 'families': ['interfaces'], 'name': 'otro'}]})
        assert len(limpio['connectors']) == 1
        assert any('repeated' in p for p in connectors.problems(
            {'connectors': [{'id': 'a', 'families': ['interfaces']},
                            {'id': 'a', 'families': ['interfaces']}]}))

    def test_un_grupo_inventado_cae_en_otro_y_no_se_pierde_la_fila(self):
        """Perder el conector por no reconocer su grupo sería tirar el dato por la etiqueta."""
        limpio = connectors.normalise({'version': 1, 'connectors': [
            {'id': 'a', 'families': ['interfaces'], 'group': 'inventado'}]})
        assert limpio['connectors'][0]['group'] == 'other'

    def test_el_nombre_en_dos_idiomas_sobrevive(self):
        limpio = connectors.normalise({'version': 1, 'connectors': [
            {'id': 'a', 'families': ['interfaces'],
             'name': {'es_ES': 'Uno', 'en_EN': 'One'}}]})
        assert limpio['connectors'][0]['name'] == {'es_ES': 'Uno', 'en_EN': 'One'}

    def test_el_documento_que_viene_pasa_su_propia_limpieza(self):
        """También se lee el que viene dentro: una comprobación que solo corre al guardar no
        protege del fichero que llega por la otra puerta."""
        assert connectors.problems(connectors.packaged()) == []


class TestLaGeneracionYLoQueLleva:
    """`usb-c` es una FORMA y no dice nada más.

    Un USB 2.0 y un 3.2 Gen 2 son la misma boca con veinte veces la velocidad, y el mismo cable
    saca vídeo, red y corriente. Un conector por combinación serían cientos; el conector dice qué
    CABE en esa forma y el puerto dice cuál de ellas es la suya.
    """

    def test_las_generaciones_se_guardan_en_su_orden(self):
        """De la más vieja a la más nueva, que es como se lee un desplegable sin buscar."""
        limpio = connectors.normalise({'version': 2, 'connectors': [
            {'id': 'usb-c', 'families': ['rear-ports'], 'gens': [
                {'id': 'usb2', 'name': 'USB 2.0', 'speed': '480 Mbps'},
                {'id': 'usb4', 'name': 'USB4', 'speed': '40 Gbps'}]}]})
        gens = limpio['connectors'][0]['gens']
        assert [g['id'] for g in gens] == ['usb2', 'usb4']
        assert gens[0]['speed'] == '480 Mbps'

    def test_una_generacion_sin_id_no_entra_y_se_dice(self):
        """El `id` es lo que guarda el puerto: una fila que solo tiene nombre no se puede volver
        a encontrar cuando alguien corrija el nombre."""
        doc = {'version': 2, 'connectors': [
            {'id': 'usb-c', 'families': ['rear-ports'],
             'gens': [{'name': 'USB 2.0'}, {'id': 'usb2', 'name': 'USB 2.0'}]}]}
        assert [g['id'] for g in connectors.normalise(doc)['connectors'][0]['gens']] == ['usb2']
        assert any('no id' in p for p in connectors.problems(doc))

    def test_una_generacion_repetida_se_queda_en_una(self):
        limpio = connectors.normalise({'version': 2, 'connectors': [
            {'id': 'usb-c', 'families': ['rear-ports'],
             'gens': [{'id': 'usb2', 'name': 'uno'}, {'id': 'usb2', 'name': 'otro'}]}]})
        assert len(limpio['connectors'][0]['gens']) == 1

    def test_hay_tope_de_generaciones(self):
        """Lo que sobra de un documento raro son renglones que nadie lee en un desplegable."""
        gens = [{'id': f'g{i}'} for i in range(connectors.GENS_MAX + 20)]
        limpio = connectors.normalise({'version': 2, 'connectors': [
            {'id': 'usb-c', 'families': ['rear-ports'], 'gens': gens}]})
        assert len(limpio['connectors'][0]['gens']) == connectors.GENS_MAX

    def test_el_vocabulario_de_senales_se_guarda(self):
        limpio = connectors.normalise({'version': 2, 'signals': [
            {'id': 'data', 'name': {'es_ES': 'Datos', 'en_EN': 'Data'}},
            {'id': 'data', 'name': 'repetida'},
            {'name': 'sin id'}], 'connectors': []})
        assert [s['id'] for s in limpio['signals']] == ['data']
        assert limpio['signals'][0]['name']['en_EN'] == 'Data'

    def test_una_senal_fuera_del_vocabulario_se_conserva_y_se_dice(self):
        """Abierto a propósito: perder el dato por no reconocerlo es peor que guardarlo tal cual.
        Pero casi siempre es una errata, y una errata que funciona es la que se queda."""
        doc = {'version': 2, 'signals': [{'id': 'data'}], 'connectors': [
            {'id': 'usb-c', 'families': ['rear-ports'], 'signals': ['data', 'inventada']}]}
        assert connectors.normalise(doc)['connectors'][0]['signals'] == ['data', 'inventada']
        assert any('inventada' in p for p in connectors.problems(doc))

    def test_las_senales_repetidas_no_se_cuentan_dos_veces(self):
        limpio = connectors.normalise({'version': 2, 'connectors': [
            {'id': 'usb-c', 'families': ['rear-ports'],
             'signals': ['data', 'data', '', 'dp']}]})
        assert limpio['connectors'][0]['signals'] == ['data', 'dp']

    def test_lo_que_llega_a_la_pantalla_trae_las_dos_cosas(self):
        """`all()` es lo que ve el navegador: lo que no se copie ahí no da error, da un hueco."""
        fila = {c['id']: c for c in connectors.all('es_ES')}['usb-c']
        assert any(g['id'] == 'usb3.2g2' for g in fila['gens'])
        assert 'dp' in fila['signals']

    def test_el_vocabulario_llega_con_su_nombre(self):
        """Un identificador suelto no se lee: `power-out` donde alguien quiere leer «alimenta»."""
        voc = {s['id']: s['name'] for s in connectors.signals('es_ES')}
        assert voc['power-out'] == 'Alimenta'
        assert {s['id']: s['name'] for s in connectors.signals('en_EN')}['power-out'] \
            == 'Supplies power'

    def test_el_documento_que_viene_declara_las_del_usb(self):
        """La forma que motivó todo esto: un USB-C tiene generaciones y lleva varias cosas."""
        usb = {c['id']: c for c in connectors.packaged()['connectors']}['usb-c']
        assert len(usb['gens']) >= 6
        assert 'thunderbolt' in usb['signals']


class _Store:
    """Un almacén de mentira: lo único que `effective` le pide es el documento guardado."""

    def __init__(self, body):
        self._body = body

    def get(self, name=''):
        return {'body': self._body}


class TestLaFotoDeUnConector:
    """Los ciento y pico que vienen con el panel llevan dibujo —uno por FORMA, porque una C13 y
    una C15 son la misma boca— y al que alguien añada no se le parece ninguno: nadie va a
    escribir un SVG para la regleta de su rack. Puede traer una foto en su lugar.

    Lo que se guarda es un NOMBRE del almacén de medios, comprobado con la regla de ese almacén
    y no con una copia de ella: un nombre que no acuñó él no es un fichero de este disco, y
    aceptarlo aquí sería dejar que un documento decida qué ruta se lee después — que es
    exactamente la forma que tenía el fallo del catálogo de MIB.
    """

    #: Un nombre de los que acuña el almacén, con su subcarpeta.
    BUENO = 'own/abcd1234-1111-2222-3333-444455556666.png'

    def _doc(self, **extra):
        c = {'id': 'regleta', 'families': ['power-outlets']}
        c.update(extra)
        return {'version': 1, 'connectors': [c]}

    def test_un_nombre_del_almacen_se_queda(self):
        fila = connectors.normalise(self._doc(image=self.BUENO))['connectors'][0]
        assert fila['image'] == self.BUENO

    def test_y_una_ruta_no(self):
        """`../../etc/passwd` no es un nombre: es una ruta, y la única defensa que funciona es
        que no pueda llegar a construirse una."""
        for malo in ('../../etc/passwd', 'own/x.png', '/tmp/foto.png', 'foto.exe'):
            fila = connectors.normalise(self._doc(image=malo))['connectors'][0]
            assert 'image' not in fila, malo

    def test_lo_que_se_tira_se_dice(self):
        """Descartarla en silencio deja el conector con el dibujo genérico, que se lee como «no
        tiene foto» y no como «la que pusiste no vale»."""
        assert any('image' in p for p in connectors.problems(self._doc(image='../x.png')))
        assert not connectors.problems(self._doc(image=self.BUENO))

    def test_llega_a_la_pantalla(self):
        """Guardada y no servida es una foto que no se ve, que es lo mismo que no tenerla."""
        # Con versión que GANE a la del panel: si no, el efectivo es el de dentro y lo que se
        # estaría comprobando es que el fichero del repositorio no trae fotos.
        doc = self._doc(image=self.BUENO)
        doc['version'] = connectors.next_version()
        filas = connectors.all('es_ES', _Store(doc))
        assert filas[0]['image'] == self.BUENO


class TestPonerlaYQuitarla:
    """`with_image` escribe en UN conector del documento y devuelve la que había: hay que
    borrarla del disco, y sólo quien sustituye sabe cuál era."""

    def _doc(self):
        return {'version': 4, 'connectors': [
            {'id': 'a', 'families': ['interfaces'], 'image': 'own/vieja.png'},
            {'id': 'b', 'families': ['interfaces']}]}

    def test_pone_la_nueva_y_devuelve_la_vieja(self):
        doc, vieja = connectors.with_image(self._doc(), 'a', 'own/nueva.png')
        assert vieja == 'own/vieja.png'
        assert doc['connectors'][0]['image'] == 'own/nueva.png'
        # Y no toca al de al lado.
        assert 'image' not in doc['connectors'][1]

    def test_quitarla_borra_la_clave_y_no_la_deja_vacia(self):
        """Un `"image": ""` afirma que ese conector tiene una foto que no se ve."""
        doc, vieja = connectors.with_image(self._doc(), 'a', '')
        assert vieja == 'own/vieja.png' and 'image' not in doc['connectors'][0]

    def test_no_toca_el_documento_que_recibe(self):
        """Escribir sobre el que está en vigor dejaría la memoria de este proceso diciendo algo
        que la base de datos no dice todavía — y si el guardado falla, para siempre."""
        original = self._doc()
        connectors.with_image(original, 'a', 'own/nueva.png')
        assert original['connectors'][0]['image'] == 'own/vieja.png'

    def test_uno_que_no_esta_se_contesta_con_nada(self):
        """Y no creando la fila: guardar la foto de un conector que no existe deja un fichero
        huérfano y una respuesta que dice que fue bien."""
        doc, vieja = connectors.with_image(self._doc(), 'no-existe', 'own/x.png')
        assert doc is None and vieja == ''


class TestLaVersionQueDeVerdadMANDA:
    """Una más que la MAYOR de las dos que compiten, no una más que la guardada.

    Con la del panel por delante —una actualización que publicó la 3 sobre un parche local que
    iba por la 2— sumarle uno a la guardada da otra vez 3, que no gana: el cambio se guarda, se
    dice que sí, y no se aplica.
    """

    def test_supera_a_la_del_panel(self):
        dentro = int(connectors.packaged().get('version') or 0)
        assert connectors.next_version() == dentro + 1
        assert connectors.next_version(_Store({'version': dentro - 1})) == dentro + 1

    def test_y_a_la_guardada_cuando_es_ella_la_que_manda(self):
        dentro = int(connectors.packaged().get('version') or 0)
        assert connectors.next_version(_Store({'version': dentro + 40})) == dentro + 41
