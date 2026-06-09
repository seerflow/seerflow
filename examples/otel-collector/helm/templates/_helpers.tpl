{{/*
Naming helpers for the seerflow-otel-gateway chart.
*/}}

{{- define "seerflow-otel-gateway.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "seerflow-otel-gateway.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "seerflow-otel-gateway.labels" -}}
app.kubernetes.io/name: {{ include "seerflow-otel-gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "seerflow-otel-gateway.selectorLabels" -}}
app.kubernetes.io/name: {{ include "seerflow-otel-gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
