#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que comparten todas las áreas: los permisos y los ayudantes que usan dos o más.

Un objeto y no un módulo con funciones sueltas porque casi todos cierran sobre `wa` —el
panel— y sobre los almacenes que este construye al arrancar: son ayudantes de ESTA
aplicación, no de la librería. Se arman una vez y cada área recibe el mismo.

Lo que solo usa un área **no está aquí**: se queda con sus rutas, que es donde se lee sin
ir a buscarlo. Esa es la mitad del sitio que gana el reparto.
"""

from __future__ import annotations

from types import SimpleNamespace

from flask import request, session

from lib.core.hosts import service as hosts_svc

from lib.core.dcim import assets as dcim_assets
from lib.core.dcim import builds as dcim_builds
from lib.core.dcim import catalog as dcim_catalog
from lib.core.dcim import owners as dcim_owners
from lib.core.dcim import profiles as dcim_profiles
from lib.core.dcim import rackrev as dcim_rackrev
from lib.core.dcim import service as dcim_svc
from lib.core.dcim.store import PART_KINDS


def build(app, wa):
    """Los ayudantes de esta aplicación, armados una vez."""
    dcim_view_req = wa._perm_required('dcim_view')
    dcim_edit_req = wa._perm_required('dcim_edit')
    # Tocar el cableado es su propia bandera: mover un equipo de U y decir por dónde va un
    # cable son dos trabajos, muchas veces de dos personas.
    dcim_cable_req = wa._perm_required('dcim_cable_edit')
    dcim_org_edit_req = wa._perm_required('dcim_org_edit')
    dcim_catalog_view_req = wa._perm_required('dcim_catalog_view')
    dcim_catalog_manage_req = wa._perm_required('dcim_catalog_manage')
    # Decidir el estándar de compra no es colocar una caja en un U: lo hacen personas distintas
    # en momentos distintos, y con una sola bandera quien monta un rack rescribe lo que compra
    # la empresa. Leerlas, en cambio, va con `dcim_view`: hay que poder ELEGIR una al colocar un
    # equipo, y pedir para eso el permiso del catálogo dejaría sin plantillas a quien monta.
    dcim_build_req = wa._perm_required('dcim_build_edit')

    def _actor():
        return session.get('username', '')

    def _store():
        return getattr(wa, '_dcim_store', None)

    def _perms():
        return set(wa._get_session_permissions() or [])

    def _seen():
        """What this caller may see, resolved once. See `owners.visible_orgs`."""
        return dcim_owners.visible_orgs(_perms())

    def _states():
        """Every machine's live state, once per request.

        The same read Infrastructure's fleet list is drawn from, so a rack and the list cannot
        disagree about whether a machine is in trouble. Asked once and handed down: per node it
        would be a read of the status file per rack, and this screen is opened with forty.

        A caller with no `devices_view` may still see a rack; what they must not get is the
        state of a machine the registry hides from them. Narrowed here rather than at each
        drawing, so there is one place to be right.
        """
        perms = _perms()
        try:
            rows = hosts_svc._host_statuses(wa) or {}
        except Exception:                       # pylint: disable=broad-except
            return {}                           # a colour is not worth failing the page for
        if 'devices_view' in perms:
            return rows
        return {uid: st for uid, st in rows.items() if f'server.{uid}.view' in perms}

    def _owner_of(store, said, scope, uid):
        return dcim_owners.owner_of(store.chain_of(scope, uid), said)

    def _filtered(rows, store, said, allowed, scope, reach=None):
        """Rows this caller may see, with the rest reduced to what they occupy.

        Only items have a shape worth returning opaquely — a rack of somebody else's is still a
        rack, and its U being taken is the fact that makes the room plannable. A site or a room
        they may not see is simply not listed: there is nothing about it that helps them.

        *reach* trae la otra mitad de la regla: una caja que CONTIENE algo suyo se lista aunque
        no sea suya. Sin ella, el caso del holding —el departamento opera la sede, la filial
        tiene 2U dentro— deja a la filial con la pantalla vacía y su equipo inalcanzable.
        """
        out = []
        for row in rows:
            org = _owner_of(store, said, scope, row.get('uid'))
            if dcim_owners.may_see(org, allowed) or dcim_svc.llega(reach, scope,
                                                                  row.get('uid')):
                out.append(dict(row, org_uid=org))
            elif scope == 'item':
                out.append(dcim_owners.opaque(row))
        return out

    def _may_write(store, said, allowed, scope, uid) -> bool:
        """Whether this caller may change one thing. Checked on what is being CHANGED."""
        return dcim_owners.may_see(_owner_of(store, said, scope, uid), allowed)

    # ── Companies ─────────────────────────────────────────────────────────────

    def _media_dir():
        """The configured pictures folder, or '' for the default under var_dir.

        Read on every call rather than cached, like the backup folder: moving it must not
        need a restart, and an operator who moves it mid-day would otherwise write the next
        upload to the old path and then not find it there."""
        return str(getattr(wa, '_DCIM_MEDIA_DIR', '') or '')
    def _from_type(data: dict) -> dict:
        """Lo que una pieza toma de su modelo del catálogo, cuando dice de cuál es.

        **Manda el catálogo, no la petición.** Un SSD no es de esta máquina: es un modelo que va
        en veinte, y su marca, su nombre y su tamaño son suyos. Dejar que cada formulario los
        escribiera serían once formas de teclear «Samsung PM9A3» que no se pueden contar juntas
        — y contar juntas es la única pregunta que se le hace a esto.

        Lo que sí es de la pieza —la bahía, la cantidad, el número de serie— no se toca.
        """
        fuera = dict(data or {})
        # Dónde vive, acotado: `Rows` escribe cualquier columna de la tabla, así que sin esto una
        # petición podría dejar ahí una palabra que ninguna pestaña sabe leer — y la pieza
        # desaparecería de las dos.
        if 'mount' in fuera:
            fuera['mount'] = (str(fuera.get('mount') or '').strip()
                              if str(fuera.get('mount') or '').strip()
                              in dcim_builds.MOUNTS else '')
        if 'kit_qty' in fuera:
            try:
                fuera['kit_qty'] = max(1, int(float(fuera['kit_qty'] or 1)))
            except (TypeError, ValueError):
                fuera['kit_qty'] = 1
        uid = str(fuera.get('type_uid') or '').strip()
        if not uid:
            return fuera
        cat = getattr(wa, '_dcim_catalog', None)
        modelo = cat.get(uid) if cat else None
        if not modelo:
            # Un modelo que no existe no es un modelo: guardar el identificador dejaría una
            # pieza afirmando venir de algo que no está, y eso no da ningún error al escribirlo.
            fuera.pop('type_uid', None)
            return fuera
        for destino, origen in dcim_catalog.PART_FROM_TYPE:
            valor = modelo.get(origen)
            # Los números se copian como números: `kit_qty` es una columna entera, y meterle
            # `'2'` funciona en SQLite y no en los otros dos motores.
            fuera[destino] = valor if isinstance(valor, int) else str(valor or '')
        # Y nunca por debajo de uno: una unidad que trae cero piezas no es una unidad.
        try:
            fuera['kit_qty'] = max(1, int(fuera.get('kit_qty') or 1))
        except (TypeError, ValueError):
            fuera['kit_qty'] = 1
        # Y la clase, si el modelo la sabe y quien pide no la ha dicho: un modelo de
        # `component-types` está clasificado con el mismo vocabulario que una pieza.
        if not str(fuera.get('kind') or '').strip():
            clase = str(modelo.get('kind') or '')
            if clase in PART_KINDS:
                fuera['kind'] = clase
        return fuera

    # ── Qué se pregunta de un componente ──────────────────────────────────────
    def _profiles():
        return getattr(wa, '_dcim_profiles', None)
    def _component_fields() -> dict:
        """Los atributos de cada clase de componente, del documento que mande.

        Servido y no escrito en la pantalla: once clases con cuatro atributos puestas a mano en
        una plantilla son la lista que nadie actualiza el día que entra la doceava — y sobre
        todo, así se puede cambiar sin tocar la pantalla ni el servidor.
        """
        doc = dcim_profiles.effective(_profiles())
        # Solo los de la clase: los comunes van aparte, con los datos generales, porque algo que
        # tienen todas las clases no distingue ninguna.
        return {k: list((doc.get('kinds') or {}).get(k, []))
                for k in dcim_catalog.kinds_for(dcim_catalog.COMPONENT_TREE)}
    def _conns():
        return getattr(wa, '_dcim_conns', None)
    def _platforms():
        return getattr(wa, '_dcim_platforms', None)
    def _brands():
        cat = getattr(wa, '_dcim_catalog', None)
        return getattr(cat, 'brands', None) if cat else None
    def _builds():
        return getattr(wa, '_dcim_builds', None)

    #: Lo que la pantalla necesita saber del modelo base. No la fila entera —sobran el
    #: origen y la fecha de importación— y no solo el nombre: la altura, el fondo y la clase son
    #: justo lo que la plantilla NO tiene que volver a preguntar.
    #:
    #: Los puertos SÍ, y aquí decía que sobraban. Sobraban cuando se escribió esta línea; desde
    #: que el resumen cuenta cuántas bocas de red sale un equipo, son justo lo que falta — y un
    #: campo que no se pide no da ningún error: da un cero que parece un dato. Un mini-PC con su
    #: puerto en la placa decía tener solo la tarjeta que alguien le añadió.
    def _build_wanted(data: dict):
        """La plantilla que la petición pide, si pide alguna y existe."""
        uid = str((data or {}).get('build_uid') or '').strip()
        plantillas = _builds()
        return plantillas.get(uid) if (uid and plantillas) else None
    def _from_build(build: dict, data: dict) -> dict:
        """Lo que la plantilla sabe, puesto **solo donde la petición no dijo nada**.

        Al revés sería que la plantilla mandara sobre quien está delante: el fondo de una caja
        que alguien acaba de medir con un metro vale más que el que se escribió en el estándar
        hace un año, y una plantilla que pisa lo tecleado deja de poder usarse para lo que casi
        encaja — que es la mitad de los casos.
        """
        fuera = dict(data or {})
        for campo in ('role', 'face', 'type_uid'):
            if not str(fuera.get(campo) or '').strip() and build.get(campo):
                fuera[campo] = build[campo]
        if not fuera.get('depth_mm') and build.get('depth_mm'):
            fuera['depth_mm'] = build['depth_mm']
        if not fuera.get('u_height'):
            # La de la plantilla, y si no la fija, la del modelo del catálogo — que es donde
            # está escrita de verdad: un R740 mide lo que mide se le ponga lo que se le ponga.
            #
            # Las dos en décimas, y el equipo cuenta U enteros: uno de 0,5 U ocupa **un** U y
            # comparte sus dos mitades, que es lo que de verdad pasa en el armario. Por eso se
            # redondea hacia arriba y no hacia abajo — hacia abajo daría cero, y una caja que
            # ocupa cero U es una que el dibujo no pinta.
            decimas = int(build.get('u_tenths') or 0)
            if not decimas:
                cat = getattr(wa, '_dcim_catalog', None)
                modelo = cat.get(str(build.get('type_uid') or '')) if cat else None
                decimas = int((modelo or {}).get('u_tenths') or 0)
            if decimas:
                fuera['u_height'] = max(1, -(-decimas // 10))
        # Y cómo comparte U, que es del estándar: dos por U para un patch panel de 0,5 U, ocho
        # para una bandeja de Raspberry. *Cuál* de las partes toma esta caja no lo dice la
        # plantilla —una va arriba y la otra abajo— así que eso se queda sin poner.
        for campo, defecto in (('u_slots', 1), ('u_slot_span', 1), ('u_split', 'width')):
            if not fuera.get(campo) and build.get(campo) not in (None, '', defecto):
                fuera[campo] = build[campo]
        fuera['build_uid'] = build['uid']
        return fuera
    def _snap(rack_uid: str, action: str = 'edit') -> None:
        """Guardar cómo queda el armario **después** de un cambio.

        Una foto por cambio contesta las dos preguntas que se le hacen a un armario con un año
        de vida: cómo estaba en marzo (la foto) y qué le pasó (la diferencia con la anterior).
        Al revés no funciona: de una lista de acontecimientos no se reconstruye un estado sin
        reproducirlos todos, y basta que falte uno para que la reconstrucción mienta sin decirlo.

        **Después y no antes**, como el historial del catálogo y por lo mismo: así la última
        versión es lo que hay ahora y la lista se lee sola.

        Se llama al final de cada escritura que toca el armario o lo que hay dentro. Que no se
        olvide ninguna no se deja a la memoria: hay una prueba que recorre las rutas y lo exige.
        """
        store = _store()
        rack = store.racks.get(str(rack_uid or '')) if store else None
        if not rack:
            return
        foto = dcim_rackrev.snapshot(rack, store.items_of(str(rack_uid or '')))
        historial = store.revs.history(str(rack_uid or ''), scope=dcim_rackrev.SCOPE)
        # Una escritura que no cambió nada no es una versión. Un formulario manda la ficha
        # entera cada vez que se pulsa guardar, y doce renglones idénticos no dicen qué pasó:
        # dicen que alguien pulsó un botón.
        if historial and dcim_rackrev.same((historial[0].get('data') or {}), foto):
            return
        store.revs.keep(str(rack_uid or ''), foto, action=str(action or 'edit'),
                        actor=_actor(), scope=dcim_rackrev.SCOPE)

    def _from_type_item(data: dict) -> dict:
        """Lo que un EQUIPO toma de su modelo del catálogo al colocarlo.

        No todo lo que se pone en un armario nace de una plantilla. Una tapa ciega, una regleta,
        una bandeja y un panel de parcheo no tienen estándar de compra ni componentes que
        estampar: son un modelo del catálogo y una U. Obligar a inventarse una plantilla para
        cada uno es pedir que se declare un estándar de una tapa.

        Lo que el modelo sabe y quien coloca no ha dicho: **cuánto mide**. Es el dato del que
        depende que quepa, y el único que la biblioteca trae de verdad — de un modelo no se sabe
        el fondo en milímetros («full depth» no es una medida) ni para qué se va a usar.

        Al revés que la plantilla y por lo mismo: lo tecleado manda. Quien acaba de medir la caja
        con un metro sabe más que la biblioteca.
        """
        fuera = dict(data or {})
        uid = str(fuera.get('type_uid') or '').strip()
        if not uid:
            return fuera
        cat = getattr(wa, '_dcim_catalog', None)
        modelo = cat.get(uid) if cat else None
        if not modelo:
            # Un modelo que no existe no es un modelo: guardar el identificador dejaría un
            # equipo afirmando ser algo que no está, y eso no da ningún error al escribirlo.
            fuera.pop('type_uid', None)
            return fuera
        if not fuera.get('u_height'):
            # En décimas, y el armario cuenta U enteros: uno de 0,5 U ocupa **un** U y comparte
            # sus dos mitades, que es lo que de verdad pasa. Hacia arriba, porque hacia abajo
            # daría cero y una caja que ocupa cero U es una que el dibujo no pinta.
            decimas = int(modelo.get('u_tenths') or 0)
            if decimas:
                fuera['u_height'] = max(1, -(-decimas // 10))
        return fuera

    def _asset(part, data, skip: str = '') -> str:
        """Deja el número de inventario RESUELTO en *data*, y devuelve el error o ``''``.

        En un ayudante compartido porque lo escriben cinco puertas —el armario, el equipo, la
        regleta, el cable de datos y el de corriente— y la unicidad de un número no es de
        ninguna de ellas: es de todas a la vez. Comprobarla en cada una es tener cuatro sitios
        donde puede quedarse sin comprobar, y el que se olvida no da ningún error el día que se
        escribe.

        *part* es el almacén al que va la fila, y con él esto **no hace nada** donde no hay
        número que llevar: una sede y una sala pasan por el mismo CRUD que un armario, y minarle
        un número a algo que no tiene la columna sería gastar uno de la numeración en una fila
        que no lo va a guardar.
        """
        store = _store()
        rows = getattr(store, str(part or ''), None) if store else None
        col = dcim_assets.ASSET_COL
        if rows is None or not rows.has(col) or col not in (data or {}):
            return ''
        data[col], err = store.mint_asset(data[col], skip)
        return err

    def _files():
        return getattr(wa, '_dcim_files', None)

    return SimpleNamespace(
        actor=_actor,
        from_type_item=_from_type_item,
        snap=_snap,
        store=_store,
        perms=_perms,
        seen=_seen,
        states=_states,
        owner_of=_owner_of,
        filtered=_filtered,
        may_write=_may_write,
        media_dir=_media_dir,
        from_type=_from_type,
        profiles=_profiles,
        component_fields=_component_fields,
        conns=_conns,
        platforms=_platforms,
        brands=_brands,
        builds=_builds,
        build_wanted=_build_wanted,
        from_build=_from_build,
        files=_files,
        asset=_asset,
        view_req=dcim_view_req,
        edit_req=dcim_edit_req,
        cable_req=dcim_cable_req,
        org_edit_req=dcim_org_edit_req,
        catalog_view_req=dcim_catalog_view_req,
        catalog_manage_req=dcim_catalog_manage_req,
        build_req=dcim_build_req,
    )
