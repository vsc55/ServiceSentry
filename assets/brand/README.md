# Marca

`logo.png` es el **original** del que salen los dos ficheros que sirve el panel. Vive aquí y no
en `src/`: pesa 2 MB y es material de origen, así que no tiene por qué viajar en el paquete que
se instala en el servidor — pero sí en el repositorio, porque un binario servido sin fuente es
un callejón sin salida: nadie puede rehacerlo a otro tamaño ni retocarlo sin volver a empezar.
Es la misma razón por la que el favicon tiene `src/tools/make_favicon.py`.

## Qué se sirve, y de dónde sale

| Fichero | Dónde se usa | Cómo se genera |
|---|---|---|
| `src/lib/web_admin/static/img/logo.png` | La tarjeta de login, la cabecera de Diagnóstico y el pie de la barra lateral | el original a 640 px de ancho |
| `src/lib/web_admin/static/img/logo-mark.png` | El anillo de carga del panel | solo el emblema, 256×256 |

```bash
# El lockup completo, para el login.
magick assets/brand/logo.png \
    -resize 640x -strip -colors 256 -define png:compression-level=9 \
    src/lib/web_admin/static/img/logo.png

# Solo la insignia: el lockup es apaisado y dentro de un anillo de 96 px sería un
# nombre que no se lee. El recorte está centrado en el círculo del original.
magick assets/brand/logo.png -crop 680x680+410+0 +repage \
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
