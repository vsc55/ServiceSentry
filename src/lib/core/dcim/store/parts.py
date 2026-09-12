#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_part`` — what a piece of equipment is MADE OF: disks, memory, cards,
and the ports it exposes."""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec


#: De qué puede ser un componente. `accessory` es el cargador del mini-PC, el latiguillo corto que
#: vive con él, el kit de raíles — cosas que no son elegantes y son exactamente las que faltan
#: cuando alguien las necesita.
#:
#: `jack` es lo que PUEBLA un hueco: el módulo keystone de un panel, el acoplador LC de uno de
#: fibra. No es «lo de dentro» —no es una ranura de la placa— ni «lo que cuelga» —no está
#: enchufado por fuera—, y sin una clase propia había que meterlo en `accessory` y perder la
#: única pregunta que se le hace: qué hay puesto en el hueco 7. Un panel keystone se compra
#: VACÍO, así que lo que lleva no puede salir del modelo: es de cada panel.
PART_KINDS = ('disk', 'ssd', 'memory', 'cpu', 'nic', 'hba', 'gpu', 'psu', 'fan',
              'transceiver', 'jack', 'battery', 'module', 'accessory', 'other')

#: Las familias de puerto que se nombran. Las mismas nueve del catálogo y del documento de
#: conectores: una escrita a mano que no esté aquí sería una lista que ninguna pantalla dibuja.
PORT_FAMILIES = ('interfaces', 'power-ports', 'power-outlets', 'console-ports',
                 'console-server-ports', 'front-ports', 'rear-ports', 'module-bays',
                 'device-bays')

#: Cuántas bocas se nombran como mucho por familia. Un chasis de verdad no llega; el tope está
#: para que nadie meta cien mil entradas en una columna. Lo que se pierde es detalle, nunca el
#: recuento — que se cuenta aparte y no tiene tope.
PORT_LIST_MAX = 512

#: El tope de vatios de una toma. Un rack entero no llega; está para que un cero de más no
#: convierta una suma de consumos en una cifra que nadie mira dos veces.
WATTS_MAX = 100000

#: Y cuántas señales caben en un puerto. Un USB-C lleva datos, vídeo y corriente a la vez; ocho
#: es más de lo que existe y sigue siendo una lista que se lee de un vistazo.
PORT_SIGNALS_MAX = 8

_PART = TableSpec(
    name='dc_part',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        Column('item_uid', 'TEXT', nullable=False),
        Column('kind',     'TEXT', nullable=False, default="'other'"),
        # Cómo se llama en la máquina: «bahía 3», «DIMM A1», «PSU 2». Es lo que hay que decirle
        # a quien está delante con un destornillador, y no siempre coincide con nada del modelo.
        Column('slot',     'TEXT', nullable=False, default="''"),
        Column('model',    'TEXT', nullable=False, default="''"),
        Column('serial',   'TEXT', nullable=False, default="''"),
        # El tamaño como TEXTO: «4 TB», «32 GB», «10 GbE», «750 W». Guardarlo en bytes obligaría
        # a decidir si un disco de 4 TB son 4·10¹² o 4·2⁴⁰ —y las dos respuestas están en algún
        # albarán— y a convertir para enseñar lo que alguien ya escribió bien.
        Column('size',     'TEXT', nullable=False, default="''"),
        # Cuántos iguales. Seis discos idénticos son una fila con un seis, no seis filas: nadie
        # apunta el número de serie de cada uno, y obligar a ello es garantizar que no se apunte
        # ninguno.
        Column('qty',      'INTEGER', nullable=False, default='1'),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
        # De qué modelo del catálogo es, cuando alguien lo dijo. Opcional a propósito: el disco
        # que salió del cajón no está en ningún catálogo y sigue siendo un disco. Lo que da es
        # poder preguntar «cuántos KSM32RD8/32 hay puestos» sin depender de que las once formas
        # de escribir el mismo modelo coincidan.
        #
        # La última, para que aparecer sobre una tabla llena sea un `ADD COLUMN`.
        Column('type_uid', 'TEXT', nullable=False, default="''"),
        # La MARCA, aparte del modelo. «Samsung PM9A3» en una sola casilla son once formas de
        # escribir lo mismo que no se pueden contar juntas — y contar juntas es la única
        # pregunta que se le hace a esto: cuántos de estos tengo y en qué máquinas.
        #
        # Como texto y no como `brand_uid`, igual que `dc_type.manufacturer`: es lo que se dijo
        # de esta pieza, y sigue siendo cierto si alguien retira la ficha de la marca. El
        # vínculo bueno lo tiene el modelo del catálogo, que es a quien apunta `type_uid`.
        Column('brand', 'TEXT', nullable=False, default="''"),
        # Cuántas piezas trae una unidad de lo que se compró. Estampada como lo demás: una
        # máquina que dice llevar dos kits sigue diciendo cuántos módulos son aunque alguien
        # borre el modelo del catálogo.
        Column('kit_qty', 'INTEGER', nullable=False, default='1'),
        # Dentro de la caja o colgando de ella. Se estampa desde la plantilla como lo demás: el
        # adaptador de red que el estándar dice que lleva sigue siendo externo en la máquina que
        # sale de él, y el día de la mudanza eso es lo que hay que acordarse de meter en la caja.
        Column('mount',   'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_part_item', ('item_uid',)),),
)

def clean_port_list(value) -> dict:
    """``{familia: [{'name', 'type', 'gen', 'signals'}, …]}`` — lo que se guarda, y nada más.

    **En la puerta y no en la pantalla**: lo que llega es un JSON del navegador, y guardarlo tal
    cual es guardar lo que mande quien sepa escribir una petición. Lo que no se reconoce se cae
    aquí, donde se puede decir por qué, y no tres pantallas más allá donde solo se ve un hueco.

    Sin nombre no hay entrada: el nombre es lo que se guarda y lo que cruza con el componente que
    va en ese hueco. Una lista de guiones no dice nada que el recuento no diga mejor.

    El orden se respeta —`gi10` va detrás de `gi9` en el equipo y delante alfabéticamente— y los
    campos vacíos no se escriben: un `gen: ''` es una generación que alguien tendría que
    interpretar, y no hay nada que interpretar.
    """
    fuera: dict = {}
    if not isinstance(value, dict):
        return fuera
    for fam in PORT_FAMILIES:
        filas = value.get(fam)
        if not isinstance(filas, list) or not filas:
            continue
        lista = []
        for x in filas:
            if not isinstance(x, dict):
                continue
            nombre = str(x.get('name') or '').strip()[:120]
            if not nombre:
                continue
            uno = {'name': nombre, 'type': str(x.get('type') or '').strip()[:60]}
            gen = str(x.get('gen') or '').strip()[:60]
            if gen:
                uno['gen'] = gen
            # Abiertas a propósito: una señal que no esté en el vocabulario se conserva y se
            # enseña tal cual, que es lo que deja ampliar el documento sin tocar el panel.
            senales = []
            for sig in (x.get('signals') or ()):
                sig = str(sig or '').strip()[:40]
                if sig and sig not in senales:
                    senales.append(sig)
            if senales:
                uno['signals'] = senales[:PORT_SIGNALS_MAX]
            # El voltaje como texto —lo que pone en la etiqueta es `100-240 V`, un rango— y los
            # vatios como número, que son los que se suman para saber cuánto pide un armario.
            volt = str(x.get('volts') or '').strip()[:24]
            if volt:
                uno['volts'] = volt
            try:
                vat = int(float(x.get('watts') or 0))
            except (TypeError, ValueError):
                vat = 0
            if 0 < vat <= WATTS_MAX:
                uno['watts'] = vat
            lista.append(uno)
            if len(lista) >= PORT_LIST_MAX:
                break
        if lista:
            fuera[fam] = lista
    return fuera
