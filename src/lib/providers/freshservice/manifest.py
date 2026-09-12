#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que este proveedor aporta (ver `lib/discovery.py`).

Dos botones en su tarjeta de configuración y dos líneas de auditoría. Nada más: la sección de
Empresas no sabe que esto existe, y este paquete no aparece nombrado en ninguna pantalla del core
— se declara, y el panel lo dibuja.

El JavaScript que se nombra aquí viaja con el paquete (`web/_ui.html`), que es lo que permite
quitar el proveedor entero borrando su carpeta.
"""

# ── Botones en la tarjeta «Freshservice» de la configuración ─────────────────────────────
#
# Probar, y traer. En ese orden y separados a propósito: comprobar la conexión mientras se teclea
# la clave es una pregunta, e importar es un acto — y con un solo botón, quien sólo quería saber
# si la clave vale se encuentra con cuarenta empresas creadas.
#
# Los dos piden `orgs_edit`, que es la misma bandera que exige el servidor. La de aquí es una
# reja encima de esa, nunca en su lugar.
CONFIG_ACTIONS = [
    {'section': 'freshservice', 'id': 'test',
     'label_key': 'fs_test', 'tooltip_key': 'fs_test_tt',
     'icon': 'bi-plug', 'variant': 'secondary', 'order': 10,
     'perm': 'orgs_edit', 'group_label_key': 'fs_actions',
     'fn': 'freshserviceTest',
     # Tras el dominio: sin él no hay a quién llamar, y es lo que dice si esto está puesto.
     'show_when': {'field': 'domain', 'not_empty': True}},
    {'section': 'freshservice', 'id': 'import',
     'label_key': 'fs_import', 'tooltip_key': 'fs_import_tt',
     'icon': 'bi-cloud-download', 'variant': 'primary', 'order': 20,
     'perm': 'orgs_edit', 'group_label_key': 'fs_actions',
     'fn': 'freshserviceImport',
     'show_when': {'field': 'domain', 'not_empty': True}},
]


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
]


# ── De dónde vienen las empresas que este proveedor trae ─────────────────────────────────
#
# La columna `source` de una empresa guarda `freshservice`, y la pantalla de Empresas tiene que
# poder enseñar un nombre y un icono sin que el core escriba ninguno: ningún texto del core
# nombra a un proveedor. Se declara aquí, como los ámbitos, y quien lo dibuja no sabe de quién es.
ORG_SOURCES = [
    {'id': 'freshservice', 'label_key': 'fs_source', 'icon': 'bi-life-preserver'},
]
