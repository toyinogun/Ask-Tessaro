{{- define "baseline.labels" -}}
app.kubernetes.io/part-of: ask-tessaro
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Pod Security level each mode enforces, by tier (spec 0007 AC-4). */}}
{{- define "baseline.enforce" -}}
{{- if eq .tier "own" }}restricted{{ else }}baseline{{ end -}}
{{- end -}}
