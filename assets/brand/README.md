# Marca

Aquí viven los **originales** de los que salen los ficheros que sirve el panel. Viven aquí y no
en `src/`: pesan megas y son material de origen, así que no tienen por qué viajar en el paquete
que se instala en el servidor — pero sí en el repositorio, porque un binario servido sin fuente
es un callejón sin salida: nadie puede rehacerlo a otro tamaño ni retocarlo sin volver a
empezar. Es la misma razón por la que el favicon tiene `src/tools/make_favicon.py`.

Son dos, y no son el mismo dibujo:

- `logo.png` — el **lockup** completo (arte + nombre), sobre su placa.
- `logo-badge.png` — el **emblema recortado**, sin placa ni fondo: sólo la insignia sobre
  transparencia. Es lo que hace falta cuando el logo tiene que posarse sobre un fondo que no
  controlamos — la tarjeta blanca de un cliente de correo, por ejemplo.

## Qué se sirve, y de dónde sale

| Fichero | Dónde se usa | Cómo se genera |
|---|---|---|
| `src/lib/web_admin/static/img/logo.png` | La tarjeta de login, la cabecera de Diagnóstico y el pie de la barra lateral | el original a 640 px de ancho |
| `src/lib/web_admin/static/img/logo-mark.png` | El anillo de carga del panel | el emblema recortado a 256×256 |
| `src/lib/web_admin/static/img/logo-email.png` | La cabecera de los correos de notificación | el emblema recortado a 128×128 |

```bash
# La insignia del correo. Del emblema RECORTADO y no del crop del lockup: en un correo el
# fondo es la tarjeta blanca del cliente, y el crop lleva placa — sería un rectángulo oscuro
# alrededor del emblema. 160 px para un `<img>` de 68: algo más del doble de densidad, que
# es lo que quiere una pantalla HiDPI, y ~10 KB. Pequeño a propósito, porque viaja adjunto
# en CADA notificación.
magick assets/brand/logo-badge.png \
    -resize 160x160 -strip -colors 256 -define png:compression-level=9 \
    src/lib/web_admin/static/img/logo-email.png

# El lockup completo, para el login.
magick assets/brand/logo.png \
    -resize 640x -strip -colors 256 -define png:compression-level=9 \
    src/lib/web_admin/static/img/logo.png

# La insignia del anillo de carga: el lockup es apaisado y dentro de un anillo de 96 px
# sería un nombre que no se lee. Del emblema recortado, y no de un crop del lockup: el
# crop metía una placa cuadrada dentro de un círculo, así que el anillo enmarcaba una
# esquina en vez de la insignia.
magick assets/brand/logo-badge.png \
    -resize 256x256 -strip -colors 256 -define png:compression-level=9 \
    src/lib/web_admin/static/img/logo-mark.png
```

Dos decisiones que no se ven en los comandos:

- **256 colores.** El original son 2 MB y se sirve en cada login: a 640 px de ancho son 305 KB
  en color completo y **76 KB** cuantizado, sin diferencia apreciable en un arte de neón sobre
  transparente. Una página de acceso que tarda en pintar la marca es la primera impresión del
  panel.
- **La transparencia se conserva** (`-strip` quita metadatos, no el canal alfa). Es lo que
  permite que el mismo fichero funcione sobre la tarjeta clara y sobre la oscura sin una placa
  negra detrás — y `tests/unit/test_wa_brand_logo.py` lo comprueba, porque aplanarlo contra
  negro es exactamente lo que hace una herramienta de optimización si nadie mira.
