"""MySQL/PostgreSQL portability regression tests.

Production runs on MySQL and PostgreSQL, but the suite exercises SQLite (which tolerates
bare reserved-word identifiers). These tests drive each store against a recording stub
connector reporting ``KIND='mysql'`` (backtick quoting) and assert the raw SQL quotes the
reserved-word identifiers — so a future bare `key`/`virtual`/`groups`/`user` is caught here.
"""
import contextlib
import re



class _RecConn:
    """Minimal BaseConnector-shaped stub that records every SQL string it's given."""
    KIND = 'mysql'

    def __init__(self):
        self.sql = []

    def quote_ident(self, name):
        return f'`{name}`'

    def reconcile_table(self, spec):
        pass

    def execute(self, sql, params=()):
        self.sql.append(sql); return 0

    def executemany(self, sql, params_list=()):
        self.sql.append(sql); return 0

    def fetchone(self, sql, params=()):
        self.sql.append(sql); return None

    def fetchall(self, sql, params=()):
        self.sql.append(sql); return []

    def commit(self):
        pass

    def last_insert_id(self):
        return 1

    @contextlib.contextmanager
    def transaction(self):
        yield


def _bare(word, sql):
    """True if *word* appears as a standalone identifier NOT wrapped in backticks."""
    return bool(re.search(rf'(?<![`\w]){word}(?![`\w])', sql))


def test_check_state_quotes_key_on_mysql():
    from lib.services.monitoring.check_state.store import CheckStateStore
    c = _RecConn(); s = CheckStateStore(c)
    s.get_all(); s.set('mod', 'k', True); s.delete('mod', 'k')
    s.persist_status({'mod': {'k': {'status': True}}})
    sql = '\n'.join(c.sql)
    assert '`key`' in sql and not _bare('key', sql)


def test_history_quotes_key_on_mysql():
    from lib.core.history.store import HistoryStore
    c = _RecConn(); s = HistoryStore(c)
    s.record('mod', 'k', status=True, data={})
    s.get_index(); s.query('mod', 'k', 0, 9); s.get_stats('mod', 'k', 0, 9)
    s.latest_by_series(); s.latest_by_series(['mod'])
    s.delete_series('mod', 'k')
    sql = '\n'.join(c.sql)
    assert '`key`' in sql and not _bare('key', sql)


def test_devices_quotes_virtual_on_mysql():
    from lib.core.devices.stores import DevicesStore
    c = _RecConn(); s = DevicesStore(c)
    s.list(); s.get('x'); s.create({'name': 'n'}, actor='a'); s.update('x', {'name': 'n'}, actor='a')
    sql = '\n'.join(c.sql)
    assert '`virtual`' in sql and not _bare('virtual', sql)


def test_audit_quotes_user_on_mysql():
    from lib.core.audit.store import AuditStore
    c = _RecConn(); s = AuditStore(c)
    s.insert('ts', 'ev', 'bob', 'ip', {}); s.get_all(); s.query_since(0)
    sql = '\n'.join(c.sql)
    assert '`user`' in sql and not _bare('user', sql)


def test_groups_quotes_groups_table_on_mysql():
    from lib.core.groups.store import GroupsStore
    c = _RecConn(); s = GroupsStore(c)
    s.load(); s.count(); s.apply({'u1': {'name': 'g', 'roles': ['r1']}})
    sql = '\n'.join(c.sql)
    assert '`groups`' in sql and not _bare('groups', sql)   # groups_roles is fine (compound)


def test_revisions_quotes_by_on_mysql():
    """`dc_rev.by` es la mitad de `GROUP BY`, y se metía cruda en cada INSERT y SELECT.

    Comprobado contra MariaDB 11.8.6: `SELECT uid, by FROM ...` es error de sintaxis 1064.
    El historial de versiones del inventario no existía fuera de SQLite, **y no daba ningún
    fallo visible** — las rutas capturan, así que la ficha salía sin versiones, como si nadie
    la hubiera tocado nunca. Lo destapó el barrido de lecturas del motor vivo, una vez que
    dejó de atascarse antes de llegar aquí.
    """
    from lib.core.dcim.revisions import RevisionStore
    c = _RecConn(); s = RevisionStore(c)
    s.keep('ref1', {'a': 1}, actor='bob'); s.history('ref1'); s.get('u1'); s.forget('ref1')
    sql = '\n'.join(c.sql)
    assert '`by`' in sql and not _bare('by', sql)


