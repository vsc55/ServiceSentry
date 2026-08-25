# Marcas de fabricante

Un dispositivo dice quién lo fabricó, y el perfil que lo reconoce es lo único del producto que
sabe traducir `1.3.6.1.4.1.14988` a «MikroTik». Aquí están las marcas que ese perfil puede
nombrar: un fichero por fabricante, cuyo nombre declara el perfil en su bloque `brand`
(`"logo": "mikrotik"` → `mikrotik.svg`).

## De dónde salen

De [Simple Icons](https://github.com/simple-icons/simple-icons), **sin modificar**, bajo
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) — dedicación al dominio público.
Esa licencia cubre **el fichero SVG**, no la marca que dibuja: los nombres y los logotipos
siguen siendo de sus titulares y aquí se usan sólo para identificar el equipo que el panel está
midiendo, que es exactamente para lo que están.

Ninguno lleva relleno declarado, así que se dibujan en negro: bien sobre un panel claro e
invisibles sobre uno oscuro, donde se invierten (`.ss-brand`, en `web_admin.css`) — el negro se
vuelve blanco y la forma no se toca.

**El `viewBox` de cada fichero está recortado a la tinta que contiene**, y eso no es cosmética:
la marca se dibuja dándole una ALTURA y dejando que calcule sola su ancho, así que un letrero
sale ancho y una marca redonda sale redonda. El origen dibuja todo dentro de un lienzo de
24×24, y con ese lienzo un letrero como el de Synology salía a un tercio de la altura del texto
de al lado. Hay una guarda (`tests/meta/test_wa_infra_section.py`) que calcula la caja del
trazado y falla si la declarada es mayor.

## Añadir una

1. Deja el `.svg` aquí: monocromo, una silueta, **sin `fill`** y con el `viewBox` ajustado a
   la tinta (si viene de Simple Icons, en un lienzo de 24×24, recórtalo — si no, se dibujará
   pequeño). El nombre del fichero es un `slug`: minúsculas, dígitos, `-` y `_`, y nada más
   (el núcleo rechaza cualquier otra cosa antes de que llegue a una URL).
2. Decláralo donde corresponda, y hay **dos sitios** porque hay dos preguntas distintas.

   El perfil **es** de un fabricante —casa con su árbol de OIDs, así que un aparato que lo
   contesta lo hizo él— y lo dice al lado del `match`:

   ```json
   "brand": {"name": "MikroTik", "logo": "mikrotik", "color": "#293239"}
   ```

   O el perfil no habla por nadie en particular y **lee** quién lo hizo. `ucd_extend` lee DMI,
   que contesta «HP», «Dell Inc.» o «QEMU» — y quien lee DMI es justo lo que sabe qué contesta
   DMI, así que la tabla va en ese perfil:

   ```json
   "brands": [
       {"any": ["hp", "hewlett"], "name": "HP", "logo": "hp", "color": "#0096d6"}
   ]
   ```

   `any` son las cadenas que significan ese fabricante, buscadas **dentro** de lo que dijo el
   aparato y en minúsculas: una máquina dice «HP», la siguiente «Hewlett-Packard» y la tercera
   «HPE ProLiant», y son el mismo rack.

Un fabricante para el que no haya fichero **no es un error**: se dibuja su nombre sobre su
color. Y un perfil que declara `icon` (`bi-windows`) usa el juego de iconos que el panel ya
trae, sin fichero ninguno.
