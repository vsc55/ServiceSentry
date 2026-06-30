# ServiceSentry Helm chart

Despliega ServiceSentry en Kubernetes con la topología por roles (web / worker /
events / syslog) sobre una BD compartida, el **plano de control distribuido**
(heartbeat + cola de comandos + poke HTTP) y **elección de líder** para alta
disponibilidad. Ver [docs/kubernetes.md](../../docs/kubernetes.md) y
[docs/architecture.md](../../docs/architecture.md) para el modelo completo.

## Requisitos

- Kubernetes ≥ 1.23, Helm 3.
- Una **base de datos** MySQL/PostgreSQL accesible (gestionada o propia). El chart
  **no** despliega la BD.
- La imagen `servicesentry` en un registry accesible por el cluster.

## Instalación

```bash
helm install ss ./helm/servicesentry \
  --namespace servicesentry --create-namespace \
  --set auth.password='cambia-esto' \
  --set database.host=mi-mysql --set database.password='db-pass' \
  --set control.token="$(openssl rand -hex 32)"
```

O con un fichero de valores:

```bash
helm install ss ./helm/servicesentry -n servicesentry --create-namespace -f mis-valores.yaml
```

## Valores clave

| Valor | Por defecto | Descripción |
|-------|-------------|-------------|
| `image.repository` / `image.tag` | `servicesentry` / `latest` | Imagen |
| `auth.username` / `auth.password` | `admin` / *(requerido)* | Credenciales del panel |
| `existingSecret` | `""` | Usa un Secret propio con las claves `SS_*` en vez de generarlo |
| `secretKey` | *(auto)* | Clave de cifrado **compartida** (`.flask_secret`, 64 hex). Auto-generada y estable entre upgrades si se deja vacía |
| `database.driver/host/port/name/user/password` | `mysql` … | BD compartida (externa) |
| `syslogDatabase.enabled` | `false` | BD dedicada para mensajes syslog |
| `control.enabled` / `control.token` / `control.port` | `true` / `""` / `8765` | Plano de control: con token se habilita el **poke** instantáneo |
| `web.replicas` | `1` | Réplicas del panel |
| `worker.replicas` | `1` | Monitor. **>1 = hot-standby** (failover por lease de líder) |
| `events.replicas` | `1` | Eventos. **>1 = hot-standby** |
| `syslog.enabled` / `syslog.replicas` | `true` / `1` | Receptor syslog. **>1 = active-active** (scale-out) |
| `syslog.ingress.type` | `LoadBalancer` | Service de ingreso UDP/TCP |
| `networkPolicy.enabled` | `false` | Restringe el puerto de control (`:8765`) a los pods `web` |
| `netRaw` | `true` | Concede `CAP_NET_RAW` (módulo ping) |

Lista completa en [`values.yaml`](values.yaml).

## Alta disponibilidad

- **worker / events**: pon `replicas: 2`. Un **lease de líder** en BD hace que solo
  una réplica trabaje; si cae, otra toma el relevo en ~30 s. La pestaña *Servicios*
  marca **Líder / En espera**.
- **syslog**: `replicas: N` reparte la ingesta entre réplicas (active-active).

## Notas

- **`secretKey` debe ser estable y la misma en todos los pods** — el chart la genera
  una vez (Secret con `helm.sh/resource-policy: keep`) y la monta como
  `/etc/ServiSesentry/.flask_secret`. Si la cambias, los secretos ya cifrados en la
  BD dejarán de poder descifrarse.
- **Sin `control.token`** el poke se desactiva (no se exponen los Services de control
  ni las probes `/control/health`); el control sigue por el reconcile periódico.
- El Service de ingreso de syslog usa puertos **mixtos UDP/TCP**: requiere un cluster
  que lo soporte; si no, divídelo en dos Services.

## Desinstalar

```bash
helm uninstall ss -n servicesentry
# El Secret de la clave de cifrado se conserva (resource-policy: keep); bórralo a mano
# si quieres una instalación totalmente limpia:
kubectl delete secret ss-servicesentry-secretkey -n servicesentry
```
