#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las clases de dispositivo, que ahora viven **enteras en la base de datos**.

Eran once escritas en una tupla, y sólo se podían cambiar con un commit: lo que no cabía en
ellas se quedaba «sin clasificar» — un punto de acceso, un teléfono IP, una controladora. Ahora
son filas. Del código queda una semilla que se usa el día que se crea la tabla y cuando alguien
pide «añadir las básicas»; a partir de ahí manda la tabla.

Lo que se vigila aquí, y por qué cada cosa:

* que la siembra ocurra **al crear la tabla y no cuando esté vacía** — quien borre las once
  porque en su casa no hay ninguna se las encontraría de vuelta en el siguiente arranque;
* que volver a sembrar **no pise lo corregido**, o el botón deshace trabajo cada vez que se
  pulsa;
* que se relacione por **`uid`** y que ese uid no se mueva al renombrar — es lo que guarda cada
  dispositivo de esa clase, y moverlo los deja a todos señalando a una que ya no existe, con el
  filtro en cero;
* que una base de la forma vieja —clave primaria `id`, con el nombre corto dentro— **se migre con
  su flota**: cambiar la tabla sin reescribir `devices.device_type` deja a todos los dispositivos
  apuntando a nada, y eso tampoco da ningún error;
* que renombrar una sembrada **le quite la clave de idioma**, o lo que se lee sigue siendo lo
  que dice el catálogo y no lo que alguien acaba de escribir;
* y que el almacén de dispositivos mire **sólo la tabla**, o una clase añadida se acepta en
  pantalla y se pierde al guardar.
