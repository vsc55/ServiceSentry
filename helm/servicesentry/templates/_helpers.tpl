{{/* Expand the name of the chart. */}}
{{- define "servicesentry.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully qualified app name. */}}
{{- define "servicesentry.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Common labels. */}}
{{- define "servicesentry.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "servicesentry.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
{{- end -}}

{{/* Selector labels. */}}
{{- define "servicesentry.selectorLabels" -}}
app.kubernetes.io/name: {{ include "servicesentry.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Secret name (generated or external). */}}
{{- define "servicesentry.secretName" -}}
{{- if .Values.existingSecret -}}{{ .Values.existingSecret }}{{- else -}}{{ include "servicesentry.fullname" . }}-secret{{- end -}}
{{- end -}}

{{/* ServiceAccount name. */}}
{{- define "servicesentry.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "servicesentry.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* envFrom block shared by every role (ConfigMap + Secret). */}}
{{- define "servicesentry.envFrom" -}}
- configMapRef:
    name: {{ include "servicesentry.fullname" . }}-env
- secretRef:
    name: {{ include "servicesentry.secretName" . }}
{{- end -}}

{{/* Pod securityContext capabilities for raw ICMP (ping module). */}}
{{- define "servicesentry.netRaw" -}}
{{- if .Values.netRaw }}
securityContext:
  capabilities:
    add: ["NET_RAW"]
{{- end }}
{{- end -}}

{{/* Shared volumes: the encryption key (same on every pod) + a scratch var dir. */}}
{{- define "servicesentry.volumes" -}}
- name: flasksecret
  secret:
    secretName: {{ include "servicesentry.fullname" . }}-secretkey
    items:
      - { key: flask_secret, path: .flask_secret }
- name: vardata
  emptyDir: {}
{{- end -}}

{{- define "servicesentry.volumeMounts" -}}
- name: flasksecret
  mountPath: /etc/ServiSesentry/.flask_secret
  subPath: .flask_secret
  readOnly: true
- name: vardata
  mountPath: /var/lib/ServiSesentry
{{- end -}}

{{/* Control-listener container port + advertise env for a dedicated role.
     Usage: {{ include "servicesentry.controlEnv" (dict "ctx" $ "role" "worker") }} */}}
{{- define "servicesentry.controlEnv" -}}
{{- if .ctx.Values.control.enabled }}
- name: SS_CONTROL_ADVERTISE
  value: {{ printf "%s-%s" (include "servicesentry.fullname" .ctx) .role | quote }}
{{- end }}
{{- end -}}
