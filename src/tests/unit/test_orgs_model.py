#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las empresas: quién ve qué, y qué puede ser de quién.

Estas reglas vivían dentro del inventario físico, que es donde se hizo la pregunta por primera
vez. Era un accidente de calendario: la misma sociedad que paga el armario tiene usuarios en el
directorio y licencias en Microsoft 365, y las reglas de «de quién es esto y puedo verlo» no
pueden estar dentro de una sección si las demás las necesitan.

Sin base de datos y sin aplicación: lo que se comprueba aquí es aritmética de conjuntos y una
lista de ámbitos declarados. Lo que necesita filas está en `tests/integration/test_wa_orgs.py`.
"""

from lib.core.orgs import owners, scopes


class TestElContenedorCompartidoEsElCasoDuro:
    """Un armario con equipos de varias sociedades rompe la suposición de que ver un sitio es
    ver lo que hay dentro: alguien de la filial B tiene que ver el armario y que el U 12 está
    ocupado —si no, planificar es imposible— y no tiene que ver de quién es ni cómo se llama.

    La misma forma aparece en cuanto un segundo paquete ficha algo: un inquilino compartido
    entre dos filiales, una suscripción que paga otro.
    """

    def test_quien_lo_tiene_todo_lo_ve_todo(self):
        assert owners.visible_orgs({'orgs_all_view'}) is None
        assert owners.may_see('cualquiera', None) is True

    def test_sin_ninguna_empresa_no_es_lo_mismo_que_sin_acceso(self):
        """`None` y `set()` son respuestas distintas a propósito: la segunda es alguien a quien
        se le dio una sección y ninguna empresa, que debe ver los contenedores con todo opaco —
        no un error. Tratarlo como «sin acceso» deja fuera justo a quien se inventó el ámbito."""
        allowed = owners.visible_orgs({'orgs_view'})
        assert allowed == set()
        assert owners.may_see('org-a', allowed) is False

    def test_el_ambito_por_empresa_se_lee_de_los_permisos(self):
        allowed = owners.visible_orgs({'orgs_view', 'org.org-a.view', 'server.h1.view'})
        assert allowed == {'org-a'}
        assert owners.may_see('org-a', allowed) is True
        assert owners.may_see('org-b', allowed) is False

    def test_y_el_permiso_de_un_dispositivo_no_se_cuela_por_parecido(self):
        """`server.<uid>.view` tiene la misma forma y no es lo mismo: si colase, conceder una
        máquina concedería una empresa que ni existe."""
        assert owners.visible_orgs({'server.h1.view', 'org..view'}) == set()

    def test_lo_que_nadie_reclama_lo_ve_cualquiera(self):
        """Algo sin fichar no es un secreto: es algo que nadie ha archivado todavía, que es el
        estado de toda instalación el primer día — y de casi toda el segundo."""
        assert owners.may_see('', {'org-a'}) is True


class TestLoDichoManda:
    """Se dice donde alguien lo sepa y se hereda hacia dentro, gana lo más cercano."""

    def test_gana_lo_mas_cercano(self):
        cadena = [('item', 'i1'), ('rack', 'r1'), ('room', 's1'), ('site', 'x1')]
        dicho = {('site', 'x1'): 'org-it', ('item', 'i1'): 'org-b'}
        assert owners.owner_of(cadena, dicho) == 'org-b'

    def test_y_si_nadie_lo_dijo_de_cerca_se_hereda(self):
        cadena = [('item', 'i1'), ('rack', 'r1'), ('room', 's1'), ('site', 'x1')]
        assert owners.owner_of(cadena, {('site', 'x1'): 'org-it'}) == 'org-it'

    def test_y_si_nadie_lo_dijo_nunca_no_es_de_nadie(self):
        """Y «de nadie» no es un error ni un dueño llamado vacío: es el estado normal."""
        assert owners.owner_of([('item', 'i1'), ('rack', 'r1')], {}) == ''

    def test_y_una_cadena_rota_termina_en_vez_de_estallar(self):
        """Un armario cuya sala se borró es un estado real de los datos, y la respuesta para él
        es «no se sabe», no un 500."""
        assert owners.owner_of([], {('site', 'x1'): 'org-it'}) == ''


class TestQuePuedeSerDeUnaEmpresaLoDiceQuienLoTiene:
    """La tabla de pertenencia abarca ámbitos que viven en tablas que este paquete no conoce,
    así que la lista no puede estar en él: sería una que el core edita cada vez que un paquete
    aprende a poseer algo, que es el core nombrando un dominio."""

    def test_los_declaran_los_paquetes_y_no_el_core(self):
        registro = scopes.registry()
        # Los cuatro de la contención física los declara el inventario…
        for ambito in ('site', 'room', 'rack', 'item'):
            assert registro[ambito]['package'] == 'dcim', ambito
        # …y la máquina la declara el registro de máquinas, que es de quien es.
        assert registro['host']['package'] == 'hosts'

    def test_y_ninguno_llega_sin_nombre_traducible(self):
        """La pantalla cuenta «3 armarios» sin saber qué es un armario: el texto sale de la
        clave que declara quien lo tiene, y una sin clave saldría en crudo."""
        for ambito, spec in scopes.registry().items():
            assert spec.get('label_key'), ambito

    def test_y_lo_que_nadie_declara_no_se_puede_fichar(self):
        """Lo que impide que una errata escriba una fila que nada podrá volver a leer."""
        assert scopes.known('rack') is True
        assert scopes.known('sala_de_maquinas') is False
        assert scopes.known('') is False

    def test_una_maquina_no_hereda_de_nada_y_eso_es_una_respuesta(self):
        """Un `host` no tiene contenedor del que heredar: es de quien se dijo, y de nadie si no
        se dijo. Contestar consigo mismo es lo que hace que resuelva igual que los demás."""
        assert scopes.chain_of(None, 'host', 'h1') == [('host', 'h1')]

    def test_y_un_ambito_que_no_existe_no_estalla_al_resolverse(self):
        assert scopes.chain_of(None, 'inventado', 'x') == [('inventado', 'x')]
        assert scopes.chain_of(None, 'host', '') == []


class TestLasBanderasSonDelCoreYNoDeUnaSeccion:

    def test_son_estas_tres(self):
        from lib.core.orgs.manifest import MODULE_PERMISSIONS
        flags = [p['flag'] for p in MODULE_PERMISSIONS['permissions']]
        assert flags == ['orgs_view', 'orgs_all_view', 'orgs_edit']

    def test_decidir_de_quien_es_algo_no_se_regala_con_ningun_rol(self):
        """En un grupo esto decide qué se le factura a qué sociedad y quién puede ver qué, que
        no es la misma autoridad que ordenar un armario."""
        from lib.core.orgs.manifest import MODULE_PERMISSIONS
        roles = {p['flag']: p['roles'] for p in MODULE_PERMISSIONS['permissions']}
        assert roles['orgs_edit'] == ()
        # …y lo que es una lectura sí llega a quien solo mira.
        assert 'viewer' in roles['orgs_view'] and 'viewer' in roles['orgs_all_view']

    def test_y_la_de_verlo_todo_termina_en_view(self):
        """`viewer` siendo de solo lectura es una invariante de NOMBRE: toda bandera que ese rol
        trae acaba en `_view`, que es lo que hace contestable «¿este rol es de solo lectura?»
        mirando en vez de leyendo seis manifiestos (tests/unit/test_wa_roles.py)."""
        assert owners.ALL_ORGS_PERM.endswith('_view')

    def test_y_un_rol_guardado_no_pierde_lo_que_tenia(self):
        """Las banderas se llamaban `dcim_all_view` y `dcim_org_edit`. Un renombre sin migración
        es un permiso que desaparece de un rol sin que nada lo diga — y lo que desaparece aquí
        es quién puede ver las cosas de qué sociedad."""
        from lib.core.roles.mixin import _LEGACY_PERM_RENAME
        assert _LEGACY_PERM_RENAME['dcim_all_view'] == 'orgs_all_view'
        assert _LEGACY_PERM_RENAME['dcim_org_edit'] == 'orgs_edit'
