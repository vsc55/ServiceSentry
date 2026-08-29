#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the physical-inventory domain owns, and what it writes to the audit log.

Discovered by :func:`lib.core.permissions.discover_permissions` and merged by
:mod:`lib.web_admin.constants`, like every other domain's.

**Reading where something is, is not reading what it is.** ``devices_view`` opens the registry —
addresses, bound credentials, the buttons that change them. Somebody who needs to walk into a
room and find the failing box needs none of that, and the person who plans capacity needs even
less: how many U are free is a fact about a cabinet, not about a machine.

**Moving a device is not changing whose it is.** ``dcim_edit`` reorders the cabinet;
``dcim_org_edit`` moves a piece of property between companies. In a group that means billing,
and it means who can see it — which is why the two are separate flags rather than one "edit".

**And a shared rack is why ownership has a scope of its own.** A cabinet holding equipment of
several companies breaks the assumption that seeing a place means seeing what is in it: somebody
from company B must see the rack, must see that U 12 is taken — otherwise planning is impossible
— and must not see whose it is or what it is called. That is `org.<uid>.view`, minted per company
the same way `server.<uid>.view` is minted per device, and it is the reason this domain is
scoped from its first commit rather than from its fifth: retrofitting it means auditing every
query that returns a list.

Nothing here alerts, and nothing here reaches a device. This package stores what people know.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_dcim',       # i18n key for the role-editor group heading
    'order': 46,                      # right after infrastructure (45): same fleet, other axis
    'permissions': (
        # The inventory, the elevations and the maps. Both roles, like `infra_view`: knowing
        # which rack a machine is in is a read, and it is the read somebody does while walking.
        {'flag': 'dcim_view', 'roles': ('editor', 'viewer')},
        # …and every company's things, rather than only those of the companies granted one by
        # one. Both roles by default, so nothing narrows on the day this lands: a role is
        # narrowed by NOT holding this and holding `org.<uid>.view` instead, which is opt-in
        # and visible in the role editor rather than implied by an absence.
        {'flag': 'dcim_all_view', 'roles': ('editor', 'viewer')},
        # Create and move sites, rooms, racks and items. `editor`: it is a decision about the
        # installation, and a wrong one puts a 2U device in a U that has not got the room.
        {'flag': 'dcim_edit', 'roles': ('editor',)},
        # …and whose each thing is. Its own flag on purpose — see the docstring. No role by
        # default, not even `editor`: in a group this decides what gets billed to whom and who
        # is allowed to see it, which is not the same authority as tidying a cabinet.
        {'flag': 'dcim_org_edit', 'roles': ()},
        # Declare and retire cabling and its labels. `editor`, like moving equipment: it is the
        # same act of recording what somebody did with their hands.
        {'flag': 'dcim_cable_edit', 'roles': ('editor',)},
        # The catalogue of models. Both roles: it is a reference book about equipment in
        # general, and it says nothing about this installation.
        {'flag': 'dcim_catalog_view', 'roles': ('editor', 'viewer')},
        # Importing one. `editor` only: it fetches a few thousand files, runs for minutes and
        # replaces what every elevation is drawn from.
        {'flag': 'dcim_catalog_manage', 'roles': ('editor',)},
        # Los estándares de compra: qué es «un servidor de CPD» en esta casa. Su propia bandera
        # porque DECIDIR lo que se compra y COLOCAR una caja en un U los hacen personas distintas
        # en momentos distintos, y con una sola quien monta un rack rescribe lo que compra la
        # empresa. `editor` de salida: es una decisión técnica, no una de dinero como
        # `dcim_org_edit` — lo que importa es que se pueda quitar sin quitar nada más.
        {'flag': 'dcim_build_edit', 'roles': ('editor',)},
    ),
}


