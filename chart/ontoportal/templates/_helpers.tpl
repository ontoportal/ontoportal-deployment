{{- define "ontoportal.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ontoportal.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "ontoportal.namespace" -}}
{{- default .Release.Namespace .Values.global.namespace -}}
{{- end -}}

{{- define "ontoportal.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "ontoportal.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: ontoportal
ontoportal.org/profile: {{ .Values.profile.name | quote }}
ontoportal.org/distribution: {{ .Values.deploymentTarget.distribution | default .Values.profile.name | quote }}
ontoportal.org/runtime: {{ .Values.deploymentTarget.runtime | default "kubernetes" | quote }}
ontoportal.org/provider: {{ .Values.deploymentTarget.provider | default "generic" | quote }}
{{- with .Values.global.labels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "ontoportal.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ontoportal.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "ontoportal.secretName" -}}
{{- default (printf "%s-secrets" (include "ontoportal.fullname" .)) .Values.secrets.existingSecret -}}
{{- end -}}

{{- define "ontoportal.storageClass" -}}
{{- default .Values.global.storageClassName . -}}
{{- end -}}

{{- define "ontoportal.image" -}}
{{- if .digest -}}
{{- printf "%s@%s" .repository .digest -}}
{{- else -}}
{{- printf "%s:%s" .repository .tag -}}
{{- end -}}
{{- end -}}

{{- define "ontoportal.componentNodeSelector" -}}
{{- $component := index . 0 -}}
{{- $root := index . 1 -}}
{{- $nodeSelector := default $root.Values.global.nodeSelector $component.nodeSelector -}}
{{- with $nodeSelector }}
nodeSelector:
{{ toYaml . | indent 2 }}
{{- end -}}
{{- end -}}

{{- define "ontoportal.componentScheduling" -}}
{{- $component := index . 0 -}}
{{- $root := index . 1 -}}
{{- $nodeSelector := default $root.Values.global.nodeSelector $component.nodeSelector -}}
{{- with $nodeSelector }}
nodeSelector:
{{ toYaml . | nindent 8 }}
{{- end }}
{{- $tolerations := default $root.Values.global.tolerations $component.tolerations -}}
{{- with $tolerations }}
tolerations:
{{ toYaml . | nindent 8 }}
{{- end }}
{{- $affinity := default $root.Values.global.affinity $component.affinity -}}
{{- with $affinity }}
affinity:
{{ toYaml . | nindent 8 }}
{{- end }}
{{- end -}}

{{- define "ontoportal.redisHostPersistent" -}}
{{- if eq (.Values.redis.mode | default "shared") "split" -}}
{{ include "ontoportal.fullname" . }}-redis-persistent
{{- else -}}
{{ include "ontoportal.fullname" . }}-redis
{{- end -}}
{{- end -}}

{{- define "ontoportal.redisHostGoo" -}}
{{- if eq (.Values.redis.mode | default "shared") "split" -}}
{{ include "ontoportal.fullname" . }}-redis-goo-cache
{{- else -}}
{{ include "ontoportal.fullname" . }}-redis
{{- end -}}
{{- end -}}

{{- define "ontoportal.redisHostHttp" -}}
{{- if eq (.Values.redis.mode | default "shared") "split" -}}
{{ include "ontoportal.fullname" . }}-redis-http-cache
{{- else -}}
{{ include "ontoportal.fullname" . }}-redis
{{- end -}}
{{- end -}}

{{- define "ontoportal.solrTermBaseUrl" -}}
{{- if eq (.Values.solr.mode | default "single") "split" -}}
{{ printf "http://%s-solr-term:%v/solr" (include "ontoportal.fullname" .) .Values.solr.port }}
{{- else -}}
{{ printf "http://%s-solr:%v/solr" (include "ontoportal.fullname" .) .Values.solr.port }}
{{- end -}}
{{- end -}}

{{- define "ontoportal.solrPropBaseUrl" -}}
{{- if eq (.Values.solr.mode | default "single") "split" -}}
{{ printf "http://%s-solr-prop:%v/solr" (include "ontoportal.fullname" .) .Values.solr.port }}
{{- else -}}
{{ printf "http://%s-solr:%v/solr" (include "ontoportal.fullname" .) .Values.solr.port }}
{{- end -}}
{{- end -}}

{{- define "ontoportal.solrTermUrl" -}}
{{ printf "%s/%s" (include "ontoportal.solrTermBaseUrl" . | trim) .Values.solr.termCore }}
{{- end -}}

{{- define "ontoportal.solrPropUrl" -}}
{{ printf "%s/%s" (include "ontoportal.solrPropBaseUrl" . | trim) .Values.solr.propCore }}
{{- end -}}

{{- define "ontoportal.storeHost" -}}
{{- if .Values.store.host -}}
{{ .Values.store.host }}
{{- else -}}
{{ include "ontoportal.fullname" . }}-store
{{- end -}}
{{- end -}}

{{- define "ontoportal.storePort" -}}
{{- if .Values.store.port -}}{{ .Values.store.port }}{{- else -}}{{ .Values.store.service.port }}{{- end -}}
{{- end -}}
{{- define "ontoportal.podSecurityContext" -}}
{{- with .Values.global.podSecurityContext }}
securityContext:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{- define "ontoportal.containerSecurityContext" -}}
{{- with .Values.global.containerSecurityContext }}
securityContext:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{- define "ontoportal.volumeDataSource" -}}
{{- $root := index . 0 -}}
{{- $existingClaim := index . 1 -}}
{{- $defaultClaim := index . 2 -}}
{{- if $root.Values.persistence.enabled }}
persistentVolumeClaim:
  claimName: {{ $existingClaim | default $defaultClaim }}
{{- else }}
emptyDir: {}
{{- end }}
{{- end -}}
{{- define "ontoportal.annotations" -}}
{{- with .Values.global.annotations }}
annotations:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}
{{- define "ontoportal.storeBackendName" -}}
{{- $engine := .Values.store.engine | default "virtuoso" | lower -}}
{{- if eq $engine "external" -}}
{{ default "sparql" .Values.store.backendName }}
{{- else if eq $engine "virtuoso" -}}
{{ default "virtuoso" .Values.store.backendName }}
{{- else -}}
{{- fail "store.engine must be 'virtuoso' or 'external'" -}}
{{- end -}}
{{- end -}}
{{- define "ontoportal.runtimeConfigScript" -}}
mkdir -p config/environments
cat > "config/environments/${RACK_ENV:-production}.rb" <<RUBY
require "active_support/all"
require "active_support/isolated_execution_state"
require "sparql/client"

module SparqlClientUpdatePatch
  def update(query, **options)
    @op = :update

    if @cache.redis_cache
      q_opts = query.respond_to?(:options) ? (query.options || {}) : options
      bypass = q_opts[:bypass_cache]
      graph = q_opts[:graph] || q_opts[:graphs]
      if !bypass && graph
        @cache.invalidate(graph)
      end
    end

    @alt_endpoint = options[:endpoint]
    @logger.log(query, user: options[:user], cached: false) do
      case @url
      when RDF::Queryable
        require "sparql" unless defined?(::SPARQL::Grammar)
        SPARQL.execute(query, @url, update: true, optimize: true, **options)
      else
        response(query, **options)
      end
    end
    self
  end
end
SPARQL::Client.prepend(SparqlClientUpdatePatch) unless SPARQL::Client.ancestors.include?(SparqlClientUpdatePatch)

GOO_BACKEND_NAME = ENV.fetch("GOO_BACKEND_NAME", "virtuoso")
GOO_HOST = ENV.fetch("GOO_HOST", "localhost")
GOO_PATH_DATA = ENV.fetch("GOO_PATH_DATA", "/sparql/")
GOO_PATH_QUERY = ENV.fetch("GOO_PATH_QUERY", "/sparql/")
GOO_PATH_UPDATE = ENV.fetch("GOO_PATH_UPDATE", "/sparql/")
GOO_PORT = ENV.fetch("GOO_PORT", 8890)
MGREP_HOST = ENV.fetch("MGREP_HOST", "localhost")
MGREP_PORT = ENV.fetch("MGREP_PORT", 55556)
MGREP_DICT_PATH = ENV.fetch("MGREP_DICT_PATH", "/data/mgrep/dictionary.txt")
REDIS_GOO_CACHE_HOST = ENV.fetch("REDIS_GOO_CACHE_HOST", "localhost")
REDIS_HTTP_CACHE_HOST = ENV.fetch("REDIS_HTTP_CACHE_HOST", "localhost")
REDIS_PERSISTENT_HOST = ENV.fetch("REDIS_PERSISTENT_HOST", "localhost")
REDIS_PORT = ENV.fetch("REDIS_PORT", 6379)
REPORT_PATH = ENV.fetch("REPORT_PATH", "/data/reports/ontologies_report.json")
REPOSITORY_FOLDER = ENV.fetch("REPOSITORY_FOLDER", "/data/repository")
REST_URL_PREFIX = ENV.fetch("REST_URL_PREFIX", "http://localhost:9393")
SOLR_PROP_SEARCH_URL = ENV.fetch("SOLR_PROP_SEARCH_URL", "http://localhost:8983/solr/prop_search_core1")
SOLR_TERM_SEARCH_URL = ENV.fetch("SOLR_TERM_SEARCH_URL", "http://localhost:8983/solr/term_search_core1")

require "net/http"
require "json"
require "uri"

module SOLR
  module Administration
    def solr_alive?
      uri = URI("#{@solr_url}/admin/info/system?wt=json")
      res = Net::HTTP.get_response(uri)
      res.is_a?(Net::HTTPSuccess) && (JSON.parse(res.body).dig("responseHeader", "status") == 0 rescue false)
    rescue StandardError
      false
    end

    def fetch_all_collections
      uri = URI("#{@solr_url}/admin/cores?action=STATUS&wt=json")
      res = Net::HTTP.get_response(uri)
      data = (JSON.parse(res.body) rescue {}) if res.is_a?(Net::HTTPSuccess)
      if res.is_a?(Net::HTTPSuccess) && data.dig("responseHeader", "status") == 0
        (data["status"] || {}).keys
      else
        raise "Failed to fetch Solr collections: #{res&.code} #{res&.body}"
      end
    end

    def collection_exists?(collection_name = @collection_name)
      fetch_all_collections.include?(collection_name.to_s)
    end

    def create_collection(collection_name = @collection_name, _num_shards = 1, _replication_factor = 1)
      return if collection_exists?(collection_name)

      params = URI.encode_www_form(
        action: "CREATE",
        name: collection_name.to_s,
        instanceDir: collection_name.to_s,
        configSet: "_default",
        wt: "json"
      )
      uri = URI("#{@solr_url}/admin/cores?#{params}")
      req = Net::HTTP::Post.new(uri)
      res = Net::HTTP.start(uri.hostname, uri.port, use_ssl: uri.scheme == "https") { |http| http.request(req) }
      data = (JSON.parse(res.body) rescue {}) if res.is_a?(Net::HTTPSuccess)
      unless res.is_a?(Net::HTTPSuccess) && data.dig("responseHeader", "status") == 0
        raise "Failed to create Solr collection #{collection_name}: #{res&.code} #{res&.body}"
      end
    end

    def delete_collection(collection_name = @collection_name)
      return unless collection_exists?(collection_name)

      params = URI.encode_www_form(
        action: "UNLOAD",
        core: collection_name.to_s,
        deleteIndex: "true",
        deleteDataDir: "true",
        deleteInstanceDir: "true",
        wt: "json"
      )
      uri = URI("#{@solr_url}/admin/cores?#{params}")
      req = Net::HTTP::Post.new(uri)
      res = Net::HTTP.start(uri.hostname, uri.port, use_ssl: uri.scheme == "https") { |http| http.request(req) }
      data = (JSON.parse(res.body) rescue {}) if res.is_a?(Net::HTTPSuccess)
      unless res.is_a?(Net::HTTPSuccess) && data.dig("responseHeader", "status") == 0
        raise "Failed to delete Solr collection #{collection_name}: #{res&.code} #{res&.body}"
      end
    end
  end
end

if defined?(LinkedData)
  LinkedData.config do |config|
    config.goo_backend_name = GOO_BACKEND_NAME.to_s
    config.goo_host = GOO_HOST.to_s
    config.goo_port = GOO_PORT.to_i
    config.goo_path_query = GOO_PATH_QUERY.to_s
    config.goo_path_data = GOO_PATH_DATA.to_s
    config.goo_path_update = GOO_PATH_UPDATE.to_s
    config.goo_redis_host = REDIS_GOO_CACHE_HOST.to_s
    config.goo_redis_port = REDIS_PORT.to_i
    config.http_redis_host = REDIS_HTTP_CACHE_HOST.to_s
    config.http_redis_port = REDIS_PORT.to_i
    config.ontology_analytics_redis_host = REDIS_PERSISTENT_HOST.to_s
    config.ontology_analytics_redis_port = REDIS_PORT.to_i
    config.repository_folder = REPOSITORY_FOLDER.to_s
    config.search_server_url = SOLR_TERM_SEARCH_URL.to_s.sub(%r{/term_search_core1/?\z}, "")
    config.property_search_server_url = SOLR_PROP_SEARCH_URL.to_s.sub(%r{/prop_search_core1/?\z}, "")
    config.rest_url_prefix = REST_URL_PREFIX.to_s
    config.replace_url_prefix = true
    config.enable_notifications = false
  end
end

if defined?(Annotator)
  Annotator.config do |config|
    config.annotator_redis_host = REDIS_PERSISTENT_HOST.to_s
    config.annotator_redis_port = REDIS_PORT.to_i
    config.mgrep_host = MGREP_HOST.to_s
    config.mgrep_port = MGREP_PORT.to_i
    config.mgrep_dictionary_file = MGREP_DICT_PATH.to_s
  end
end

if defined?(NcboCron)
  NcboCron.config do |config|
    config.redis_host = REDIS_PERSISTENT_HOST.to_s
    config.redis_port = REDIS_PORT.to_i
    config.ontology_report_path = REPORT_PATH
    config.daemonize = false
    config.search_index_all_url = ENV.fetch("SEARCH_INDEX_ALL_URL", SOLR_TERM_SEARCH_URL)
    config.property_search_index_all_url = ENV.fetch("PROPERTY_SEARCH_INDEX_ALL_URL", SOLR_PROP_SEARCH_URL)
  end
end

if defined?(LinkedData::OntologiesAPI)
  LinkedData::OntologiesAPI.config do |config|
    config.http_redis_host = REDIS_HTTP_CACHE_HOST.to_s
    config.http_redis_port = REDIS_PORT.to_i
    config.ontology_report_path = REPORT_PATH
    config.enable_req_timeout = false
    config.enable_throttling = false
  end
end

Goo.use_cache = true if defined?(Goo)
RUBY
{{- end -}}