"""

from __future__ import annotations

import os
import sys
import tempfile

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import pytest                                                         # noqa: E402

from lib.core.devices import classes as ht                              # noqa: E402
from lib.core.devices.stores import DevicesStore                          # noqa: E402
from lib.db.sqlite import SQLiteConnector                             # noqa: E402


@pytest.fixture()
def db():
    return SQLiteConnector(os.path.join(tempfile.mkdtemp(prefix='ss-ht-'), 'x.db'))


@pytest.fixture()
def store(db):
    return ht.DeviceTypesStore(db)


def _uid(store, corto):
    """El `uid` de la clase cuyo nombre corto es *corto*.

    Las pruebas hablan de «server» o «nas» porque es como se las nombra al leerlas; lo que se le
    pasa al almacén es su `uid`, que es por donde se relaciona todo y que no se puede escribir
    aquí porque se genera al sembrar.
    """
    fila = next((f for f in store.list() if f['slug'] == corto), None)
    assert fila is not None, 'no existe la clase %s' % corto
    return fila['uid']


class _Panel:
    """Lo justo de un panel para lo que miran las pantallas: sus dos almacenes."""

    def __init__(self, db):
        self._device_types_store = ht.DeviceTypesStore(db)
        self._devices_store = DevicesStore(db)


class TestLaSiembra:
    """Lo único que queda de la lista en el código, y se usa una vez."""

    def test_una_base_nueva_nace_con_las_basicas(self, store):
        assert [c['slug'] for c in store.list()][:3] == ['server', 'workstation', 'nas']
        assert len(store.list()) == len(ht.SEED)

    def test_en_el_orden_declarado_y_no_por_orden_alfabetico(self, store):
        """La lista va de lo más común a lo menos. Ordenada por nombre, «Cámara» sale antes que
        «Servidor» en un desplegable que se usa cuarenta veces al día para decir «servidor»."""
        cortos = [c['slug'] for c in store.list()]
        assert cortos.index('server') < cortos.index('camera')

    def test_cada_sembrada_conserva_su_nombre_corto_de_siempre(self, store):
        """`server`, `nas` y `ups` son los de la semilla, y salen de ahí y no del nombre: la clave
        de idioma de cada una se construye con ellos (`device_type_nas`), y sacarlos del nombre
        —«NAS / Storage» → `nas_storage`— dejaría a las once sin traducción."""
        assert {c['slug'] for c in store.list()} == {t['id'] for t in ht.SEED}

    def test_y_cada_una_nace_con_su_uid(self, store):
        """Que es por donde se relaciona, y por eso no puede ser el nombre corto: un esquema con
        dos maneras de señalar es uno donde hay que acordarse de cuál toca en cada consulta."""
        filas = store.list()
        uids = {c['uid'] for c in filas}
        assert len(uids) == len(filas), 'dos clases comparten uid'
        assert not (uids & {c['slug'] for c in filas}), 'el uid es el nombre corto'

    def test_y_su_clave_de_idioma(self, store):
        """Es lo que hace que se sigan diciendo «Servidor» o «Server» después de mudarse a una
        tabla. Sin ella, sembrarlas obligaba a elegir un idioma al crear la base y dejarlo así
        para siempre."""
        assert store.get(_uid(store, 'server'))['label_key'] == 'device_type_server'

    def test_se_siembra_al_CREAR_la_tabla_y_no_cuando_esta_vacia(self, db):
        """La diferencia entera. Quien borre las once porque en su casa no hay ninguna se las
        encontraría de vuelta en el siguiente arranque, sin que nada lo explicara."""
        primero = ht.DeviceTypesStore(db)
        for c in primero.list():
            primero.delete(c['uid'])
        assert ht.DeviceTypesStore(db).list() == []

    def test_y_volver_a_sembrar_es_un_boton_que_se_pulsa(self, store):
        store.delete(_uid(store, 'camera'))
        store.delete(_uid(store, 'printer'))
        assert sorted(store.seed_missing()) == ['camera', 'printer']
        assert len(store.list()) == len(ht.SEED)

    def test_que_no_pisa_lo_que_alguien_corrigio(self, store):
        """Una «siembra» que rescribe lo editado es una que deshace trabajo cada vez que se
        pulsa."""
        store.update(_uid(store, 'server'), 'Servidor de producción', 'bi-cpu')
        assert store.seed_missing() == []
        fila = store.get(_uid(store, 'server'))
        assert (fila['name'], fila['icon']) == ('Servidor de producción', 'bi-cpu')


class TestElIdentificadorSaleDelNombre:
    """Va a una columna que se compara y se filtra, así que se le quitan las tres cosas que hacen
    que dos escrituras del mismo nombre no casen: acentos, mayúsculas y signos."""

    def test_sin_acentos_en_minusculas_y_con_guiones(self):
        assert ht.slug('Punto de Acceso') == 'punto_de_acceso'
        assert ht.slug('Cámara térmica') == 'camara_termica'

    def test_dos_escrituras_del_mismo_nombre_dan_el_mismo(self):
        assert ht.slug('TELÉFONO  IP') == ht.slug('teléfono ip') == 'telefono_ip'

    def test_un_nombre_que_es_solo_signos_no_es_un_nombre(self):
        """Y devuelve vacío en vez de algo: una clase con el identificador vacío sería
        indistinguible de «sin clasificar», que es justo lo que se estaba evitando."""
        assert ht.slug('...') == '' and ht.slug('  ') == ''

    def test_se_corta_donde_cabe(self):
        assert len(ht.slug('a' * 200)) == ht.ID_MAX


class TestAnadirCorregirYQuitar:

    def test_se_crea_y_se_lee(self, store):
        ident = store.create('Punto de acceso', 'bi-wifi')
        fila = store.get(ident)
        assert (fila['name'], fila['icon'], fila['label_key']) == ('Punto de acceso',
                                                                   'bi-wifi', '')
        # El nombre corto sale del nombre y es para leer; el uid es lo que devuelve `create` y
        # lo que se le vuelve a pasar al almacén.
        assert fila['slug'] == 'punto_de_acceso' and fila['uid'] != 'punto_de_acceso'

    def test_y_con_su_descripcion(self, store):
        """Que es lo que contesta «¿y ésta en qué se diferencia de la de al lado?» el día que hay
        dos parecidas — que es meses después, cuando ya no se acuerda nadie."""
        ident = store.create('Punto de acceso', 'bi-wifi', description='Los del techo')
        assert store.get(ident)['description'] == 'Los del techo'

    def test_la_descripcion_se_corrige_sola(self, store):
        """Sin tocar el nombre: es lo único que se puede escribir sobre una clase que mantiene un
        proveedor, porque de allí no viene."""
        ident = store.create('Punto de acceso')
        assert store.update(ident, 'Punto de acceso', description='Los del techo')
        assert store.get(ident)['description'] == 'Los del techo'

    def test_y_no_venir_no_es_venir_vacia(self, store):
        """Guardar sólo el icono no puede borrar lo que escribió alguien: `None` es «déjala como
        está», y es lo que manda la ruta cuando el campo no viene en la petición."""
        ident = store.create('Punto de acceso', description='Los del techo')
        store.update(ident, 'Punto de acceso', 'bi-broadcast')
        assert store.get(ident)['description'] == 'Los del techo'
        store.update(ident, 'Punto de acceso', 'bi-broadcast', description='')
        assert store.get(ident)['description'] == ''

    def test_el_mismo_nombre_no_entra_dos_veces(self, store):
        """Ni escrito de otra manera: «Punto de Acceso» y «punto de acceso» son la misma clase, y
        dos filas para eso son dos entradas del desplegable que hacen dudar a quien elige."""
        store.create('Punto de acceso')
        assert store.create('PUNTO DE ACCESO') is None

    def test_ni_el_de_una_sembrada(self, store):
        """Aunque ahora sea una fila como las demás: sigue siendo la misma clase, y dos
        «Servidor» en el desplegable son dos sitios donde repartir la misma flota."""
        assert store.create('Server') is None

    def test_ni_cuando_el_nombre_no_se_parece_a_su_identificador(self, store):
        """El caso que se escapa mirando sólo el identificador: `nas` se llama «NAS / Storage», y
        ese nombre da el identificador `nas_storage`, que está libre. Alguien teclea la clase que
        ve escrita en su propia lista y se crea una segunda, con otro identificador y el mismo
        nombre — y a partir de ahí la mitad de la flota va a una y la mitad a la otra.

        Por eso se mira también por NOMBRE y no sólo por identificador. Encontrado mutándolo: la
        prueba de al lado no lo veía, porque «PUNTO DE ACCESO» y «Punto de acceso» sí dan el mismo
        identificador y chocan antes de llegar aquí."""
        assert store.get(_uid(store, 'nas'))['name'] == 'NAS / Storage', 'la semilla ha cambiado'
        assert ht.slug('NAS / Storage') != 'nas', 'el caso ya no se da'
        # En minúsculas **a propósito**: escrito igual lo pararía el índice único de la columna
        # `name`, que es la red de debajo. Escrito de otra manera, no — y entonces lo único que
        # queda entre esto y un duplicado es la comparación por nombre aplanado.
        assert store.create('nas / storage') is None
        assert store.create('NAS / Storage') is None

    def test_renombrar_no_mueve_ni_el_uid_ni_el_nombre_corto(self, store):
        """**La regla entera.** El uid es lo que guarda cada dispositivo de esa clase; si cambiara,
        todos se quedarían señalando a una que ya no existe — sin error, sin aviso, y con el
        filtro de clase devolviendo cero."""
        ident = store.create('Punto de acceso', 'bi-wifi')
        assert store.update(ident, 'Punto de acceso Wi-Fi 6', 'bi-broadcast')
        fila = store.get(ident)
        assert (fila['name'], fila['icon']) == ('Punto de acceso Wi-Fi 6', 'bi-broadcast')
        assert (fila['uid'], fila['slug']) == (ident, 'punto_de_acceso')

    def test_una_sembrada_tambien_se_puede_renombrar(self, store):
        """Nada es intocable: era lo que se pedía al sacar la lista del código."""
        nas = _uid(store, 'nas')
        assert store.update(nas, 'Cabina de discos', 'bi-hdd-stack')
        assert store.get(nas)['name'] == 'Cabina de discos'

    def test_y_al_renombrarla_deja_de_traducirse(self, store):
        """Desde que alguien la llama «Cabina de discos», eso es lo que quiere leer — no lo que
        diga un catálogo de traducciones sobre una palabra que ya no usa. Con la clave puesta, el
        nombre nuevo se guardaría y la pantalla seguiría enseñando «NAS / Almacenamiento»."""
        nas = _uid(store, 'nas')
        store.update(nas, 'Cabina de discos')
        assert store.get(nas)['label_key'] == ''

    def test_renombrar_a_uno_que_ya_existe_se_rechaza(self, store):
        ident = store.create('Punto de acceso')
        assert store.update(ident, 'Router') is False

    def test_una_clase_que_no_existe_no_se_corrige(self, store):
        assert store.update('fantasma', 'X') is False

    def test_sin_nombre_no_hay_clase(self, store):
        assert store.create('   ') is None
        assert store.create('¡!') is None

    def test_una_sembrada_se_puede_quitar(self, store):
        camera = _uid(store, 'camera')
        assert store.delete(camera) is True
        assert store.get(camera) is None


class TestLoQueVenLasPantallas:

    def test_cada_una_dice_como_se_llama_de_UNA_manera(self, db):
        """Las sembradas traen `label_key` —se dicen en el idioma de quien mira— y las escritas
        aquí traen `label`, el texto que puso alguien. Nunca las dos: una clase de casa no es
        traducible porque nadie más sabe que existe, y una sembrada con el texto metido dentro
        saldría en inglés para quien mira en castellano."""
        wa = _Panel(db)
        wa._device_types_store.create('Punto de acceso')
        catalogo = ht.catalog(wa)
        assert catalogo, 'el catálogo ha salido vacío'
        for c in catalogo:
            assert ('label_key' in c) != ('label' in c), c
        porcorto = {c['slug']: c for c in catalogo}
        assert porcorto['server']['label_key'] == 'device_type_server'
        assert porcorto['punto_de_acceso']['label'] == 'Punto de acceso'
        # Y el uid, que es con lo que la pantalla vuelve a hablar del catálogo: sin él, cada
        # acción sobre una fila tendría que buscarla por el nombre.
        assert all(c['uid'] for c in catalogo)

    def test_una_clase_sin_icono_sale_con_el_generico(self, db):
        """Un icono vacío en el catálogo es una fila sin dibujo, y una lista donde una fila de
        cuarenta no tiene icono se lee como una pantalla rota."""
        wa = _Panel(db)
        wa._device_types_store.create('Punto de acceso')
        porcorto = {c['slug']: c for c in ht.catalog(wa)}
        assert porcorto['punto_de_acceso']['icon'] == ht.FALLBACK_ICON

    def test_sin_almacen_el_catalogo_esta_vacio_y_no_revienta(self):
        """Un panel a medio montar no puede dejar la pantalla de dispositivos sin cargar: lo que
        se pierde es el desplegable, y lo que queda es «sin clasificar», que vale para todo."""
        class _Pelado:
            pass

        assert ht.catalog(_Pelado()) == []

    def test_known_mira_la_tabla(self, db):
        wa = _Panel(db)
        propia = wa._device_types_store.create('Punto de acceso')
        assert ht.known(wa, _uid(wa._device_types_store, 'server')) and ht.known(wa, propia)
        assert not ht.known(wa, 'inventada') and not ht.known(wa, '')
        # Y el nombre corto NO reconoce: es para leer, y aceptarlo aquí sería la segunda manera
        # de señalar una clase que este cambio existe para quitar.
        assert not ht.known(wa, 'punto_de_acceso')

    def test_y_deja_de_reconocer_lo_que_se_borra(self, db):
        """Que es la diferencia con la tupla: antes `camera` valía siempre, la borrara quien la
        borrara, porque lo que decidía estaba en el código."""
        wa = _Panel(db)
        camera = _uid(wa._device_types_store, 'camera')
        wa._device_types_store.delete(camera)
        assert not ht.known(wa, camera)


class TestGuardarUnDispositivoNoReconciliaElEsquema:
    """Validar la clase de un dispositivo construía el almacén de clases, y su constructor
    reconcilia la tabla — en CADA guardado. En SQLite cuesta poco; contra MySQL o PostgreSQL son
    otras tantas rondas al catálogo del motor, y una importación de cuatrocientas máquinas son
    cuatrocientas.

    Se ve con un contador y no con un cronómetro: el tiempo depende de la máquina, y el número de
    reconciliaciones no.
    """

    def test_crear_cuatro_dispositivos_no_toca_el_esquema_cuatro_veces(self, db):
        tipos = ht.DeviceTypesStore(db)               # la tabla, creada una vez
        server = _uid(tipos, 'server')
        devices = DevicesStore(db)
        veces = {'n': 0}
        real = db.reconcile_table

        def _contando(spec):
            veces['n'] += 1
            return real(spec)

        db.reconcile_table = _contando
        for n in range(4):
            devices.create({'name': 'h-%d' % n, 'device_type': server})
        assert veces['n'] == 0, 'reconcilia el esquema al guardar un dispositivo'


class TestQueLaColumnaMireLaTabla:
    """El fallo que no da ningún error: la pantalla acepta la clase, el almacén la tira por no
    estar en una lista del código, y el dispositivo se guarda sin nada."""

    def test_una_clase_anadida_se_guarda(self, db):
        clase = ht.DeviceTypesStore(db).create('Punto de acceso')
        devices = DevicesStore(db)
        uid = devices.create({'name': 'ap-1', 'device_type': clase})
        assert devices.get(uid)['device_type'] == clase

    def test_una_sembrada_tambien(self, db):
        server = _uid(ht.DeviceTypesStore(db), 'server')
        devices = DevicesStore(db)
        uid = devices.create({'name': 'srv-1', 'device_type': server})
        assert devices.get(uid)['device_type'] == server

    def test_y_el_nombre_corto_NO_se_guarda(self, db):
        """La columna lleva el `uid` y sólo el `uid`. Aceptar también el nombre corto sería dejar
        media flota apuntando de una manera y media de otra, y entonces el filtro de clase
        contesta la mitad — sin que nada falle."""
        ht.DeviceTypesStore(db)
        devices = DevicesStore(db)
        uid = devices.create({'name': 'srv-1', 'device_type': 'server'})
        assert devices.get(uid)['device_type'] == ''

    def test_una_inventada_sigue_sin_entrar(self, db):
        """Guardar una palabra que nada declara pone en pantalla algo que no se traduce, no se
        filtra y no dibuja ningún icono."""
        ht.DeviceTypesStore(db)
        devices = DevicesStore(db)
        uid = devices.create({'name': 'x-1', 'device_type': 'no_existe'})
        assert devices.get(uid)['device_type'] == ''

    def test_y_una_que_se_borro_deja_de_entrar(self, db):
        """La prueba de que lo que manda es la tabla y no la semilla: `camera` está en el código
        y aun así, borrada, ya no se puede poner."""
        tipos = ht.DeviceTypesStore(db)
        camera = _uid(tipos, 'camera')
        tipos.delete(camera)
        devices = DevicesStore(db)
        uid = devices.create({'name': 'cam-1', 'device_type': camera})
        assert devices.get(uid)['device_type'] == ''


class TestCrearLaQueFalteSinDuplicar:
    """Lo que usa la importación: un tipo de activo que no se parece a ninguna clase de aquí se
    crea, en vez de dejar el dispositivo sin clasificar."""

    def test_la_crea_la_primera_vez(self, db):
        wa = _Panel(db)
        ident = ht.ensure(wa, 'Access Point', source='freshservice')
        fila = wa._device_types_store.get(ident)
        assert (fila['slug'], fila['source']) == ('access_point', 'freshservice')

    def test_y_la_segunda_vez_devuelve_la_misma(self, db):
        """Buscar antes de crear no es una optimización: sin eso, dos importaciones seguidas
        dejan dos clases iguales y la segunda se lleva los dispositivos nuevos."""
        wa = _Panel(db)
        primero = ht.ensure(wa, 'Access Point')
        assert ht.ensure(wa, 'access point') == primero

    def test_si_coincide_con_una_que_ya_hay_devuelve_esa(self, db):
        wa = _Panel(db)
        antes = len(wa._device_types_store.list())
        assert ht.ensure(wa, 'Router') == _uid(wa._device_types_store, 'router')
        assert len(wa._device_types_store.list()) == antes

    def test_un_nombre_que_no_da_identificador_no_crea_nada(self, db):
        wa = _Panel(db)
        antes = len(wa._device_types_store.list())
        assert ht.ensure(wa, '···') == ''
        assert len(wa._device_types_store.list()) == antes


class TestAtarUnaClaseAUnaDeFuera:
    """Por el identificador de allí y no por el nombre, que es la misma regla que en las empresas
    y en los dispositivos. Aquí se ve sola: renombrar una clase es algo que la pantalla **invita**
    a hacer, y buscando sólo por el nombre la siguiente importación crea una segunda con el
    nombre de allí — con la mitad de los dispositivos nuevos yendo a cada una."""

    def test_se_crea_atada_y_la_segunda_vez_es_la_misma(self, db):
        wa = _Panel(db)
        primero = ht.ensure(wa, 'Access Point', source='freshservice', external_id='7009')
        assert ht.ensure(wa, 'Access Point', source='freshservice',
                         external_id='7009') == primero

    def test_y_sigue_siendo_la_misma_despues_de_renombrarla(self, db):
        """**La razón entera de que haya un `external_id`.** Por el nombre, esto crea otra."""
        wa = _Panel(db)
        ident = ht.ensure(wa, 'Access Point', source='freshservice', external_id='7009')
        wa._device_types_store.update(ident, 'Punto de acceso')
        antes = len(wa._device_types_store.list())
        assert ht.ensure(wa, 'Access Point', source='freshservice',
                         external_id='7009') == ident
        assert len(wa._device_types_store.list()) == antes, 'ha creado una segunda'

    def test_y_le_refresca_el_nombre_desde_alli(self, db):
        """La otra mitad de que no se pueda teclear aquí: una clase que nadie puede corregir y
        que tampoco se actualiza sola es un nombre congelado sin dueño."""
        wa = _Panel(db)
        ident = ht.ensure(wa, 'Access Point', source='freshservice', external_id='7009')
        ht.ensure(wa, 'Wireless AP', source='freshservice', external_id='7009')
        assert wa._device_types_store.get(ident)['name'] == 'Wireless AP'

    def test_una_escrita_a_mano_que_se_llama_igual_se_ADOPTA(self, db):
        """En vez de crear una copia — lo mismo que hacen las empresas y los dispositivos. Y
        desde ese momento la mantiene el origen, así que renombrarla ya no la duplica."""
        wa = _Panel(db)
        propia = wa._device_types_store.create('Access Point')
        assert ht.ensure(wa, 'Access Point', source='freshservice',
                         external_id='7009') == propia
        fila = wa._device_types_store.get(propia)
        assert (fila['source'], fila['external_id']) == ('freshservice', '7009')

    def test_atar_a_mano_una_que_se_llama_distinto(self, db):
        """El caso que el nombre no puede resolver: aquí «Punto de acceso», allí «Access Point»."""
        wa = _Panel(db)
        propia = wa._device_types_store.create('Punto de acceso')
        assert wa._device_types_store.link(propia, 'freshservice', '7009') is True
        assert ht.ensure(wa, 'Access Point', source='freshservice',
                         external_id='7009') == propia

    def test_dos_de_aqui_no_pueden_compartir_una_de_fuera(self, db):
        """Sería repartir la flota en dos montones que nadie decidió."""
        wa = _Panel(db)
        a = wa._device_types_store.create('Punto de acceso')
        b = wa._device_types_store.create('Antena')
        assert wa._device_types_store.link(a, 'freshservice', '7009') is True
        assert wa._device_types_store.link(b, 'freshservice', '7009') is False

    def test_soltarla_la_devuelve_a_esta_casa(self, db):
        wa = _Panel(db)
        propia = wa._device_types_store.create('Punto de acceso')
        wa._device_types_store.link(propia, 'freshservice', '7009')
        assert wa._device_types_store.link(propia, '', '') is True
        fila = wa._device_types_store.get(propia)
        assert (fila['source'], fila['external_id']) == ('', '')

    def test_la_siembra_no_es_un_origen(self, db):
        """`source` dice qué sistema de FUERA mantiene la fila, y la siembra no es uno: es lo que
        trae cualquier instalación, y se renombra, se le cambia el icono y se quita como todo lo
        demás. Marcándola había que excluirla a mano en cada sitio que preguntara «¿esto lo
        mantiene otro?», y cada uno era una ocasión de olvidarlo. Reportado desde la base.

        Cuál vino de la siembra lo dice `label_key`, que sólo la llevan ellas."""
        store = ht.DeviceTypesStore(db)
        fila = store.get(_uid(store, 'server'))
        assert (fila['source'], fila['external_id']) == ('', '')
        assert fila['label_key'] == 'device_type_server', 'entonces no hay cómo reconocerlas'

    def test_y_la_escribe_el_usuario_system(self, db):
        """Que es el que este panel tiene para lo que hace él solo. Escribir «seed» ahí es
        inventarse un usuario que no existe en ninguna otra tabla."""
        from lib.core.constants import SYSTEM_USER                 # noqa: PLC0415
        store = ht.DeviceTypesStore(db)
        assert store.get(_uid(store, 'server'))['updated_by'] == SYSTEM_USER


class TestCuantosLaLlevanPuesta:
    """Se pregunta antes de borrarla. Quitar una que llevan cuarenta máquinas las deja con una
    palabra que ya no significa nada, y no se arregla volviendo a crearla con el mismo nombre:
    lo que se perdió fue saber que había que hacerlo."""

    def test_cuenta_los_que_la_llevan(self, db):
        wa = _Panel(db)
        ap = wa._device_types_store.create('Punto de acceso')
        wa._devices_store.create({'name': 'ap-1', 'device_type': ap})
        wa._devices_store.create({'name': 'ap-2', 'device_type': ap})
        wa._devices_store.create({'name': 'srv-1',
                                'device_type': _uid(wa._device_types_store, 'server')})
        assert ht.in_use(wa, ap) == 2
        assert ht.in_use(wa, _uid(wa._device_types_store, 'camera')) == 0

    def test_no_se_cuenta_recorriendo_la_flota(self, db):
        """**Lo cuenta el motor.** Esto lo preguntaba leyendo todos los dispositivos en Python
        —cada fila son cuatro `json.loads`— y con tres mil máquinas eran 110 ms por clase: quitar
        doce eran doce lecturas completas de la flota, y lo que se veía era una pantalla que
        tardaba. Reportado desde ella: «¿por qué tarda tanto en eliminar los tipos?».

        La guarda es mecánica: con `list()` reventando, las dos preguntas siguen contestando. Si
        alguien vuelve a contar en Python, esto falla — que es lo único que puede decirlo, porque
        la respuesta es la misma por los dos caminos y sólo cambia el tiempo.
        """
        wa = _Panel(db)
        ap = wa._device_types_store.create('Punto de acceso')
        server = _uid(wa._device_types_store, 'server')
        wa._devices_store.create({'name': 'ap-1', 'device_type': ap})
        wa._devices_store.create({'name': 'srv-1', 'device_type': server})

        def _no(*_a, **_k):
            raise AssertionError('ha leído la flota entera para contar')

        wa._devices_store.list = _no
        assert ht.in_use(wa, ap) == 1
        assert ht.usage(wa) == {ap: 1, server: 1}

    def test_y_el_recuento_de_todas_sale_de_UNA_consulta(self, db):
        """La pantalla de clases lo enseña en cada fila. Preguntarlo una a una sería una consulta
        por clase — doce para dibujar una tabla."""
        wa = _Panel(db)
        server = _uid(wa._device_types_store, 'server')
        switch = _uid(wa._device_types_store, 'switch')
        wa._devices_store.create({'name': 'srv-1', 'device_type': server})
        wa._devices_store.create({'name': 'sw-1', 'device_type': switch})
        wa._devices_store.create({'name': 'x-1'})
        assert ht.usage(wa) == {server: 1, switch: 1}, 'un sin clasificar se ha colado'


class TestLaDescripcionDeLasDeSerie:
    """Viaja por el mismo camino que su nombre: la clave del catálogo de idiomas, no la columna.

    Escrita en la columna se congelaría en el idioma de quien creó la base — que es exactamente el
    problema que `label_key` existe para evitar, y que aquí se daría además en una frase entera.
    """

    def test_una_sembrada_dice_de_donde_sale_la_suya(self, db):
        wa = _Panel(db)
        fila = next(c for c in ht.catalog(wa) if c['slug'] == 'nas')
        assert fila['description'] == '', 'se ha escrito en la columna'
        assert fila['desc_key'] == 'device_type_nas_desc'

    def test_y_la_clave_existe_en_los_dos_idiomas(self, db):
        """`t()` devuelve la clave que se le dio cuando no la encuentra, así que una que falte no
        deja un hueco: deja `host_type_nas_desc` escrito en la columna de la frase."""
        from lib.i18n import TRANSLATIONS                           # noqa: PLC0415
        wa = _Panel(db)
        claves = [c['desc_key'] for c in ht.catalog(wa) if c.get('desc_key')]
        assert len(claves) == len(ht.SEED), 'alguna sembrada no dice de dónde sale la suya'
        for idioma in ('es_ES', 'en_EN'):
            faltan = [k for k in claves if not (TRANSLATIONS.get(idioma) or {}).get(k)]
            assert not faltan, '%s: %s' % (idioma, faltan)

    def test_una_escrita_aqui_lleva_su_texto_y_ninguna_clave(self, db):
        """Una clase de esta casa no es traducible, porque nadie más sabe que existe — lo mismo
        que ya pasa con su nombre. Las dos cosas a la vez serían dos descripciones para la misma
        fila y una pantalla eligiendo."""
        wa = _Panel(db)
        propia = wa._device_types_store.create('Punto de acceso', description='Los del techo')
        fila = next(c for c in ht.catalog(wa) if c['uid'] == propia)
        assert fila['description'] == 'Los del techo'
        assert 'desc_key' not in fila

    def test_y_describir_una_de_serie_a_mano_no_le_quita_la_clave(self, db):
        """A diferencia de renombrarla. El texto guardado manda al dibujar —quien lo escribió
        quiere leer el suyo— pero la clave se queda: borrar lo escrito devuelve la de serie en el
        idioma de quien mire, en vez de dejar la fila muda."""
        wa = _Panel(db)
        nas = _uid(wa._device_types_store, 'nas')
        # `keep_label` es lo que decide la ruta al ver que el nombre no cambia — describirla no es
        # renombrarla. Sin él, el almacén hace lo que hace al renombrar: quitarle la clave.
        wa._device_types_store.update(nas, 'NAS / Storage', keep_label=True,
                                    description='Las dos cabinas del CPD')
        fila = next(c for c in ht.catalog(wa) if c['uid'] == nas)
        assert fila['description'] == 'Las dos cabinas del CPD'
        assert fila['desc_key'] == 'device_type_nas_desc'
