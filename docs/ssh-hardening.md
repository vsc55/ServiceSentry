# Endurecimiento del acceso SSH a hosts monitorizados

ServiceSentry se conecta por SSH (paramiko, sesión **no interactiva** vía
`exec_command`, sin PTY) a los servidores remotos para leer métricas y, de forma
opcional, remediar servicios. Esta guía explica cómo configurar cada host
remoto para que la cuenta usada por ServiceSentry **solo pueda ejecutar los
comandos estrictamente necesarios** y nada más.

La técnica central es la estándar de OpenSSH: **clave dedicada + comando forzado
(`command=`) en `authorized_keys` + un script envoltorio que valida cada comando
contra una allowlist**. El envoltorio listo para usar está en
[`ssentry-wrap`](ssentry-wrap).

---

## Comandos que ejecuta ServiceSentry (host Linux)

Cada módulo OS lanza un comando fijo y conocido. Todos son de **solo lectura**
salvo la remediación de servicios:

| Módulo | Comando remoto (Linux) | Privilegio | Allowlist limpia |
|--------|------------------------|-----------|:---:|
| filesystemusage | `df -P -k` | usuario | ✅ |
| process | `ps -A -o comm=` | usuario | ✅ |
| ram_swap | `cat /proc/meminfo` | usuario | ✅ |
| raid | `cat /proc/mdstat` | usuario | ✅ |
| temperature | `grep -H . /sys/class/thermal/thermal_zone*/{type,temp}` | usuario | ✅ |
| dns | `dig +short …` | usuario | ✅ |
| service_status (check) | `systemctl is-active <svc>` | usuario | ✅ |
| cpu | `cat /proc/stat` (×2, intervalo en Python) | usuario | ✅ |
| **service_status (remediación)** | `systemctl start\|stop\|restart <svc>` | **root** | ✅ (vía sudo) |

> Las métricas de solo lectura no requieren privilegios: con una cuenta normal
> basta. Solo la **remediación** (arrancar/parar/reiniciar servicios) necesita
> root, y se acota con una regla `sudoers` mínima. Si no usas remediación, la
> cuenta puede ser 100 % de solo lectura y **sin sudo**.

Todos los comandos son un **binario suelto** sin encadenamiento de shell. Los
módulos que necesitan varias lecturas (cpu muestrea `/proc/stat` dos veces;
ram_swap/temperature en macOS/FreeBSD) hacen cada lectura en una llamada
separada y combinan/esperan en Python, no con `sleep`/`;`/`|` remotos. Eso
permite una allowlist estricta de un comando por entrada.

---

## Paso 1 — Usuario dedicado, solo con clave

```bash
sudo useradd -m -s /bin/bash svcsentry
sudo -u svcsentry install -d -m 700 /home/svcsentry/.ssh
```

En el **gestor de credenciales** de ServiceSentry crea una credencial SSH para
este host usando **autenticación por clave** (no contraseña) y activa
`ssh_verify_host` en el perfil SSH del host para validar la host key del remoto
(evita ataques MITM).

## Paso 2 — Instalar el envoltorio

Copia [`ssentry-wrap`](ssentry-wrap) al host remoto:

```bash
sudo install -m 0755 -o root -g root ssentry-wrap /usr/local/bin/ssentry-wrap
```

Recorta los `case` del script para dejar solo los módulos que realmente usas:
cuantas menos entradas, menor superficie de ataque. Todo comando fuera de la
lista se rechaza y se registra en syslog (`logger -t ssentry-wrap`).

## Paso 3 — Comando forzado en `authorized_keys`

`/home/svcsentry/.ssh/authorized_keys`:

```
restrict,command="/usr/local/bin/ssentry-wrap" ssh-ed25519 AAAA…clave_publica… servicesentry
```

```bash
sudo chown -R svcsentry:svcsentry /home/svcsentry/.ssh
sudo chmod 600 /home/svcsentry/.ssh/authorized_keys
```

`restrict` (OpenSSH ≥ 7.2) implica `no-port-forwarding`, `no-agent-forwarding`,
`no-X11-forwarding`, `no-pty` y `no-user-rc`: desactiva túneles y shell
interactiva. Encaja perfecto porque ServiceSentry **no** solicita PTY ni
forwarding. El `command=` forzado ignora el comando que pide el cliente y
ejecuta siempre el envoltorio, que recibe la petición original en
`$SSH_ORIGINAL_COMMAND`.

## Paso 4 — `sudoers` (solo si usas remediación)

La cuenta normal no puede arrancar/parar servicios. Concede privilegio acotado y
sin contraseña **solo** a esos verbos:

`/etc/sudoers.d/svcsentry` (valida siempre con `visudo -cf`):

```
svcsentry ALL=(root) NOPASSWD: /bin/systemctl start *, /bin/systemctl stop *, /bin/systemctl restart *
```

Habilita en `ssentry-wrap` el bloque `sudo systemctl …` y configura el comando
de remediación de ServiceSentry con prefijo `sudo`. Si **no** usas remediación,
omite este paso entero y borra ese bloque del envoltorio.

> Endurecimiento adicional: en lugar de `start *`, enumera los servicios
> concretos (`/bin/systemctl restart nginx, /bin/systemctl restart postgresql`)
> para que ni siquiera sea posible tocar otros servicios.

## Paso 5 — Endurecer `sshd` y la red

- **Firewall**: permite el puerto SSH solo desde la IP de ServiceSentry, p. ej.
  `sudo ufw allow from <IP_servicesentry> to any port 22 proto tcp`.
- **`sshd_config`**: `PasswordAuthentication no` y, para acotar aún más esta
  cuenta:

  ```
  Match User svcsentry
      PermitTTY no
      X11Forwarding no
      AllowTcpForwarding no
      AllowAgentForwarding no
  ```

- Considera `fail2ban` y mantener `sshd` actualizado.

---

## Verificación

```bash
# Comando permitido → devuelve datos:
ssh -i clave_privada svcsentry@host 'df -P -k'

# Comando NO permitido → rechazado y registrado en syslog:
ssh -i clave_privada svcsentry@host 'rm -rf /'      # → "command not allowed", exit 1
sudo journalctl -t ssentry-wrap                      # auditoría de OK/DENIED
```

Desde la propia interfaz, el botón **Test connection** del host y de cada
comprobación debe seguir devolviendo OK con la cuenta restringida.

---

## Nota de diseño: comandos compatibles con allowlist

Para que la allowlist pueda ser estricta (un binario fijo por entrada, sin
`for`, `;`, `|` ni `$()`), los módulos OS evitan por completo los snippets de
shell. Cuando un módulo necesita varias lecturas, hace cada una en una llamada
SSH separada y combina o espera en Python, en lugar de encadenar comandos en el
host remoto:

- **temperature** lee las zonas térmicas con un único `grep -H .` sobre
  `/sys/class/thermal/thermal_zone*/{type,temp}` y correlaciona `type`↔`temp` en
  Python (antes: bucle `for … done`).
- **cpu** muestrea `/proc/stat` (o `kern.cp_time` en FreeBSD) en **dos llamadas**
  con la espera del intervalo en Python (antes: `cat … | grep …; sleep N; …`).
- **ram_swap** en macOS/FreeBSD ejecuta cada `sysctl`/`vm_stat`/`swapinfo` por
  separado y une las salidas con un marcador en Python (antes: `…; echo SEP; …`).

Cada módulo incluye un test `test_command(s)_are_allowlist_friendly` que fija
esta propiedad (sin `;`, `|`, `&&`, `$()`, `` ` ``, `for` ni `echo`).
