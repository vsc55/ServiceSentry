#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que este proveedor aporta (ver `lib/discovery.py`).

Un botón en su tarjeta de configuración, otro en la pantalla de Empresas, otro en la de
Dispositivos, y tres líneas de auditoría. Nada más: la sección de Empresas no sabe que esto existe, y este paquete no aparece
nombrado en ninguna pantalla del core — se declara, y el panel lo dibuja.

**Los dos botones no viven en el mismo sitio, y es el mismo argumento que los separó.** Probar la
conexión es una *pregunta* sobre unos ajustes, y se hace donde se teclean: en su tarjeta de
Configuración. Traer las empresas es un *acto* sobre la lista de Empresas, y se hace donde está
esa lista — bajar a Configuración para importar es ir a buscar un botón a la pantalla de otra
cosa. Pedido desde la pantalla.

El JavaScript que se nombra aquí viaja con el paquete (`web/_ui.html`), que es lo que permite
quitar el proveedor entero borrando su carpeta.
"""

from lib.providers.freshservice.service import is_configured

# ── Botones en la tarjeta «Freshservice» de la configuración ─────────────────────────────
#
# Probar, y traer. En ese orden y separados a propósito: comprobar la conexión mientras se teclea
# la clave es una pregunta, e importar es un acto — y con un solo botón, quien sólo quería saber
# si la clave vale se encuentra con cuarenta empresas creadas.
#
# Pide `orgs_edit`, que es la misma bandera que exige el servidor. La de aquí es una reja
# encima de esa, nunca en su lugar.
CONFIG_ACTIONS = [
    {'section': 'freshservice', 'id': 'test',
     'label_key': 'fs_test', 'tooltip_key': 'fs_test_tt',
     'icon': 'bi-plug', 'variant': 'secondary', 'order': 10,
     'perm': 'orgs_edit', 'group_label_key': 'fs_actions',
     'fn': 'freshserviceTest',
     # Tras el dominio: sin él no hay a quién llamar, y es lo que dice si esto está puesto.
     'show_when': {'field': 'domain', 'not_empty': True}},
]


# ── El botón de traer, en la pantalla de Empresas ────────────────────────────────────────
#
# Ahí y no en Configuración: es un acto sobre esa lista. Y **sólo cuando el conector está
# puesto** — un botón que promete traer cuarenta empresas y falla en la primera llamada por una
# clave que nadie ha escrito es peor que no tenerlo, porque el error que da es de autenticación
# y eso manda a mirar la credencial en vez del campo vacío.
#
# Quién decide si está puesto es este paquete, no la pantalla: `ready` es una función suya, y el
# día que le haga falta un tercer campo la respuesta cambia aquí y en ningún otro sitio.
ORG_ACTIONS = [
    # Su propio texto, distinto del que lleva el botón del cuadro: aquí hay que decir de
    # DÓNDE se trae —esta pantalla no sabe de proveedores— y allí no, que el cuadro ya se
    # titula con el nombre y el botón lleva la cuenta pegada detrás.
    {'id': 'import', 'label_key': 'fs_import_orgs', 'tooltip_key': 'fs_import_tt',
     'icon': 'bi-cloud-download', 'variant': 'primary', 'order': 10,
     'perm': 'orgs_edit', 'fn': 'freshserviceImport',
     'ready': is_configured},
]


# ── El botón de traer, en la pantalla de Dispositivos ────────────────────────────────────
#
# El mismo argumento una planta más abajo: dar de alta un dispositivo es lo que esa pantalla sabe
# hacer, y traerlo de donde ya está escrito es **otra manera de que aparezca uno**. Por eso cuelga
# del botón de añadir y no es un botón más en la barra — el día que haya una segunda fuente, la
# barra sigue igual de vacía.
#
# `devices_edit` y no `orgs_edit`: esto crea fichas en el registro de máquinas. Quien lleva las
# sociedades no tiene por qué poder dar de alta cuarenta servidores, y al revés tampoco.
DEVICE_ACTIONS = [
    {'id': 'import', 'label_key': 'fs_import_hosts', 'tooltip_key': 'fs_import_hosts_tt',
     'icon': 'bi-cloud-download', 'variant': 'primary', 'order': 10,
     'perm': 'devices_edit', 'fn': 'freshserviceImportHosts',
     'ready': is_configured},
]


# ── Y el de traer las CLASES, en la pantalla de clases ───────────────────────────────────
#
# Otro acto y otra pantalla: una casa que ya tiene su inventario en Freshservice tiene ahí
# escritas las clases que usa —«Access Point», «IP Phone», «Controladora»— y teclearlas otra vez
# aquí es tener dos listas, que es una que se queda vieja sin avisar.
#
# Se puede pedir **sin traer un solo dispositivo**: el catálogo de tipos es un recurso aparte y
# una sola llamada.
DEVICE_TYPE_ACTIONS = [
    {'id': 'import', 'label_key': 'fs_import_types', 'tooltip_key': 'fs_import_types_tt',
     'icon': 'bi-cloud-download', 'variant': 'secondary', 'order': 10,
     'perm': 'devices_edit', 'fn': 'freshserviceImportTypes',
     'ready': is_configured},
    # Y atar una clase que YA se escribió aquí a una de allí. `link` la pone dentro del cuadro de
    # la clase en vez de en la barra: es un acto sobre UNA, y su `fn` recibe cuál.
    #
    # Hace falta porque el nombre no basta: quien escribió «Punto de acceso» y allí se llama
    # «Access Point» se encontraría una segunda clase en la primera importación, con la mitad de
    # los dispositivos nuevos yendo a cada una. Atándolas, la importación la reconoce.
    {'id': 'link', 'link': True, 'label_key': 'fs_link_type', 'tooltip_key': 'fs_link_type_tt',
     'icon': 'bi-link-45deg', 'variant': 'secondary', 'order': 20,
     'perm': 'devices_edit', 'fn': 'freshserviceLinkType',
     'ready': is_configured},
]


# De dónde vino un dispositivo, para que su ficha pueda decirlo con un nombre y un icono en vez
# de con el identificador `freshservice`. Aparte de `ORG_SOURCES` porque son dos preguntas: un
# proveedor puede traer las empresas y no los dispositivos.
DEVICE_SOURCES = [
    {'id': 'freshservice', 'label_key': 'fs_source', 'icon': 'bi-life-preserver'},
]

# El mismo registro sirve para las CLASES de dispositivo, que también pueden venir de aquí: la
# pantalla de clases enseña de dónde salió cada una, y ningún texto del core nombra a un
# proveedor. Se reutiliza el de arriba en vez de declarar un tercero — es el mismo origen
# diciendo el mismo nombre, y dos declaraciones son dos que se separan.
DEVICE_TYPE_SOURCES = DEVICE_SOURCES


# Lo que este paquete escribe en el registro de auditoría, y cuánto pesa cada línea. Declarado y
# no adivinado del nombre: el color es lo único que da una ojeada a doscientas filas.
AUDIT_EVENTS = [
    # Traer la lista. `info` y no `muted`: crea sociedades y corrige nombres que después salen en
    # las chapas de cuarenta armarios, y «¿desde cuándo se llama así?» se pregunta meses después.
    {'key': 'freshservice_import', 'severity': 'info'},
    # Y probar la conexión. `muted`, pero se apunta: es una petición que este servidor hace a la
    # máquina de otro con una credencial, y eso es lo que se mira cuando alguien pregunta por qué
    # se está llamando desde aquí.
    {'key': 'freshservice_test', 'severity': 'muted'},
    # Traer los dispositivos. `info`, como las empresas y por lo mismo: crea fichas que después
    # salen en la lista de todo el mundo y a las que alguien engancha checks, y «¿de dónde ha
    # salido esta máquina?» se pregunta meses después.
    {'key': 'freshservice_import_hosts', 'severity': 'info'},
]


# ── De dónde vienen las empresas que este proveedor trae ─────────────────────────────────
#
# La columna `source` de una empresa guarda `freshservice`, y la pantalla de Empresas tiene que
# poder enseñar un nombre y un icono sin que el core escriba ninguno: ningún texto del core
# nombra a un proveedor. Se declara aquí, como los ámbitos, y quien lo dibuja no sabe de quién es.
ORG_SOURCES = [
    {'id': 'freshservice', 'label_key': 'fs_source', 'icon': 'bi-life-preserver'},
]
