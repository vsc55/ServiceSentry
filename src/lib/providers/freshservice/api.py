#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La API de Freshservice: lo que es cierto de TODA ella, escrito una vez.

Aquí no hay ni un departamento. Lo que hay es el contrato —cómo se llama, cómo contesta, cómo
falla y cómo se pagina—, para que traer agentes, activos o tickets mañana sea una línea y no otra
ronda de leerse la documentación. Todo lo de este fichero sale de la documentación publicada
(https://api.freshservice.com/), y lo que es decisión nuestra lo dice.

**Cómo se llama.** `https://<dominio>/api/v2/<recurso>`, sólo por HTTPS —«Only SSL calls (HTTPS)
will be allowed»— y sólo contra un dominio de Freshservice: «Works only via Freshservice domains
and not via custom CNAMEs», que es un fallo difícil de adivinar si el CNAME de la casa resuelve y
contesta otra cosa.

**Cómo se autentica.** La clave de API como usuario y cualquier cosa como contraseña: «If you use
the API key, there is no need for a password. You can use any set of characters as a dummy
password». Aquí va una `X`, que es la que ellos escriben en sus ejemplos.

**Cómo contesta.** Un sobre con una clave: la lista bajo el nombre en plural (`departments`) y el
objeto suelto bajo el singular (`ticket`). Por eso se desenvuelve por nombre y no se coge «lo
primero que venga»: un cuerpo inesperado se nota, en vez de convertirse en una lista vacía.

**Cómo pagina.** `page` y `per_page` —cien como máximo—, y la cabecera `link` con `rel="next"`
mientras queden páginas: «If you have reached the last page of objects, then the link header will
not be set». Piden además no pasar de la página 500 («deep pagination»).

**Cómo va de tiempo.** Marcas en UTC con la forma `YYYY-MM-DDTHH:MM:SSZ`, y en las entradas se
admiten ocho formatos, asumiendo UTC cuando no se dice la zona. Aquí se escribe **siempre** la
forma completa: la más corta se admite y ahorra dos caracteres a costa de que la zona la ponga
otro por ti.

**Cómo limita.** Por minuto y por plan, y lo dice en cada respuesta (`X-RateLimit-Total`,
`X-RateLimit-Remaining`). Cuando se acaba: 429 y `Retry-After` **en segundos**. Eso no se
interpreta ni se adivina — se lee y se cuenta, que es la diferencia entre «vuelve en 43 segundos»
y «error».

**Cómo falla.** Códigos con significados distintos y, en el cuerpo, `description` y una lista
`errors` con `field`, `message` y `code`. Cada código va a una clave de idioma propia porque
detrás de cada uno hay una cosa distinta que arreglar, y llamarlos a todos «error» manda a la
persona a mirar el que no es.
"""

from __future__ import annotations

import logging

#: La versión que se llama. Existe una v1 y está documentada aparte; esto es v2 en todas partes.
API_VERSION = 'v2'

_log = logging.getLogger(__name__)

#: El único sufijo por el que responde. Un CNAME propio de la casa resuelve, contesta, y no es
#: esto: la documentación lo dice con todas las letras.
DOMAIN_SUFFIX = '.freshservice.com'

#: Cuántos por página. Cien es su máximo; pedir menos son más viajes para lo mismo.
PER_PAGE_MAX = 100

#: Hasta qué página piden que se pida. **Suyo, no nuestro**: «avoid making calls referencing page
#: numbers over 500 (deep pagination)». Con cien por página son cincuenta mil objetos.
DEEP_PAGE_LIMIT = 500

#: Lo que se espera de una red que va bien. Nuestro: sin esto, un cortafuegos que traga los
#: paquetes deja la petición —y la pantalla— colgada hasta que se aburra el navegador.
TIMEOUT = 20

#: La forma en que van y vienen las marcas de tiempo, en UTC. La misma que escribe este panel, lo
#: cual es una coincidencia cómoda y no una razón para mezclarlas: una columna «modificado» que
#: unas veces dice cuándo se tocó aquí y otras cuándo se tocó allí significa dos cosas.
TIMESTAMP_FMT = '%Y-%m-%dT%H:%M:%SZ'

#: Lo que cada respuesta dice de tu cupo. Se leen todas y se devuelven juntas: «te quedan 12 de
#: 200» es una frase que se puede enseñar, y `X-RateLimit-Remaining` no.
RATE_HEADERS = {'total': 'X-RateLimit-Total',
                'remaining': 'X-RateLimit-Remaining',
                'used': 'X-RateLimit-Used-CurrentRequest',
                'retry_after': 'Retry-After'}

#: Un código, una clave de idioma. Cada uno se arregla de una manera distinta: 401 es la clave,
#: 403 es lo que ESA clave puede hacer, 404 es el dominio o el recurso, 405 es un fallo de este
#: código, 429 es esperar y 500 es de ellos.
STATUS_KEYS = {
    400: 'fs_err_request',
    401: 'fs_err_auth',
    403: 'fs_err_forbidden',
    404: 'fs_err_domain',
    405: 'fs_err_method',
    429: 'fs_err_rate',
    500: 'fs_err_server',
}


class FreshserviceError(Exception):
    """Un fallo con nombre.

    *key* es la clave del catálogo de idiomas con la que se cuenta en pantalla, y es lo ÚNICO que
    dice qué ha pasado: aquí no se escribe ni una frase. Una escrita aquí sería una que no se
    puede traducir y que nadie va a encontrar cuando revise las traducciones — y la tentación es
    grande, porque en el momento de escribirla se sabe muy bien lo que se quiere decir.

    *detail* es lo que dijo **el otro extremo** —un código, el `description` de su cuerpo de
    error, el mensaje de una librería, el cuerpo del proxy que contestó en su lugar— y por eso no
    se traduce: no es de este panel, y traducir lo que dijo otro es cambiárselo.

    *retry_after* sólo llega con un 429, en segundos y tal cual ellos lo mandan.
    """

    def __init__(self, key: str, detail: str = '', retry_after: int = 0) -> None:
        super().__init__(detail or key)
        self.key = key
        self.detail = detail
        self.retry_after = int(retry_after or 0)


# ── El dominio ──────────────────────────────────────────────────────────────────────────

def host_of(domain: str) -> str:
    """El dominio tal cual se teclea, convertido en el que se puede llamar.

    `https://acme.freshservice.com/`, `acme.freshservice.com` y `acme` son la misma casa, y quien
    lo escribe no tiene por qué saber cuál de las tres quiere el programa. Sin esquema, porque
    sólo hay uno: sus llamadas son todas HTTPS.
    """
    d = str(domain or '').strip()
    for prefijo in ('https://', 'http://'):
        if d.lower().startswith(prefijo):
            d = d[len(prefijo):]
    d = d.strip('/').split('/')[0].strip().lower()
    if d and '.' not in d:
        d += DOMAIN_SUFFIX
    return d


def is_freshservice_host(host: str) -> bool:
    """Si eso es un dominio suyo. Un CNAME de la casa resuelve y contesta, y no es esto — la
    documentación dice que la API va sólo por dominios de Freshservice."""
    return str(host or '').lower().endswith(DOMAIN_SUFFIX)


def url(host: str, path: str) -> str:
    """`https://<host>/api/v2/<path>`. Sólo HTTPS: es lo único que admiten."""
    return f'https://{host}/api/{API_VERSION}/{str(path or "").lstrip("/")}'


# ── El tiempo ───────────────────────────────────────────────────────────────────────────

def parse_stamp(value: str):
    """Una marca suya, como fecha con zona. `None` si no lo es.

    Aquí y no en cada sitio que lea una: el día que una pantalla enseñe «modificado en el origen»
    hay una sola forma de leerlo, y no tres parsers con tres ideas de qué pasa sin la `Z`. Sin
    zona se asume UTC, que es lo que ellos dicen que hacen.
    """
    from datetime import datetime, timezone                          # noqa: PLC0415
    texto = str(value or '').strip()
    if not texto:
        return None
    for fmt in (TIMESTAMP_FMT, '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(texto, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:                                    # `±hh:mm` y demás variantes con desplazamiento
        return datetime.fromisoformat(texto.replace('Z', '+00:00'))
    except ValueError:
        return None


def stamp(when) -> str:
    """Una fecha, en la forma completa que ellos publican. Siempre la larga: la corta se admite y
    ahorra dos caracteres a costa de que la zona la ponga otro por ti."""
    from datetime import timezone                                    # noqa: PLC0415
    if when is None:
        return ''
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return when.strftime(TIMESTAMP_FMT)


# ── El cupo ─────────────────────────────────────────────────────────────────────────────

def rate(headers) -> dict:
    """Lo que la respuesta dice del cupo: `{total, remaining, used, retry_after}`.

    Números y no cadenas, y `0` cuando la cabecera no viene: quien lo enseñe no tiene por qué
    saber que `X-RateLimit-Remaining` a veces no está.
    """
    out = {}
    for nombre, cabecera in RATE_HEADERS.items():
        try:
            out[nombre] = int(str((headers or {}).get(cabecera) or '0').strip() or 0)
        except ValueError:
            out[nombre] = 0
    return out


def has_next(headers) -> bool:
    """Si queda otra página, según ellos: «if you have reached the last page of objects, then the
    link header will not be set»."""
    return 'rel="next"' in str((headers or {}).get('link') or '')


# ── Las llamadas ────────────────────────────────────────────────────────────────────────

def session(api_key: str):
    """Una sesión autenticada. La clave como usuario y una `X` de contraseña, que es lo que sus
    propios ejemplos escriben: «you can use any set of characters as a dummy password»."""
    import requests                                                  # noqa: PLC0415
    s = requests.Session()
    s.auth = (str(api_key or ''), 'X')
    s.headers.update({'Content-Type': 'application/json',
                      'Accept': 'application/json'})
    return s


def _detail(resp) -> str:
    """Lo que ellos cuentan de un error: `description`, y los `errors` con su campo y su mensaje.

    Se saca de su cuerpo y no del código, porque el código dice la clase de fallo y esto dice
    cuál — «Validation failed» y luego «name: has already been taken». Cortado, porque va a un
    aviso y no a un registro.
    """
    try:
        cuerpo = resp.json() or {}
    except Exception:                                                # pylint: disable=broad-except
        return (getattr(resp, 'text', '') or '')[:200]
    if not isinstance(cuerpo, dict):
        return str(cuerpo)[:200]
    trozos = [str(cuerpo.get('description') or '').strip()]
    for e in (cuerpo.get('errors') or []):
        if not isinstance(e, dict):
            continue
        campo = str(e.get('field') or '').strip()
        msg = str(e.get('message') or '').strip()
        trozos.append(f'{campo}: {msg}' if campo else msg)
    return ' — '.join(t for t in trozos if t)[:200]


def _raise(resp) -> None:
    """Convertir una respuesta que no es 200 en el fallo con nombre que le corresponde."""
    codigo = int(getattr(resp, 'status_code', 0) or 0)
    espera = rate(getattr(resp, 'headers', {})).get('retry_after', 0)
    raise FreshserviceError(STATUS_KEYS.get(codigo, 'fs_err_http'),
                            _detail(resp) or f'HTTP {codigo}', espera)


def get(sess, host: str, path: str, params=None):
    """Una llamada. Devuelve `(cuerpo, cabeceras)` y levanta el fallo con nombre si no fue bien.

    Todo lo que puede ir mal en una petición se traduce aquí, una vez: se acabó el cupo, no hay
    red, el certificado no vale, tardó demasiado, contestó un proxy con una página de acceso.
    """
    import requests                                                  # noqa: PLC0415
    try:
        r = sess.get(url(host, path), params=params or {}, timeout=TIMEOUT)
    except requests.exceptions.SSLError as exc:
        raise FreshserviceError('fs_err_tls', str(exc)[:200]) from exc
    except requests.exceptions.Timeout as exc:
        raise FreshserviceError('fs_err_timeout', str(exc)[:200]) from exc
    except Exception as exc:                                         # pylint: disable=broad-except
        raise FreshserviceError('fs_err_net', str(exc)[:200]) from exc
    if r.status_code != 200:
        _raise(r)
    try:
        cuerpo = r.json() or {}
    except Exception as exc:                                         # pylint: disable=broad-except
        # Un cuerpo que no es JSON casi siempre es el portal de acceso de un proxy o de un
        # cortafuegos contestando por el servidor. Dicho así, se va a mirar ahí.
        raise FreshserviceError('fs_err_body', (r.text or '')[:200]) from exc
    return cuerpo, r.headers


def unwrap(cuerpo, key: str):
    """Lo que hay dentro del sobre, por su nombre.

    Su convención: la lista bajo el plural (`departments`) y el objeto suelto bajo el singular
    (`ticket`). Por NOMBRE y no «lo primero que venga»: así, un cuerpo inesperado se nota en vez
    de convertirse en una lista vacía que parece una casa sin departamentos.
    """
    if not isinstance(cuerpo, dict) or key not in cuerpo:
        raise FreshserviceError('fs_err_body')
    return cuerpo[key]


def unwrap_soft(cuerpo, key: str):
    """Lo de dentro del sobre, o ``None`` si no está — sin levantar nada.

    Para las lecturas **que pueden no existir**: un módulo que este plan no tiene, un recurso que
    esta clave no alcanza, un campo que su documentación no publica. Ahí, «no está» es una
    respuesta legítima y tratarla como un fallo convertiría un extra en un motivo para no poder
    usar lo principal.

    Lo obligatorio sigue usando :func:`unwrap`, que sí protesta: la diferencia entre las dos es
    si lo que falta hace inútil la respuesta.
    """
    if not isinstance(cuerpo, dict):
        return None
    return cuerpo.get(key)


def name_of(fila) -> str:
    """Cómo se llama una cosa suya, sin dar por hecho el campo.

    Su documentación publica los verbos de varios recursos pero no siempre la lista de campos, y
    en sus objetos el nombre unas veces es `name`, otras `title` y otras `subject`. Se prueban en
    ese orden y se cae al identificador: enseñar «#42» es peor que enseñar «Correo caído», y
    mucho mejor que enseñar un hueco o reventar.
    """
    for campo in ('name', 'title', 'subject', 'label'):
        v = str((fila or {}).get(campo) or '').strip()
        if v:
            return v
    ident = str((fila or {}).get('id') or '').strip()
    return f'#{ident}' if ident else ''


def page_all(sess, host: str, path: str, key: str, params=None, per_page: int = PER_PAGE_MAX):
    """Todas las páginas de una colección, en una lista.

    Tres frenos, y hacen falta los tres: la cabecera `link` mientras quede algo —que es su forma
    de decirlo—, la página a medias por si un intermediario se comiera la cabecera, y el tope de
    página 500 que ellos mismos piden no pasar. Sin el tercero, un servidor que conteste siempre
    la misma página deja la petición dando vueltas para siempre.
    """
    fuera = Paged()
    for pagina in range(1, DEEP_PAGE_LIMIT + 1):
        consulta = dict(params or {}, page=pagina, per_page=min(int(per_page), PER_PAGE_MAX))
        cuerpo, cabeceras = get(sess, host, path, consulta)
        trozo = unwrap(cuerpo, key)
        if not isinstance(trozo, list):
            raise FreshserviceError('fs_err_body')
        fuera.extend(trozo)
        if not has_next(cabeceras) or len(trozo) < min(int(per_page), PER_PAGE_MAX):
            break
    else:
        # El tope, alcanzado con páginas todavía por delante. Callarlo era devolver una lista
        # CORTA como si fuera la entera — y quien la usa para decir «esto ya no está allí»
        # (los huérfanos) lo diría de todo lo que no llegó.
        fuera.truncated = True
        _log.warning('Freshservice %s: stopped at the %d-page limit with more pages left; '
                     'the list is incomplete', path, DEEP_PAGE_LIMIT)
    return fuera


class Paged(list):
    """Una lista que además dice si se cortó en el tope de páginas (`truncated`)."""
    truncated = False
