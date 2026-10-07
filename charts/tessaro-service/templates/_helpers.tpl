{{/* The release name is the service name. */}}
{{- define "tessaro.name" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "tessaro.selectorLabels" -}}
app.kubernetes.io/name: {{ include "tessaro.name" . }}
{{- end -}}

{{- define "tessaro.labels" -}}
{{ include "tessaro.selectorLabels" . }}
app.kubernetes.io/part-of: ask-tessaro
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* One NetworkPolicy peer: a namespace, optionally narrowed to pods by label. */}}
{{- define "tessaro.peer" -}}
- namespaceSelector:
    matchLabels:
      kubernetes.io/metadata.name: {{ .namespace }}
  {{- with .podLabels }}
  podSelector:
    matchLabels:
      {{- toYaml . | nindent 6 }}
  {{- end }}
{{- end -}}

{{- define "tessaro.ports" -}}
{{- with .ports -}}
ports:
  {{- range . }}
  - protocol: TCP
    port: {{ . }}
  {{- end }}
{{- end }}
{{- end -}}