# What this package writes to the audit log, and how loud each one is. Declared rather than
# guessed from the event name: the badge is the only thing a glance down two hundred rows
# gives you, and deriving it from a noun made the colour depend on what somebody called the
# event (see lib/core/audit/events.py).
# Declared HERE and written THERE, and never the other way round: these four went in before
# their writers existed and `test_nothing_is_declared_that_nobody_emits` threw them straight
# back out, which is exactly what it is for — nobody greps for a name that was never used. They
# are back because `routes.py` now writes them.
AUDIT_EVENTS = [
    # Where things are. Ordinary bookkeeping, and there is a lot of it while a room is being
    # entered for the first time.
    {'key': 'dcim_placed', 'severity': 'muted'},
    {'key': 'dcim_removed', 'severity': 'info'},
    # Whose things are. Louder than either: this line is the answer to "since when was that
    # ours", and it is the one somebody goes looking for months later.
    {'key': 'dcim_owner_set', 'severity': 'info'},
    # Asking a GitHub library what it holds. Reading does not get audited, but this is not
    # reading: it is a request this server makes to somebody else's machine, and it can end in
    # "the hour's sixty requests are gone" or "that branch is not there". The line carries the
    # address and, when it went wrong, exactly why — which is the thing that was missing when
    # the screen could only say "Error".
    {'key': 'dcim_catalog_browse', 'severity': 'muted'},
    # Writing or correcting a catalogue model by hand. Louder than muted: it is the answer to
    # "why does this say it is a power supply when the library calls it a device", and the
    # answer is that somebody decided so — a decision that then survives every re-import.
    {'key': 'dcim_catalog_edit', 'severity': 'info'},
    # An import replaces what every elevation is drawn from.
    {'key': 'dcim_catalog_import', 'severity': 'info'},
    # Quitar un modelo suelto. Una importación se rehace; una fila borrada, no — y lo que se
    # va con ella son las imágenes, que ningún otro sitio guarda.
    {'key': 'dcim_catalog_drop', 'severity': 'info'},
    # Traer los esquemas de la biblioteca, o escribir uno propio. Queda registrado porque
    # cambia lo que TODO el mundo puede teclear en un modelo a partir de ese momento.
    {'key': 'dcim_schema_save', 'severity': 'info'},
    # Escribir o cambiar una plantilla. Es el estándar con el que se van a crear los próximos
    # veinte equipos, así que «desde cuándo el estándar lleva estos discos» tiene que poder
    # contestarse — y no puede contestarlo la plantilla, que solo dice cómo está HOY.
    {'key': 'dcim_build_save', 'severity': 'info'},
    # Escribir o retirar la ficha de un fabricante. No es el catálogo: es lo que esta casa sabe
    # de ellos —dónde se abre un ticket, con qué número de cliente— y no lo trae ninguna
    # biblioteca, así que no se puede volver a descargar.
    {'key': 'dcim_brand_save', 'severity': 'info'},
    {'key': 'dcim_platform_save', 'severity': 'info'},
    # Cambiar qué se pregunta de un componente. Es lo que TODO el mundo va a poder teclear a
    # partir de ese momento, igual que traer los esquemas de la biblioteca — y aquí además puede
    # llegar por un fichero que alguien sube, así que quién y cuándo importa.
    {'key': 'dcim_profiles_save', 'severity': 'info'},
    # Retirar una. Los equipos que salieron de ella siguen ahí y siguen diciendo de cuál
    # nacieron; lo que se pierde es poder mirar de qué constaba.
    {'key': 'dcim_build_drop', 'severity': 'info'},
    # Echar o quitar el bypass de un SAI no es editar un campo: es una maniobra eléctrica que
    # deja sin protección a todo lo que cuelga de él, y quién la hizo y cuándo es lo primero que
    # se pregunta cuando algo se apaga tres meses después.
    {'key': 'dcim_bypass', 'severity': 'warning'},
    # Llevarse modelos y plantillas a un fichero. `info` y no `warning`: no cambia nada
    # aquí. Se apunta porque lo que sale es el estándar de compra de la casa, y de eso
    # la pregunta que se hace luego es quién se lo llevó y cuándo.
    {'key': 'dcim_export', 'severity': 'info'},
    # Y traerlos. Escribe filas que nadie ha tecleado aquí, así que de dónde salieron es
    # justo lo que no va a estar escrito en ninguna de ellas.
    {'key': 'dcim_import', 'severity': 'info'},
]


# ── Tables this package keeps in the shared database ─────────────────────────────────────
#
# Declared for the sake of STARTUP. Each store reconciles its own table when it is built, but
# it is built on demand — a request that draws a room, an import that fills the catalogue — and
# the two ways of arriving there are not equally forgiving.
from .builds import SCHEMAS as _BUILDS         # noqa: E402
from .catalog import SCHEMA as _CATALOG        # noqa: E402
from .files import SCHEMA as _FILES            # noqa: E402
from .profiles import SCHEMA as _PROFILES      # noqa: E402
from .revisions import SCHEMA as _REVS          # noqa: E402
from .brands import SCHEMA as _BRANDS          # noqa: E402
from .schemas import SCHEMA as _SCHEMAS        # noqa: E402
from .store import SCHEMAS as _INVENTORY       # noqa: E402

DB_TABLES = (list(_INVENTORY) + list(_BUILDS)
             + [_BRANDS, _CATALOG, _REVS, _SCHEMAS, _PROFILES, _FILES])

# What this package runs in the background, for the screen that lists all of it
# (lib/core/jobs). Declared rather than reached into: a core that imported four job
# registries by name would have to be edited to learn about a fifth.
from .jobs import live as BACKGROUND_JOBS      # noqa: E402,F401  (a descriptor)
