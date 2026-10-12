# Despliegue en Kubernetes

> **Atajo**: hay un **Helm chart** en [`helm/servicesentry/`](../helm/servicesentry)
> que genera todo lo de esta página (Deployments por rol, Services, Secret/ConfigMap,
> clave de cifrado compartida, plano de control y probes). Esta página explica los
> manifiestos por debajo; para desplegar rápido usa el chart
> (`helm install ss ./helm/servicesentry …`, ver su [README](../helm/servicesentry/README.md)).

ServiceSentry corre igual en Kubernetes que en la topología de microservicios de
Docker (ver [caso-docker.md](caso-docker.md)): **un Deployment por rol** que comparten una
**base de datos** y se coordinan por el **plano de control distribuido** (ver
[explica-servicios.md → Plano de control distribuido](explica-servicios.md#modo-microservicios-plano-de-control-distribuido)).

- **web** — panel de administración (`SS_*_EMBEDDED=0`: no programa checks, no liga
  syslog, no evalúa reglas; solo checks on-demand y la UI).
- **worker** — el scheduler de monitorización (`SS_SERVICE_ROLE=worker`).
- **syslog** — el receptor syslog (liga UDP/TCP/TLS; necesita un Service de ingress).
- **events** — el procesador de eventos por cursor.

El `web` **declara** el desired-state (config en BD) y encola comandos; cada
servicio **reconcilia** y publica su latido (`service_instances`). Para control
**instantáneo**, define `SS_CONTROL_TOKEN` (un Secret) y un **Service por rol** para
que el `web` pueda hacer el *poke* `POST /control/reconcile` por DNS de cluster. Sin
token, el control sigue funcionando por el reconcile periódico.

```mermaid
flowchart TB
    subgraph cluster["Cluster"]
        web["Deployment web<br/>SS_*_EMBEDDED=0"]
        worker["Deployment worker"]
        syslog["Deployment syslog"]
        events["Deployment events"]
        db[("BD (StatefulSet/externa)")]
        sec[["Secret: SS_CONTROL_TOKEN + DB creds"]]
        web -- desired-state / comandos --> db
        worker -- reconcile + heartbeat --> db
        syslog -- reconcile + heartbeat --> db
        events -- reconcile + heartbeat --> db
        web -. "poke /control/reconcile (Svc DNS)" .-> worker
        web -. poke .-> syslog
        web -. poke .-> events
    end
    ext(["syslog entrante UDP/TCP"]) --> syslog
```

> **Probes**: usa `GET /control/health` (sin auth) como `readinessProbe`/
> `livenessProbe` de worker/syslog/events; el `web` usa `GET /`.

---

## Secret y configuración común

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: servicesentry
type: Opaque
stringData:
  SS_USERNAME: admin
  SS_PASSWORD: change-me
  SS_DB_PASSWORD: db-password
  # Token compartido del poke de control (mismo valor en todos los pods).
  # Genéralo con:  openssl rand -hex 32
  SS_CONTROL_TOKEN: replace-with-a-long-random-token
  # OBLIGATORIO si despliegas con ESTOS manifiestos a mano. Firma las sesiones y **deriva la
  # clave Fernet con la que se cifra cada secreto guardado** (credenciales SSH, tokens…).
  # Estos Deployments solo usan `envFrom` y no montan nada, así que sin esta variable cada
  # pod se genera la suya: lo que cifra `web` no lo descifra `worker`, y al reiniciar un pod
  # lo cifrado antes queda irrecuperable. Mismo valor en TODOS los pods.
  #   Genérala con:  python -c "import secrets; print(secrets.token_hex(32))"
  #   (64 caracteres hex; un valor mal formado detiene el arranque a propósito)
  # Guárdala fuera del clúster: perderla es perder todos los secretos almacenados.
  # (Con el Helm chart se fija en `secretKey`: monta la clave compartida como fichero y la
  #  conserva entre upgrades — ver «Clave de cifrado y token de control (Helm)».)
  SS_SECRET_KEY: replace-with-64-hex-characters
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: servicesentry-env
data:
  SS_DB_DRIVER: mysql
  SS_DB_HOST: servicesentry-db
  SS_DB_PORT: "3306"
  SS_DB_NAME: servicesentry
  SS_DB_USER: servicesentry
  SS_LANG: es_ES
  SS_CHECK_INTERVAL: "300"
```

Cada Deployment monta ambos con `envFrom` (`configMapRef` + `secretRef`).

## Deployment: web

El panel **no** hospeda los servicios (`SS_*_EMBEDDED=0`): los poseen los pods
dedicados.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: servicesentry-web
spec:
  replicas: 1
  selector: { matchLabels: { app: servicesentry, role: web } }
  template:
    metadata: { labels: { app: servicesentry, role: web } }
    spec:
      containers:
        - name: web
          image: servicesentry:latest
          envFrom:
            - configMapRef: { name: servicesentry-env }
            - secretRef:    { name: servicesentry }
          env:
            - { name: SS_SERVICE_ROLE,        value: web }
            - { name: SS_MONITORING_EMBEDDED, value: "0" }
            - { name: SS_SYSLOG_EMBEDDED,     value: "0" }
            - { name: SS_EVENTS_EMBEDDED,     value: "0" }
          ports: [{ containerPort: 8080 }]
          readinessProbe:
            httpGet: { path: /api/v1/health, port: 8080 }
            initialDelaySeconds: 15
---
apiVersion: v1
kind: Service
metadata: { name: servicesentry-web }
spec:
  selector: { app: servicesentry, role: web }
  ports: [{ port: 80, targetPort: 8080 }]
```

## Deployment + Service: worker / events

`SS_CONTROL_ADVERTISE` debe ser el **nombre del Service** del rol, para que el
`control_url` que el pod publica resuelva por DNS desde el `web`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: servicesentry-worker }
spec:
  replicas: 1
  selector: { matchLabels: { app: servicesentry, role: worker } }
  template:
    metadata: { labels: { app: servicesentry, role: worker } }
    spec:
      containers:
        - name: worker
          image: servicesentry:latest
          envFrom:
            - configMapRef: { name: servicesentry-env }
            - secretRef:    { name: servicesentry }
          env:
            - { name: SS_SERVICE_ROLE,      value: worker }
            - { name: SS_CONTROL_ADVERTISE, value: servicesentry-worker }
            - { name: SS_CONTROL_PORT,      value: "8765" }
          ports: [{ containerPort: 8765, name: control }]
          readinessProbe:
            httpGet: { path: /control/health, port: 8765 }
          livenessProbe:
            httpGet: { path: /control/health, port: 8765 }
            initialDelaySeconds: 20
---
apiVersion: v1
kind: Service
metadata: { name: servicesentry-worker }   # = SS_CONTROL_ADVERTISE
spec:
  selector: { app: servicesentry, role: worker }
  ports: [{ port: 8765, targetPort: 8765 }]
```

El Deployment **events** es idéntico cambiando `role`/`SS_SERVICE_ROLE`/nombres a
`events` (su Service también escucha en 8765; no necesita ingress externo).

## Deployment + Services: syslog

Igual que worker/events para el control, **más** un Service de ingress para los
puertos syslog (UDP/TCP). Como un Service no mezcla UDP y TCP, usa dos (o un
`LoadBalancer` con `appProtocol`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: servicesentry-syslog }
spec:
  replicas: 1
  selector: { matchLabels: { app: servicesentry, role: syslog } }
  template:
    metadata: { labels: { app: servicesentry, role: syslog } }
    spec:
      containers:
        - name: syslog
          image: servicesentry:latest
          envFrom:
            - configMapRef: { name: servicesentry-env }
            - secretRef:    { name: servicesentry }
          env:
            - { name: SS_SERVICE_ROLE,      value: syslog }
            - { name: SS_CONTROL_ADVERTISE, value: servicesentry-syslog }
          ports:
            - { containerPort: 8765, name: control }
            - { containerPort: 514,  name: syslog-udp, protocol: UDP }
            - { containerPort: 514,  name: syslog-tcp, protocol: TCP }
          readinessProbe:
            httpGet: { path: /control/health, port: 8765 }
---
apiVersion: v1
kind: Service
metadata: { name: servicesentry-syslog }   # = SS_CONTROL_ADVERTISE (control poke)
spec:
  selector: { app: servicesentry, role: syslog }
  ports: [{ port: 8765, targetPort: 8765 }]
---
apiVersion: v1
kind: Service
metadata: { name: servicesentry-syslog-ingress }
spec:
  type: LoadBalancer
  selector: { app: servicesentry, role: syslog }
  ports:
    - { name: udp, port: 514, targetPort: 514, protocol: UDP }
    - { name: tcp, port: 514, targetPort: 514, protocol: TCP }
```

## NetworkPolicy (opcional, recomendado)

Restringe el listener de control para que **solo el `web`** lo alcance:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: servicesentry-control }
spec:
  podSelector: { matchLabels: { app: servicesentry } }
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector: { matchLabels: { app: servicesentry, role: web } }
      ports:
        - { port: 8765, protocol: TCP }
