{{/*
Expand the name of the chart.
*/}}
{{- define "topic-freshness-exporter.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}


{{/*
Create a fully qualified app name.
If fullnameOverride is set, use that.
Otherwise: <release-name>-<chart-name>
*/}}
{{- define "topic-freshness-exporter.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "topic-freshness-exporter.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}


{{/*
Common labels
*/}}
{{- define "topic-freshness-exporter.labels" -}}
app.kubernetes.io/name: {{ include "topic-freshness-exporter.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | default .Chart.Version }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}


{{/*
Selector labels
*/}}
{{- define "topic-freshness-exporter.selectorLabels" -}}
app.kubernetes.io/name: {{ include "topic-freshness-exporter.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