def test_files_quotes_stored_on_mysql():
    """`stored` **no** rompe en MariaDB 11.8 —preguntado al motor— pero es la misma forma
    que dejó `dc_rev` sin funcionar: la lista de columnas metida cruda en el SQL. Qué
    palabras reserva cada versión de cada motor no lo elige este código."""
    from lib.core.dcim.files import FileStore
    c = _RecConn(); s = FileStore(c)
    s.of('ref1'); s.get('u1')
    sql = '\n'.join(c.sql)
    assert '`stored`' in sql and not _bare('stored', sql)


def test_every_reserved_column_name_has_a_guard_here():
    """La guarda de la clase, no del caso.

    Las cinco pruebas de arriba nombraban `key`, `virtual`, `user` y `groups` — las que ya
    se habían roto. `by` entró después, no estaba en la lista, y nadie lo notó hasta que un
    motor de verdad lo escupió. Esto obliga a pasar por aquí: una columna nueva con nombre
    reservado no puede existir sin que este fichero la nombre entrecomillada.
    """
    import ast                                                        # noqa: PLC0415
    import io as _io                                                  # noqa: PLC0415
    import os as _os                                                  # noqa: PLC0415

    src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
    aqui = _io.open(_os.path.abspath(__file__), encoding='utf-8').read()
    sin_guarda = []
    for carpeta, _dirs, ficheros in _os.walk(_os.path.join(src, 'lib')):
        for f in ficheros:
            if not f.endswith('.py'):
                continue
            ruta = _os.path.join(carpeta, f)
            try:
                arbol = ast.parse(_io.open(ruta, encoding='utf-8').read())
            except SyntaxError:                    # pragma: no cover - fuente roto
                continue
            for n in ast.walk(arbol):
                if (isinstance(n, ast.Call) and getattr(n.func, 'id', '') == 'Column'
                        and n.args and isinstance(n.args[0], ast.Constant)):
                    col = str(n.args[0].value).lower()
                    if col in _RESERVADAS and f'`{col}`' not in aqui:
                        sin_guarda.append(
                            f'{_os.path.relpath(ruta, src)}:{n.lineno} -> {col}')
    assert not sin_guarda, (
        'columnas con nombre reservado en MySQL sin guarda en este fichero: '
        + '; '.join(sorted(set(sin_guarda)))
        + ' - añade un test que ejecute su almacén contra _RecConn y compruebe que el '
          'nombre sale entrecomillado')


#: Palabras reservadas de MySQL 8 / MariaDB que alguien podría usar como nombre de columna.
#: No es la lista entera del manual: es la parte que se solapa con el vocabulario de este
#: producto — `data`, `status` o `name` no están porque ningún motor las reserva.
_RESERVADAS = frozenset('''
    add all alter and as asc before between both by call cascade case change char check
    collate column condition constraint continue convert create cross cursor database
    default delete desc describe distinct div drop each else exists exit explain false
    fetch float for force foreign from group having if ignore in index inner insert int
    integer interval into is join key keys kill leading leave left like limit lines load
    lock long loop match natural not null on optimize option or order out outer partition
    precision primary procedure purge range read real references release rename repeat
    replace require restrict return revoke right rows schema select set show smallint
    specific sql ssl starting stored table then to trailing trigger true undo union unique
    unlock update usage use using values varchar varying virtual when where while with
    write xor user session end offset only
'''.split())


def test_quote_ident_is_dialect_aware():
    from lib.db.sqlite import SQLiteConnector
    from lib.db.mysql import MySQLConnector
    from lib.db.postgresql import PostgreSQLConnector
    # instances not needed — quote_ident is a plain method over the class contract
    assert MySQLConnector.quote_ident(object(), 'key') == '`key`'
    assert SQLiteConnector.quote_ident(object(), 'key') == '"key"'
    assert PostgreSQLConnector.quote_ident(object(), 'key') == '"key"'