```

## Alta disponibilidad (réplicas > 1)

`worker` y `events` admiten **varias réplicas con failover**: un **lease de líder**
en BD hace que solo una haga el trabajo y las demás queden en **hot-standby**; si la
activa cae, otra toma el relevo en ~30 s (ver
[explica-servicios.md → Alta disponibilidad](explica-servicios.md#alta-disponibilidad-lease-de-líder--hot-standby)).
Así que puedes poner `replicas: 2` en esos Deployments para tolerar la caída de un
pod sin duplicar checks ni alertas. La pestaña **Servicios** marca cuál es **Líder**
y cuáles **En espera**.

`syslog` es **active-active**: detrás de su Service, el balanceo reparte los mensajes
entre réplicas (cada paquete va a una sola), así que escala horizontalmente para
ingesta — sube `replicas` sin más.

## Clave de cifrado y token de control (Helm)

`secretKey` (la clave de la que se deriva el cifrado de todo secreto guardado) y
`control.token` (el del poke de control) se **fijan en los valores**:

```bash
helm upgrade --install ss ./helm/servicesentry \
  --set secretKey="$(openssl rand -hex 32)" \
  --set control.token="$(openssl rand -hex 32)" …
```

Si se dejan vacíos, el chart reutiliza los que ya estén desplegados (`lookup` sobre el
Secret del release). Si no hay ninguno, **falla al renderizar** con un mensaje que dice qué
poner — salvo con `generateSecrets: true`.

La razón es `helm template`. `lookup` no ve el clúster ni con `helm template` ni con
`--dry-run`, ni con las herramientas GitOps que renderizan así (Argo CD, Flux): antes el
chart generaba entonces una clave **nueva en cada render**, y una clave nueva deja
**indescifrables** todas las credenciales y tokens ya guardados en la BD (y un token nuevo
reinicia todos los pods en cada sincronización).

| Valor | Por defecto | Qué hace |
| ----- | ----------- | -------- |
| `secretKey` | `""` | Clave compartida (64 hex). Vacía: la desplegada; sin ninguna, falla |
| `control.token` | `""` | Token del poke. Vacío: el desplegado; sin ninguno, falla (o `control.enabled: false`) |
| `generateSecrets` | `false` | Permite generar los dos cuando faltan. **Solo** con `helm install`/`helm upgrade` |

Con `generateSecrets: true`, las notas del release lo recuerdan y dan el comando para sacar
la clave generada (`kubectl get secret <release>-servicesentry-secretkey …`): guárdala y
pásala como `secretKey` antes de mover el release a GitOps.

## Persistencia del directorio var (Helm)

El directorio var (`/var/lib/ServiSesentry`) guarda las **copias de seguridad**, las
imágenes subidas, las MIB y los perfiles SNMP. Por defecto el chart lo deja en un
`emptyDir`, como las versiones anteriores: se **pierde** cada vez que se sustituye un pod y
no se comparte entre pods (una copia hecha por una réplica de `web` no la ve otra). Las
notas de `helm install` lo avisan. Para cualquier cosa que no sea una prueba, actívalo:

| Valor | Por defecto | Qué hace |
| ----- | ----------- | -------- |
| `persistence.enabled` | `false` | Monta **un mismo** PVC en `/var/lib/ServiSesentry` de todos los roles |
| `persistence.existingClaim` | `""` | Usa ese PVC en vez de crear uno |
| `persistence.storageClass` | `""` | `""` = la clase por defecto del cluster; `"-"` = sin clase (enlace estático) |
| `persistence.accessModes` | `["ReadWriteMany"]` | Con más de un pod, o pods en nodos distintos, hace falta RWX (NFS, CephFS, EFS, Azure Files…) |
| `persistence.size` | `5Gi` | Tamaño pedido |
| `persistence.annotations` | `{}` | Anotaciones del PVC creado |
| `persistence.fixOwnership` | `true` | Ver *Permisos* más abajo |

```bash
helm upgrade --install ss ./helm/servicesentry \
  --set persistence.enabled=true --set persistence.storageClass=nfs-client
