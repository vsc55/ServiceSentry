#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qué se hace con lo que llega de Freshservice — sin red y sin base de datos.

Todo lo que puede equivocarse de una importación está en el emparejamiento: qué es nuevo, qué es
lo mismo con otro nombre, qué no hay que tocar y qué se ha quedado sin origen. Eso se prueba con
dos listas y ningún servidor, y por eso vive en un módulo que no sabe ni pedir una página.

Lo que se fija aquí son las tres reglas que en otros sitios han salido mal:

* se empareja por el **identificador de allí**, nunca por el nombre;
* lo que **tecleó una persona** no se pisa;
* lo que **no cambió** no viaja.
"""

from lib.providers.freshservice import plan as fs


def _org(uid, name, short='', desc='', source='', ext=''):
    return {'uid': uid, 'name': name, 'short': short, 'description': desc,
            'source': source, 'external_id': ext}


def _dep(i, name, desc=''):
    return {'id': i, 'name': name, 'description': desc}


class TestLaAbreviaturaSeSacaDelNombre:
    """Freshservice no tiene ese campo y aquí es obligatorio: es lo que cabe en la chapa de un
    alzado, donde el nombre legal de una sociedad no entra."""

    def test_las_iniciales_cuando_hay_varias_palabras(self):
        assert fs.short_for('Mirasol Food', []) == 'MF'
        assert fs.short_for('3D Modular', []) == '3M'

    def test_y_las_primeras_letras_cuando_es_una(self):
        assert fs.short_for('Avellana', []) == 'AVELLANA'

    def test_y_nunca_mas_larga_de_lo_que_cabe(self):
        larga = fs.short_for('Sociedad Anonima De Trabajos Y Obras Del Levante Español', [])
        assert len(larga) <= fs.SHORT_MAX

    def test_y_sin_acentos_ni_eñes(self):
        """Una chapa se lee a dos metros y se graba en una etiquetadora que a veces no tiene
        más que ASCII."""
        assert fs.short_for('Peña Ubiña', []) == 'PU'
        assert fs.short_for('Álava', []) == 'ALAVA'

    def test_y_si_ya_está_cogida_no_se_repite(self):
        """Dos chapas iguales en un armario compartido no dicen de quién es cada equipo."""
        assert fs.short_for('Mirasol Food', ['MF']) == 'MF2'
        assert fs.short_for('Mirasol Food', ['MF', 'MF2']) == 'MF3'

    def test_y_da_igual_como_esté_escrita_la_que_ya_estaba(self):
        assert fs.short_for('Mirasol Food', [' mf ']) == 'MF2'

    def test_y_un_nombre_sin_letras_no_deja_a_nadie_sin_abreviatura(self):
        assert fs.short_for('###', []) == 'ORG'


class TestSeEmparejaPorElIdentificadorDeAlli:

    def test_lo_que_no_esta_se_crea(self):
        p = fs.build([_dep(1, 'Filial B', 'la del norte')], [])
        assert [x['action'] for x in p] == ['create']
        assert p[0]['external_id'] == '1' and p[0]['short'] == 'FB'

    def test_y_lo_que_esta_se_reconoce_aunque_lo_hayan_renombrado(self):
        """Es la razón de guardar el identificador: por el nombre, renombrarla allí crearía aquí
        una segunda y dejaría la primera huérfana, sin que nada lo dijera."""
        ya = _org('u1', 'Filial B', 'FB', '', fs.SOURCE, '1')
        p = fs.build([_dep(1, 'Filial B del Norte')], [ya])
        assert [x['action'] for x in p] == ['update']
        assert p[0]['uid'] == 'u1'
        assert p[0]['was']['name'] == 'Filial B'

    def test_y_lo_que_no_cambio_no_viaja(self):
        """Una importación que reescribe cuarenta filas idénticas llena el registro de auditoría
        de cambios que no cambian nada."""
        ya = _org('u1', 'Filial B', 'FB', 'la del norte', fs.SOURCE, '1')
        p = fs.build([_dep(1, 'Filial B', 'la del norte')], [ya])
        assert [x['action'] for x in p] == ['same']

    def test_y_un_departamento_sin_nombre_o_sin_id_no_es_un_departamento(self):
        p = fs.build([_dep(0, 'Sin id'), _dep(2, '   '), _dep(3, 'Buena')], [])
        assert [x['name'] for x in p] == ['Buena']


class TestLoQueTecleoUnaPersonaNoSePisa:

    def test_una_con_el_mismo_nombre_y_sin_origen_se_adopta(self):
        """El caso real: la lista se tecleó a mano antes de conectar esto. Crear una copia
        dejaría dos sociedades iguales y los armarios fichados a la que no toca."""
        suya = _org('u9', 'Filial B', 'FB', 'escrito aquí')
        p = fs.build([_dep(7, 'Filial B', 'lo que dice Freshservice')], [suya])
        assert [x['action'] for x in p] == ['adopt']
        assert p[0]['uid'] == 'u9' and p[0]['external_id'] == '7'

    def test_y_adoptar_deja_dicho_lo_que_habia(self):
        """Se adopta porque el nombre YA coincide, y a partir de ahí la fila la mantiene el
        origen. Lo que había aquí se devuelve en `was` — es lo que la pantalla enseña para que
        quien acepta vea qué se va a quedar por el camino."""
        suya = _org('u9', 'Filial B', 'FB', 'escrito aquí')
        p = fs.build([_dep(7, 'Filial B', 'otra cosa')], [suya])
        assert p[0]['action'] == 'adopt'
        assert p[0]['was'] == {'name': 'Filial B', 'short': 'FB',
                               'description': 'escrito aquí'}
        assert p[0]['description'] == 'otra cosa', 'lo que se va a escribir es lo de allí'

    def test_y_una_de_otro_origen_no_se_toca(self):
        """Si mañana hay un segundo proveedor, lo suyo es suyo: adoptar lo de otro es que dos
        listas se peleen por la misma fila cada vez que se importe."""
        de_otro = _org('u5', 'Filial B', 'FB', '', 'otro_sitio', '99')
        p = fs.build([_dep(7, 'Filial B')], [de_otro])
        assert [x['action'] for x in p] == ['create']

    def test_y_la_abreviatura_de_la_nueva_no_choca_con_las_que_ya_hay(self):
        p = fs.build([_dep(1, 'Mirasol Food')], [_org('u1', 'Mar y Fondo', 'MF')])
        assert p[0]['short'] == 'MF2'


class TestLoQueYaNoEstaSeCuentaYNoSeBorra:
    """De una sociedad cuelgan armarios y máquinas fichados aquí, y un departamento desaparece
    del origen tanto por una reorganización como por un filtro mal puesto. Borrar lo que cuelga
    por una lista que llegó corta es perder trabajo de meses."""

    def test_lo_importado_que_ya_no_llega_sale_en_la_lista(self):
        ya = _org('u1', 'La que se fue', 'LQF', '', fs.SOURCE, '1')
        assert [o['uid'] for o in fs.orphans([_dep(2, 'Otra')], [ya])] == ['u1']

    def test_pero_lo_tecleado_aqui_no_es_huerfano_de_nada(self):
        """Nunca vino de Freshservice: que no esté allí no dice absolutamente nada de ella."""
        suya = _org('u2', 'De aquí de siempre', 'DAS')
        assert fs.orphans([], [suya]) == []


class TestElResumenCuentaLoQueVaAPasar:

    def test_cuantos_de_cada(self):
        orgs = [_org('u1', 'Uno', 'U1', 'igual', fs.SOURCE, '1'),
                _org('u2', 'Dos', 'D', 'vieja', fs.SOURCE, '2'),
                _org('u3', 'Tres', 'T')]
        deps = [_dep(1, 'Uno', 'igual'), _dep(2, 'Dos', 'nueva'),
                _dep(3, 'Tres'), _dep(4, 'Cuatro')]
        assert fs.counts(fs.build(deps, orgs)) == {'create': 1, 'update': 1,
                                                   'adopt': 1, 'same': 1}

    def test_y_sin_nada_que_traer_cuenta_ceros_en_vez_de_no_contestar(self):
        """«No había nada que hacer» es una respuesta, y no verla deja a quien mira
        preguntándose si se importó."""
        assert fs.counts([]) == {'create': 0, 'update': 0, 'adopt': 0, 'same': 0}


class TestSusFechasNoSonNuestrasFechas:
    """Freshservice manda `created_at` y `updated_at` en UTC con la forma
    `YYYY-MM-DDTHH:MM:SSZ` — que da la casualidad de que es **la misma** que escribe este panel.
    Y precisamente por parecerse tanto es por lo que no se copian: esas columnas de aquí dicen
    cuándo lo cambió ESTE panel, y meterles la hora en que lo cambió otro las deja significando
    dos cosas según la fila.

    Está vigilado porque el día que alguien escriba `dict(fila)` en vez de los tres campos, las
    fechas entran solas y no falla nada."""

    def test_el_plan_no_se_trae_ninguna_fecha(self):
        dep = dict(_dep(1, 'Filial B', 'la del norte'),
                   created_at='2016-02-13T23:27:49Z', updated_at='2026-01-02T03:04:05Z')
        p = fs.build([dep], [])
        assert set(p[0]) == {'action', 'external_id', 'name', 'description',
                             'uid', 'short', 'was'}

    def test_ni_ningun_otro_campo_suyo(self):
        """Los departamentos traen jefes, dominios y campos a medida. Nada de eso es una empresa
        de aquí, y colarlo en la fila sería guardar lo de otro sin saber qué significa."""
        dep = dict(_dep(1, 'Filial B'), head_user_id=7, prime_user_id=9,
                   domains=['filialb.example'], custom_fields={'centro_de_coste': 'CC-4'})
        p = fs.build([dep], [])
        assert 'head_user_id' not in p[0] and 'domains' not in p[0]
        assert 'custom_fields' not in p[0]


class TestSeEligeQueSeTrae:
    """Cincuenta y nueve departamentos no son cincuenta y nueve empresas de esta casa. Lo que se
    marca es lo que se trae, y lo que no se marca no existe para la importación."""

    def test_solo_lo_marcado_viaja(self):
        plan = fs.build([_dep(1, 'Una'), _dep(2, 'Otra'), _dep(3, 'Tercera')], [])
        elegido, rechazos = fs.select(plan, pick=['1', '3'])
        assert [p['name'] for p in elegido] == ['Una', 'Tercera']
        assert rechazos == []

    def test_y_sin_decir_nada_se_trae_todo(self):
        """`None` no es lo mismo que «ninguna»: es lo que hacía esto antes de que se pudiera
        elegir, y lo que hace una llamada a la API que no manda la lista."""
        plan = fs.build([_dep(1, 'Una'), _dep(2, 'Otra')], [])
        elegido, _r = fs.select(plan)
        assert len(elegido) == 2
        assert fs.select(plan, pick=[])[0] == []

    def test_y_marcar_una_que_no_cambia_no_la_convierte_en_trabajo(self):
        """«Sin cambios» marcada sigue sin tener nada que hacer: escribirla sería una línea de
        auditoría que no dice nada."""
        ya = _org('u1', 'Una', 'U', 'igual', fs.SOURCE, '1')
        plan = fs.build([_dep(1, 'Una', 'igual')], [ya])
        assert fs.select(plan, pick=['1'])[0] == []


class TestEmparejarAManoLoQueElPanelNoPuedeSaber:
    """Que «Avellana Energy Supplies, S.L.» de allí y «Avellana» de aquí son la misma casa lo
    sabe quien lo mira. Ningún parecido de nombres lo va a decir nunca — y adivinarlo sería
    peor: uniría dos que sólo se parecen."""

    def test_una_nueva_pasa_a_adoptar_la_que_se_le_diga(self):
        suya = _org('u9', 'Avellana', 'AVL')
        plan = fs.build([_dep(7, 'Avellana Energy Supplies, S.L.')], [suya])
        assert plan[0]['action'] == 'create'
        elegido, rechazos = fs.select(plan, pick=['7'], link={'7': 'u9'}, orgs=[suya])
        assert rechazos == []
        assert elegido[0]['action'] == 'adopt' and elegido[0]['uid'] == 'u9'

    def test_y_manda_sobre_lo_que_se_hubiera_deducido(self):
        """Si alguien dice que esas dos son la misma, es que lo son."""
        otra = _org('u1', 'Filial B', 'FB')
        suya = _org('u2', 'La que yo digo', 'LQD')
        plan = fs.build([_dep(7, 'Filial B')], [otra, suya])
        assert plan[0]['action'] == 'adopt' and plan[0]['uid'] == 'u1'
        elegido, _r = fs.select(plan, pick=['7'], link={'7': 'u2'}, orgs=[otra, suya])
        assert elegido[0]['uid'] == 'u2'

    def test_pero_una_ya_atada_a_otro_departamento_se_rechaza(self):
        """Dos no pueden compartir una: el segundo le pisaría el nombre al primero en cada
        importación, y la fila iría cambiando de nombre sola."""
        ocupada = _org('u1', 'Ya es de otro', 'YEO', '', fs.SOURCE, '99')
        plan = fs.build([_dep(7, 'Nueva')], [ocupada])
        elegido, rechazos = fs.select(plan, pick=['7'], link={'7': 'u1'}, orgs=[ocupada])
        assert elegido == []
        assert rechazos == [{'name': 'Nueva', 'reason': 'fs_link_taken'}]

    def test_y_una_que_ya_no_existe_tambien(self):
        """Se pudo borrar entre mirar y aceptar."""
        plan = fs.build([_dep(7, 'Nueva')], [])
        elegido, rechazos = fs.select(plan, pick=['7'], link={'7': 'fantasma'}, orgs=[])
        assert elegido == [] and rechazos[0]['reason'] == 'fs_link_gone'

    def test_y_un_rechazo_no_es_lo_mismo_que_no_haberla_elegido(self):
        """Lo primero se pidió y no salió, y hay que contarlo con su motivo; lo segundo no
        existe. Devolverlos juntos sería no poder distinguirlos."""
        ocupada = _org('u1', 'Ya es de otro', 'YEO', '', fs.SOURCE, '99')
        plan = fs.build([_dep(7, 'Pedida'), _dep(8, 'Ni marcada')], [ocupada])
        elegido, rechazos = fs.select(plan, pick=['7'], link={'7': 'u1'}, orgs=[ocupada])
        assert [r['name'] for r in rechazos] == ['Pedida']
        assert elegido == []


class TestAdoptarTraeLosDatos:
    """Atar una empresa de aquí a un departamento de allí es decir «estas dos son la misma». A
    partir de ese momento la mantiene el origen, así que sus datos son los de allí.

    Guardar sólo el atado y respetar lo de aquí era una seguridad de mentira: la siguiente
    importación le habría pisado el nombre igual. Lo único que se conseguía era que el cambio
    llegara el día que nadie lo estaba mirando."""

    def test_el_nombre_y_la_descripcion_son_los_de_alli(self):
        suya = _org('u9', 'Avellana', 'AVL', 'lo de siempre')
        plan = fs.build([_dep(7, 'Avellana Energy Supplies, S.L.', 'fotovoltaica')], [suya])
        elegido, _r = fs.select(plan, pick=['7'], link={'7': 'u9'}, orgs=[suya])
        assert elegido[0]['name'] == 'Avellana Energy Supplies, S.L.'
        assert elegido[0]['description'] == 'fotovoltaica'

    def test_y_la_abreviatura_se_rehace_si_el_nombre_cambia(self):
        """Freshservice no tiene ese campo, así que no hay nada que descargar — pero una
        abreviatura son las iniciales de un nombre, y dejar «AVL» sobre «Avellana Energy
        Supplies, S.L.» es una chapa que ya no dice lo que pone la fila."""
        suya = _org('u9', 'Avellana', 'AVL')
        plan = fs.build([_dep(7, 'Avellana Energy Supplies, S.L.')], [suya])
        elegido, _r = fs.select(plan, pick=['7'], link={'7': 'u9'}, orgs=[suya])
        assert elegido[0]['short'] == 'AESSL'

    def test_pero_se_queda_la_de_aqui_si_el_nombre_no_cambia(self):
        """La eligió una persona para leerla en un armario a dos metros, y sigue siendo la de
        ese nombre."""
        suya = _org('u9', 'Filial B', 'FB')
        plan = fs.build([_dep(7, 'Filial B', 'otra cosa')], [suya])
        elegido, _r = fs.select(plan, pick=['7'], link={'7': 'u9'}, orgs=[suya])
        assert elegido[0]['short'] == 'FB'

    def test_y_no_choca_con_las_que_ya_hay(self):
        vecina = _org('u1', 'Avellana Energy Solutions', 'AESSL')
        suya = _org('u9', 'Avellana', 'AVL')
        plan = fs.build([_dep(7, 'Avellana Energy Supplies, S.L.')], [vecina, suya])
        elegido, _r = fs.select(plan, pick=['7'], link={'7': 'u9'}, orgs=[vecina, suya])
        assert elegido[0]['short'] != 'AESSL'


class TestDosDepartamentosNoSeQuedanConLaMismaEmpresa:
    """Dos departamentos que se llaman igual (o dos emparejamientos a mano con la misma
    empresa) salían los dos como `adopt` sobre la misma fila: el segundo le pisaba el
    `external_id` al primero, y en cada importación la empresa cambiaba de dueño."""

    def test_el_segundo_con_el_mismo_nombre_es_un_conflicto(self):
        orgs = [_org('u1', 'Avellana')]
        plan = fs.build([_dep(1, 'Avellana'), _dep(2, 'AVELLANA')], orgs)
        acciones = {p['external_id']: p['action'] for p in plan}
        assert acciones == {'1': 'adopt', '2': 'conflict'}
        assert [p['uid'] for p in plan if p['action'] == 'adopt'] == ['u1']

    def test_y_el_conflicto_no_se_aplica_se_cuenta(self):
        orgs = [_org('u1', 'Avellana')]
        plan = fs.build([_dep(1, 'Avellana'), _dep(2, 'Avellana')], orgs)
        fuera, rechazos = fs.select(plan, orgs=orgs)
        assert [p['external_id'] for p in fuera] == ['1']
        assert rechazos == [{'name': 'Avellana', 'reason': 'fs_link_taken'}]

    def test_y_se_resuelve_emparejandolo_a_mano_con_otra(self):
        orgs = [_org('u1', 'Avellana'), _org('u2', 'Avellana Energy')]
        plan = fs.build([_dep(1, 'Avellana'), _dep(2, 'Avellana')], orgs)
        fuera, rechazos = fs.select(plan, link={'2': 'u2'}, orgs=orgs)
        assert sorted((p['external_id'], p['uid']) for p in fuera) == [('1', 'u1'), ('2', 'u2')]
        assert rechazos == []

    def test_dos_emparejamientos_a_mano_con_la_misma_empresa(self):
        orgs = [_org('u1', 'Avellana')]
        plan = fs.build([_dep(1, 'Uno'), _dep(2, 'Dos')], orgs)
        fuera, rechazos = fs.select(plan, link={'1': 'u1', '2': 'u1'}, orgs=orgs)
        assert [p['uid'] for p in fuera] == ['u1'] and len(fuera) == 1
        assert rechazos == [{'name': 'Dos', 'reason': 'fs_link_taken'}]

    def test_uno_a_mano_contra_la_que_otro_adopta_solo(self):
        orgs = [_org('u1', 'Avellana')]
        plan = fs.build([_dep(1, 'Avellana'), _dep(2, 'Otra')], orgs)
        fuera, rechazos = fs.select(plan, link={'2': 'u1'}, orgs=orgs)
        assert [p['uid'] for p in fuera if p['uid']] == ['u1']
        assert len(rechazos) == 1 and rechazos[0]['reason'] == 'fs_link_taken'

    def test_el_resumen_cuenta_el_conflicto_solo_si_lo_hay(self):
        orgs = [_org('u1', 'Avellana')]
        assert fs.counts(fs.build([_dep(1, 'Avellana'), _dep(2, 'Avellana')], orgs)) \
            == {'create': 0, 'update': 0, 'adopt': 1, 'same': 0, 'conflict': 1}