```

**Se conserva al desinstalar.** El PVC que crea el chart lleva
`helm.sh/resource-policy: keep`: `helm uninstall` no lo borra, porque contiene las copias de
seguridad. Si de verdad sobra, bórralo a mano
(`kubectl delete pvc <release>-servicesentry-var`). Un `existingClaim` nunca lo toca el chart.

### Permisos con varios pods (y NFS)

Los roles no corren con el mismo usuario: `web` y `events` como el UID 1000
(`podSecurityContext`), y `worker` y `syslog` como **root**, porque necesitan `CAP_NET_RAW`
(ping) y `CAP_NET_BIND_SERVICE` (`:514`) y Kubernetes no se las da a un proceso no-root. Con
un volumen compartido esa mezcla dejaba ficheros de root (`root:root`, `0755`: las MIB
compiladas, el estado del monitor) en los que `web` no podía escribir. `fsGroup` no lo
arregla en NFS ni en la mayoría de los drivers RWX, que lo ignoran.

Con `persistence.enabled` y `persistence.fixOwnership: true` (el valor por defecto), el chart
hace coherente el volumen sin quitar a `worker`/`syslog` sus capacidades:

- `worker` y `syslog` corren con el **mismo grupo** que los demás (`runAsGroup: 1000`,
  `fsGroup: 1000`) y `umask 0002`, así que lo que crean es escribible por el grupo;
- un *init container* `var-owner` (root) hace `chown -R 1000:1000` y `chmod -R ug+rwX` del
  volumen en cada arranque, lo que repara lo que dejaron versiones anteriores.

**En NFS**, el servidor decide: con `root_squash` (el valor por defecto de casi todos los
servidores) root **no puede escribir** en el recurso ni hacer `chown`; el *init container*
avisa y deja arrancar el pod, pero `worker`/`syslog` fallarán al escribir. Exporta el
recurso con una de estas dos opciones:

```text
/srv/servicesentry  10.0.0.0/8(rw,sync,all_squash,anonuid=1000,anongid=1000)   # todo es 1000 (recomendado)
/srv/servicesentry  10.0.0.0/8(rw,sync,no_root_squash)                          # root sigue siendo root
```

Con `all_squash,anonuid=1000,anongid=1000` todo lo que escribe cualquier pod queda como
1000:1000 en el servidor, que es justo lo que se busca. `persistence.fixOwnership: false`
deja el comportamiento anterior (por ejemplo, si el almacenamiento ya da la propiedad
correcta por su cuenta).

## Notas

- **Sin token**: si omites `SS_CONTROL_TOKEN`, no levantes los Services de control
  ni las probes a `/control/health`; el control se propaga por el reconcile
  periódico (≤15 s) igualmente.
- **Base de datos**: usa un MySQL/PostgreSQL gestionado o un StatefulSet; apunta
  `SS_DB_*` ahí. Para syslog de alto volumen, una segunda BD con `SS_SYSLOG_DB_*`
  (ver [caso-docker.md](caso-docker.md)).
