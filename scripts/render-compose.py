#!/usr/bin/env python3
"""Render a Docker Compose deployment from the same Helm values profiles.

This is intentionally small and dependency-light: it deep-merges values YAML files in
left-to-right order, then emits compose/generated/docker-compose.<profile>.yml and
compose/generated/.env.<profile>.sample. Kubernetes remains the source of truth, but
Compose stays maintainable because it reads the same profiles.
"""
from __future__ import annotations

import argparse
import copy
import shlex
from pathlib import Path
from typing import Any, Dict, Mapping

import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys."""


def construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False) -> Dict[Any, Any]:
    mapping: Dict[Any, Any] = {}
    seen: set[Any] = set()
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        seen.add(key)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping)

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_VALUES = REPO_ROOT / "chart" / "ontoportal" / "values.yaml"



def display_path(path: Path) -> str:
    """Return a readable output path for repo-relative or absolute targets."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def bash_command(steps: list[str]) -> list[str]:
    return ["bash", "-lc", "\n".join(steps)]


def bundle_command(command: str) -> str:
    return command.replace("bundle exec ", "bundle _2.3.27_ exec ", 1)


def virtuoso_patch_command() -> str:
    return r'''bundle _2.3.27_ exec ruby <<'RUBY' || echo "WARN: could not patch Virtuoso Goo handling" >&2
def patch_gem(gem_name, relative_path, replacements)
  path = File.join(Gem::Specification.find_by_name(gem_name).full_gem_path, relative_path)
  source = File.read(path)
  patched = replacements.reduce(source) { |text, (old, new_text)| text.gsub(old, new_text) }
  File.write(path, patched) if patched != source
end
def append_gem_patch(gem_name, relative_path, marker, patch)
  path = File.join(Gem::Specification.find_by_name(gem_name).full_gem_path, relative_path)
  source = File.read(path)
  File.write(path, source + "\n" + patch) unless source.include?(marker)
end
patch_gem("ontologies_linked_data", "lib/ontologies_linked_data/services/submission_process/operations/submission_rdf_generator.rb", {
  " if e.response&.body" => " if e.respond_to?(:response) && e.response&.body"
})
patch_gem("ncbo_cron", "bin/ncbo_cron", {
  "require 'sys/proctable'" => "begin; require 'sys/proctable'; rescue LoadError; end"
})
patch_gem("goo", "lib/goo/sparql/client.rb", {
  "DROP GRAPH <" => "DROP SILENT GRAPH <",
  "chunk_lines = 500_000 # number of line" => "chunk_lines = Integer(ENV.fetch(\"GOO_APPEND_CHUNK_LINES\", \"2000\")) # patched for Virtuoso update payload size"
})
append_gem_patch("goo", "lib/goo/sparql/client.rb", "GooVirtuosoAppendPatch", <<'RUBY_PATCH')
# ontoportal-deployment: Virtuoso does not accept Goo's Graph Store append POST on /sparql/.
module GooVirtuosoAppendPatch
  private

  def execute_append_request(graph, data_file, mime_type_in)
    return super unless Goo.sparql_backend_name.to_s == "virtuoso"

    graph_iri = graph.is_a?(Array) ? graph.first.to_s : graph.to_s
    Goo.sparql_update_client.update("INSERT DATA { GRAPH <#{graph_iri}> {\n#{data_file}\n} }", graph: graph)
  end
end
Goo::SPARQL::Client.prepend(GooVirtuosoAppendPatch) unless Goo::SPARQL::Client.ancestors.include?(GooVirtuosoAppendPatch)
RUBY_PATCH
RUBY'''


def runtime_config_command() -> str:
    return r'''mkdir -p config/environments
cat > config/environments/compose.rb <<RUBY
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
      req = Net::HTTP::Get.new(uri)
      res = Net::HTTP.start(uri.hostname, uri.port, open_timeout: 5, read_timeout: 10, use_ssl: uri.scheme == "https") { |http| http.request(req) }
      res.is_a?(Net::HTTPSuccess) && (JSON.parse(res.body).dig("responseHeader", "status") == 0 rescue false)
    rescue StandardError
      false
    end

    def fetch_all_collections
      uri = URI("#{@solr_url}/admin/cores?action=STATUS&wt=json")
      req = Net::HTTP::Get.new(uri)
      res = Net::HTTP.start(uri.hostname, uri.port, open_timeout: 5, read_timeout: 10, use_ssl: uri.scheme == "https") { |http| http.request(req) }
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
      res = Net::HTTP.start(uri.hostname, uri.port, open_timeout: 5, read_timeout: 10, use_ssl: uri.scheme == "https") { |http| http.request(req) }
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
      res = Net::HTTP.start(uri.hostname, uri.port, open_timeout: 5, read_timeout: 10, use_ssl: uri.scheme == "https") { |http| http.request(req) }
      data = (JSON.parse(res.body) rescue {}) if res.is_a?(Net::HTTPSuccess)
      unless res.is_a?(Net::HTTPSuccess) && data.dig("responseHeader", "status") == 0
        raise "Failed to delete Solr collection #{collection_name}: #{res&.code} #{res&.body}"
      end
    end
  end

  class SolrConnector
    alias_method :orig_initialize, :initialize rescue nil
    def initialize(solr_url, collection_name, *args, **kwargs)
      @solr_url = solr_url
      @collection_name = collection_name
      @solr = RSolr.connect(url: collection_url)

      wait_time = 0
      max_wait_time = Integer(ENV.fetch("SOLR_WAIT_TIMEOUT", "120"))
      until solr_alive? || wait_time >= max_wait_time
        sleep 1
        wait_time += 1
      end
      raise "Solr instance not reachable within #{max_wait_time} seconds" unless solr_alive?

      @custom_schema = false
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
    config.replace_url_prefix = true
    config.rest_url_prefix = REST_URL_PREFIX.to_s
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
RUBY'''


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.load(fh, Loader=UniqueKeyLoader) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{path} must contain a YAML mapping at the document root")
    return data


def deep_merge(base: Dict[str, Any], overlay: Mapping[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(dict(result[key]), value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def image(values: Mapping[str, Any], name: str) -> str:
    cfg = values["images"][name]
    if cfg.get("digest"):
        return f"{cfg['repository']}@{cfg['digest']}"
    return f"{cfg['repository']}:{cfg['tag']}"


def env_map(values: Mapping[str, Any], component: str) -> Dict[str, str]:
    return {str(k): str(v) for k, v in (values.get(component, {}).get("extraEnv") or {}).items()}


def service_enabled(values: Mapping[str, Any], component: str) -> bool:
    return bool(values.get(component, {}).get("enabled", False))


def redis_hosts(values: Mapping[str, Any]) -> Dict[str, str]:
    if values["redis"].get("mode") == "split":
        return {
            "persistent": "redis-persistent",
            "goo": "redis-goo-cache",
            "http": "redis-http-cache",
        }
    return {"persistent": "redis", "goo": "redis", "http": "redis"}


def solr_urls(values: Mapping[str, Any]) -> Dict[str, str]:
    port = int(values["solr"].get("port", 8983))
    if values["solr"].get("mode") == "split":
        return {
            "term": f"http://solr-term:{port}/solr/{values['solr']['termCore']}",
            "prop": f"http://solr-prop:{port}/solr/{values['solr']['propCore']}",
        }
    core_term = values["solr"]["termCore"]
    core_prop = values["solr"]["propCore"]
    return {
        "term": f"http://solr:{port}/solr/{core_term}",
        "prop": f"http://solr:{port}/solr/{core_prop}",
    }


def store_target(values: Mapping[str, Any]) -> Dict[str, str]:
    engine = str(values["store"].get("engine", "virtuoso")).lower()
    if engine == "external":
        return {
            "backend": values["store"].get("backendName", "sparql"),
            "host": str(values["store"].get("host", "")),
            "port": str(values["store"].get("port", "")),
        }
    if engine == "virtuoso":
        return {"backend": "virtuoso", "host": "virtuoso", "port": str(values["store"].get("port") or values["store"].get("service", {}).get("port") or 8890)}
    raise SystemExit("store.engine must be 'virtuoso' or 'external'")


def base_healthcheck(port: int, path: str = "/") -> Dict[str, Any]:
    return {
        "test": ["CMD-SHELL", f"curl -fsS http://localhost:{port}{path} >/dev/null || exit 1"],
        "interval": "20s",
        "timeout": "5s",
        "retries": 20,
    }


def solr_healthcheck() -> Dict[str, Any]:
    return {
        "test": ["CMD-SHELL", "solr status >/dev/null 2>&1 || /opt/solr/bin/solr status >/dev/null 2>&1"],
        "interval": "20s",
        "timeout": "5s",
        "retries": 30,
    }


def render(values: Dict[str, Any]) -> Dict[str, Any]:
    services: Dict[str, Any] = {}
    data_dir = "${DATA_DIR:-./data}"
    redis = redis_hosts(values)
    solr = solr_urls(values)
    store = store_target(values)
    api_dir = values["api"].get("appDir", "/srv/ontoportal/ontologies_api")
    cron_dir = values["cron"].get("appDir", "/srv/ontoportal/ncbo_cron")
    ui_dir = values["ui"].get("appDir", "/app")
    mgrep_port = int(values["mgrep"].get("containerPort") or values["mgrep"].get("service", {}).get("port", 55556))

    if service_enabled(values, "redis"):
        redis_common = {
            "image": image(values, "redis"),
            "restart": "unless-stopped",
            "command": ["redis-server", "--appendonly", "yes"],
        }
        if values["redis"].get("mode") == "split":
            for name in ["redis-persistent", "redis-goo-cache", "redis-http-cache"]:
                services[name] = copy.deepcopy(redis_common)
                services[name]["volumes"] = [f"{data_dir}/redis/{name}:/data"]
        else:
            services["redis"] = copy.deepcopy(redis_common)
            services["redis"]["volumes"] = [f"{data_dir}/redis:/data"]

    if service_enabled(values, "solr"):
        configsets_dir = f"{data_dir}/solr/configsets"
        services["solr-configsets"] = {
            "image": image(values, "cron"),
            "restart": "no",
            "volumes": [f"{configsets_dir}:/opt/solr-configsets"],
            "command": bash_command([
                "set -euo pipefail",
                "if [ -d /srv/ontoportal/ontologies_api ]; then cd /srv/ontoportal/ontologies_api; elif [ -d /srv/ontoportal/ncbo_cron ]; then cd /srv/ontoportal/ncbo_cron; fi",
                'gem_dir=$$(ruby -e \'require "bundler/setup"; %w[ontologies_linked_data ncbo_annotator ncbo_ontology_recommender].each { |g| p = Gem::Specification.find_by_name(g).full_gem_path rescue nil; if p && Dir.exist?("#{p}/config/solr"); print p; break; end }\' 2>/dev/null || true)',
                'default_conf=$$(ruby -e \'require "bundler/setup"; %w[ontologies_linked_data ncbo_annotator ncbo_cron ontologies_api].each { |g| p = Gem::Specification.find_by_name(g).full_gem_path rescue nil; if p && Dir.exist?("#{p}/test/solr/configsets/_default/conf"); print "#{p}/test/solr/configsets/_default/conf"; break; end }\' 2>/dev/null || true)',
                'if [ -z "$$gem_dir" ] || [ -z "$$default_conf" ]; then echo "ERROR: Solr configsets not found" >&2; exit 1; fi',
                'src="$$gem_dir/config/solr"',
                "mkdir -p /opt/solr-configsets",
                "rm -rf /opt/solr-configsets/term_search /opt/solr-configsets/property_search /opt/solr-configsets/_default",
                "mkdir -p /opt/solr-configsets/term_search/conf /opt/solr-configsets/property_search/conf /opt/solr-configsets/_default/conf",
                'cp -a "$$default_conf/." /opt/solr-configsets/_default/conf/',
                'cp -a "$$default_conf/." /opt/solr-configsets/term_search/conf/',
                'cp -a "$$default_conf/." /opt/solr-configsets/property_search/conf/',
                'cp -a "$$src/term_search/." /opt/solr-configsets/term_search/conf/',
                'cp -a "$$src/property_search/." /opt/solr-configsets/property_search/conf/',
                'for schema_file in /opt/solr-configsets/term_search/conf/schema.xml /opt/solr-configsets/property_search/conf/schema.xml; do '
                'if [ -f "$$schema_file" ] && ! grep -q \'name="resource_model"\' "$$schema_file"; then '
                'sed -i \'/name="resource_id"/a \\    <field name="resource_model" type="string" indexed="true" stored="true" multiValued="false" />\' "$$schema_file"; '
                "fi; done",
            ]),
        }
        solr_common = {
            "image": image(values, "solr"),
            "restart": "unless-stopped",
            "environment": {"SOLR_HEAP": "${SOLR_HEAP:-1g}"},
            "depends_on": {"solr-configsets": {"condition": "service_completed_successfully"}},
            "healthcheck": solr_healthcheck(),
        }
        if values["solr"].get("mode") == "split":
            term_core = str(values["solr"].get("termCore", "term_search_core1"))
            prop_core = str(values["solr"].get("propCore", "prop_search_core1"))
            services["solr-term"] = copy.deepcopy(solr_common)
            services["solr-term"]["ports"] = ["127.0.0.1:${SOLR_TERM_PORT:-8983}:8983"]
            services["solr-term"]["volumes"] = [
                f"{data_dir}/solr/term:/var/solr",
                f"{configsets_dir}:/opt/solr-configsets:ro",
            ]
            services["solr-term"]["command"] = bash_command([
                "set -euo pipefail",
                "mkdir -p /var/solr/data/configsets/_default",
                "if [ -d /opt/solr-configsets/_default ]; then cp -a /opt/solr-configsets/_default/. /var/solr/data/configsets/_default/; elif [ -d /opt/solr/server/solr/configsets/_default ]; then cp -a /opt/solr/server/solr/configsets/_default/. /var/solr/data/configsets/_default/; fi",
                f"if [ -d /opt/solr-configsets/term_search ]; then exec solr-precreate {shlex.quote(term_core)} /opt/solr-configsets/term_search; else exec solr-precreate {shlex.quote(term_core)}; fi",
            ])
            services["solr-prop"] = copy.deepcopy(solr_common)
            services["solr-prop"]["ports"] = ["127.0.0.1:${SOLR_PROP_PORT:-8984}:8983"]
            services["solr-prop"]["volumes"] = [
                f"{data_dir}/solr/prop:/var/solr",
                f"{configsets_dir}:/opt/solr-configsets:ro",
            ]
            services["solr-prop"]["command"] = bash_command([
                "set -euo pipefail",
                "mkdir -p /var/solr/data/configsets/_default",
                "if [ -d /opt/solr-configsets/_default ]; then cp -a /opt/solr-configsets/_default/. /var/solr/data/configsets/_default/; elif [ -d /opt/solr/server/solr/configsets/_default ]; then cp -a /opt/solr/server/solr/configsets/_default/. /var/solr/data/configsets/_default/; fi",
                f"if [ -d /opt/solr-configsets/property_search ]; then exec solr-precreate {shlex.quote(prop_core)} /opt/solr-configsets/property_search; else exec solr-precreate {shlex.quote(prop_core)}; fi",
            ])
        else:
            term_core = str(values["solr"].get("termCore", "term_search_core1"))
            prop_core = str(values["solr"].get("propCore", "prop_search_core1"))
            services["solr"] = copy.deepcopy(solr_common)
            services["solr"]["ports"] = ["127.0.0.1:${SOLR_PORT:-8983}:8983"]
            services["solr"]["volumes"] = [
                f"{data_dir}/solr:/var/solr",
                f"{configsets_dir}:/opt/solr-configsets:ro",
            ]
            services["solr"]["command"] = bash_command([
                "set -euo pipefail",
                "mkdir -p /var/solr/data/configsets/_default",
                "if [ -d /opt/solr-configsets/_default ]; then cp -a /opt/solr-configsets/_default/. /var/solr/data/configsets/_default/; elif [ -d /opt/solr/server/solr/configsets/_default ]; then cp -a /opt/solr/server/solr/configsets/_default/. /var/solr/data/configsets/_default/; fi",
                "solr start -p 8983",
                f'for core_cfg in {shlex.quote(term_core)}:/opt/solr-configsets/term_search {shlex.quote(prop_core)}:/opt/solr-configsets/property_search; do core="$${{core_cfg%%:*}}"; cfg="$${{core_cfg#*:}}"; if [ -d "$$cfg" ]; then solr create_core -c "$$core" -d "$$cfg" || true; else solr create_core -c "$$core" || true; fi; done',
                "solr stop -p 8983",
                "exec solr start -f -p 8983",
            ])

    if service_enabled(values, "store") and str(values["store"].get("engine", "virtuoso")).lower() == "virtuoso":
        services["virtuoso"] = {
            "image": image(values, "virtuoso"),
            "restart": "unless-stopped",
            "ports": ["127.0.0.1:${VIRTUOSO_PORT:-8890}:8890"],
            "environment": {"DBA_PASSWORD": "${STORE_DBA_PASSWORD:-change-me}"},
            "volumes": [f"{data_dir}/virtuoso:/data"],
        }

    if service_enabled(values, "mgrep"):
        command = values["mgrep"].get("command") or ""
        if not command:
            dict_path = values["mgrep"].get("dictionaryPath", "/data/mgrep/dictionary.txt")
            command = (
                f"mkdir -p $(dirname {dict_path}); "
                f"[ -s {dict_path} ] || (cp /srv/mgrep/dictionary/dictionary.txt {dict_path} 2>/dev/null || printf '0\\tDUMMY\\n' > {dict_path}); "
                f"mgrep --port {mgrep_port} -f {dict_path} -w /srv/mgrep/word_divider.txt -c /srv/mgrep/CaseFolding.txt && tail -f /dev/null"
            )
        cfg: Dict[str, Any] = {
            "image": image(values, "mgrep"),
            "restart": "unless-stopped",
            "ports": [f"127.0.0.1:${{MGREP_PORT:-{mgrep_port}}}:{mgrep_port}"],
            "volumes": [f"{data_dir}:/data"],
            "command": command,
        }
        services["mgrep"] = cfg

    if service_enabled(values, "mysql"):
        services["mysql"] = {
            "image": image(values, "mysql"),
            "restart": "unless-stopped",
            "environment": {
                "MYSQL_DATABASE": values["mysql"].get("database", "ontoportal_ui"),
                "MYSQL_ROOT_PASSWORD": "${MYSQL_ROOT_PASSWORD:-change-me}",
            },
            "ports": ["127.0.0.1:${MYSQL_PORT:-3306}:3306"],
            "volumes": [f"{data_dir}/mysql:/var/lib/mysql"],
            "healthcheck": {
                "test": ["CMD-SHELL", "mysqladmin ping -h 127.0.0.1 -p$${MYSQL_ROOT_PASSWORD:-change-me} --silent"],
                "interval": "20s",
                "timeout": "5s",
                "retries": 30,
            },
        }

    if service_enabled(values, "memcached"):
        services["memcached"] = {
            "image": image(values, "memcached"),
            "restart": "unless-stopped",
            "command": ["memcached", "-m", str(values["memcached"].get("memoryMb", 1024))],
        }

    depends_api: Dict[str, Dict[str, str]] = {}
    for dep in [redis["persistent"], redis["goo"], redis["http"], store["host"], "mgrep"]:
        if dep in services:
            depends_api[dep] = {"condition": "service_started"}
    for dep in ["solr-term", "solr-prop", "solr"]:
        if dep in services:
            depends_api[dep] = {"condition": "service_healthy"}

    if service_enabled(values, "api"):
        api_env = {
            "RACK_ENV": values["api"].get("rackEnv", "compose"),
            "RAILS_ENV": values["api"].get("railsEnv", "compose"),
            "BUNDLE_PATH": "/data/bundle/api",
            "OP_APIKEY": "${ONTOPORTAL_API_KEY:-change-me}",
            "API_KEY": "${ONTOPORTAL_API_KEY:-change-me}",
            "STORE_KB": values["store"].get("kbName", "ontoportal_kb"),
            "GOO_BACKEND_NAME": store["backend"],
            "GOO_HOST": store["host"],
            "GOO_PORT": store["port"],
            "GOO_PATH_DATA": values["store"].get("pathData", "/data/"),
            "GOO_PATH_QUERY": values["store"].get("pathQuery", "/sparql/"),
            "GOO_PATH_UPDATE": values["store"].get("pathUpdate", "/sparql/"),
            "REDIS_HOST": redis["persistent"],
            "REDIS_PORT": "6379",
            "REDIS_PERSISTENT_HOST": redis["persistent"],
            "REDIS_GOO_CACHE_HOST": redis["goo"],
            "REDIS_HTTP_CACHE_HOST": redis["http"],
            "SOLR_TERM_SEARCH_URL": solr["term"],
            "SOLR_PROP_SEARCH_URL": solr["prop"],
            "MGREP_HOST": "mgrep",
            "MGREP_PORT": str(values["mgrep"].get("service", {}).get("port", mgrep_port)),
            "MGREP_DICT_PATH": str(values["mgrep"].get("dictionaryPath", "/data/mgrep/dictionary.txt")),
            "MGREP_DICTIONARY_FILE": str(values["mgrep"].get("dictionaryPath", "/data/mgrep/dictionary.txt")),
            "REPOSITORY_FOLDER": "/data/repository",
            "REPORT_PATH": "/data/reports/ontologies_report.json",
            "REST_URL_PREFIX": values["api"].get("restUrlPrefix") or values["api"].get("publicUrl"),
            "PUBLIC_API_URL": values["ui"].get("publicApiUrl"),
            "ENABLE_SLICES": str(values["api"].get("enableSlices", "false")),
        }
        api_env.update(env_map(values, "api"))
        api_steps = [
            "mkdir -p /data/repository /data/reports /data/mgrep /data/api/log /data/api/tmp/pids /data/bundle/api /srv/ontoportal/data",
            "rm -rf log tmp || true",
            "ln -snf /data/api/log log",
            "ln -snf /data/api/tmp tmp",
            "ln -snf /data/repository /srv/ontoportal/data/repository",
            "ln -snf /data/reports /srv/ontoportal/data/reports",
            "ln -snf /data/mgrep /srv/ontoportal/data/mgrep",
            runtime_config_command(),
            "gem install bundler -v 2.3.27 >/dev/null 2>&1 || true",
            "bundle _2.3.27_ check || bundle _2.3.27_ install",
            "rm -f tmp/pids/*.pid || true",
            "exec " + bundle_command(values["api"].get("startCommand", "bundle exec rackup -o 0.0.0.0 --port 9393")),
        ]
        services["api"] = {
            "image": image(values, "api"),
            "restart": "unless-stopped",
            "depends_on": copy.deepcopy(depends_api),
            "ports": [f"${{API_BIND:-0.0.0.0}}:${{API_PORT:-{values['api']['service']['port']}}}:{values['api']['service']['port']}"],
            "environment": api_env,
            "volumes": [f"{data_dir}:/data"],
            "working_dir": api_dir,
            "command": bash_command(api_steps),
            "healthcheck": base_healthcheck(int(values["api"]["service"]["port"]), values["api"].get("probes", {}).get("readinessPath", "/status")),
        }

    if service_enabled(values, "cron"):
        cron_env = copy.deepcopy(services.get("api", {}).get("environment", {}))
        cron_env.update({
            "BUNDLE_PATH": "/data/bundle/cron",
            "ADMIN_USERNAME": values["secrets"].get("admin", {}).get("username", "admin"),
            "ADMIN_EMAIL": values["secrets"].get("admin", {}).get("email", "admin@example.org"),
            "ADMIN_PASSWORD": "${ADMIN_PASSWORD:-change-me}",
            "STARTER_ONTOLOGY": values["cron"].get("starterOntology", {}).get("acronym", ""),
            "OP_API_URL": values["cron"].get("starterOntology", {}).get("fromApiUrl", values["api"].get("publicUrl", "")),
        })
        if values["cron"].get("starterOntology", {}).get("enabled", False):
            cron_env["SOURCE_OP_APIKEY"] = "${SOURCE_OP_APIKEY:-}"
        cron_env.update(env_map(values, "cron"))
        cron_steps = [
            f"if [ -d {shlex.quote(cron_dir)} ]; then cd {shlex.quote(cron_dir)}; elif [ -d /srv/ontoportal/ontologies_api ]; then cd /srv/ontoportal/ontologies_api; elif [ -d /srv/ontoportal/ncbo_cron ]; then cd /srv/ontoportal/ncbo_cron; fi",
            "git config --global --add safe.directory '*' || true",
            "mkdir -p /data/repository /data/reports /data/mgrep /data/history /data/cron/logs /data/cron/tmp/pids /data/bundle/cron /srv/ontoportal/data",
            "rm -rf log logs tmp /usr/local/hist || true",
            "ln -snf /data/cron/logs log",
            "ln -snf /data/cron/logs logs",
            "ln -snf /data/cron/tmp tmp",
            "ln -snf /data/history /usr/local/hist",
            "ln -snf /data/repository /srv/ontoportal/data/repository",
            "ln -snf /data/reports /srv/ontoportal/data/reports",
            "ln -snf /data/mgrep /srv/ontoportal/data/mgrep",
            runtime_config_command(),
            "cp config/environments/compose.rb config/config.rb 2>/dev/null || true",
            "gem install bundler -v 2.3.27 >/dev/null 2>&1 || true",
            "bundle _2.3.27_ check || bundle _2.3.27_ install",
            (
                'NCBO_CRON_DIR="$$(bundle _2.3.27_ show ncbo_cron 2>/dev/null || true)"; '
                'if [ -n "$$NCBO_CRON_DIR" ]; then '
                'mkdir -p "$$NCBO_CRON_DIR/config"; '
                'cp config/environments/compose.rb "$$NCBO_CRON_DIR/config/config.rb"; '
                'fi'
            ),
            (
                'ANNO_DIR="$$(bundle _2.3.27_ show ncbo_annotator 2>/dev/null || true)"; '
                'if [ -n "$$ANNO_DIR" ] && [ -d "$$ANNO_DIR/lib/Lemmatizer" ]; then '
                'ln -snf "$$ANNO_DIR/lib/Lemmatizer" lib/Lemmatizer || true; '
                'fi'
            ),
            virtuoso_patch_command(),
        ]
        if values["secrets"].get("admin", {}).get("enabled", False):
            cron_steps.append(
                "if [ ! -f /data/cron/.admin_seeded ]; then "
                'RAKE_OPTS=""; '
                'if [ -n "$$NCBO_CRON_DIR" ] && [ -d "$$NCBO_CRON_DIR/rakelib" ]; then '
                'RAKE_OPTS="--rakelibdir $$NCBO_CRON_DIR/rakelib"; '
                "fi; "
                'if bundle _2.3.27_ exec rake $$RAKE_OPTS "user:create[$$ADMIN_USERNAME,$$ADMIN_EMAIL,$$ADMIN_PASSWORD]"; then '
                'bundle _2.3.27_ exec rake $$RAKE_OPTS "user:adminify[$$ADMIN_USERNAME]" || true; '
                "touch /data/cron/.admin_seeded; "
                'else echo "WARN: admin user seed failed or already exists" >&2; fi; fi'
            )
        if values["cron"].get("starterOntology", {}).get("enabled", False):
            starter_fail = "exit 1" if values["cron"].get("starterOntology", {}).get("required", False) else "true"
            cron_steps.append(
                "if [ ! -f /data/cron/.starter_ontology_imported ]; then "
                'NCBO_IMPORT="ncbo_ontology_import"; NCBO_PULL="ncbo_ontology_pull"; NCBO_PROCESS="ncbo_ontology_process"; '
                'if [ -f bin/ncbo_ontology_import ]; then NCBO_IMPORT="bin/ncbo_ontology_import"; NCBO_PULL="bin/ncbo_ontology_pull"; NCBO_PROCESS="bin/ncbo_ontology_process"; fi; '
                'if bundle _2.3.27_ exec $$NCBO_IMPORT --from-apikey "$${SOURCE_OP_APIKEY:-$${OP_APIKEY:-}}" -o "$${STARTER_ONTOLOGY}" --from "$${OP_API_URL}" --admin-user "$${ADMIN_USERNAME}" '
                '&& bundle _2.3.27_ exec $$NCBO_PULL -o "$${STARTER_ONTOLOGY}" '
                '&& bundle _2.3.27_ exec $$NCBO_PROCESS -o "$${STARTER_ONTOLOGY}"; then '
                "touch /data/cron/.starter_ontology_imported; "
                f"else echo 'WARN: starter ontology import failed' >&2; {starter_fail}; fi; fi"
            )
        cron_start = values["cron"].get("startCommand", "bundle exec bin/ncbo_cron")
        if cron_start == "bundle exec bin/ncbo_cron":
            cron_steps.append(
                "if [ -f bin/ncbo_cron ]; then "
                "exec bundle _2.3.27_ exec bin/ncbo_cron; "
                "else exec bundle _2.3.27_ exec ncbo_cron; fi"
            )
        else:
            cron_steps.append("exec " + bundle_command(cron_start))
        services["cron"] = {
            "image": image(values, "cron"),
            "restart": "unless-stopped",
            "depends_on": copy.deepcopy(depends_api),
            "environment": cron_env,
            "volumes": [f"{data_dir}:/data"],
            "command": bash_command(cron_steps),
        }

    if service_enabled(values, "ui"):
        ui_env = {
            "RAILS_ENV": values["ui"].get("railsEnv", "production"),
            "BUNDLE_PATH": "/data/bundle/ui",
            "SITE_NAME": values["ui"].get("siteName", "OntoPortal"),
            "ORG_NAME": values["ui"].get("orgName", "OntoPortal"),
            "ORG_URL": values["ui"].get("orgUrl", "https://ontoportal.org"),
            "SUPPORT_EMAIL": values["ui"].get("supportEmail", "support@example.org"),
            "UI_THEME": values["ui"].get("uiTheme", "ontoportal"),
            "UI_URL": values["ui"].get("uiUrl", "http://localhost:3000"),
            "PUBLIC_API_URL": values["ui"].get("publicApiUrl", "http://localhost:9393"),
            "FORCE_SSL": values["ui"].get("forceSsl", "false"),
            "MEMCACHE_SERVERS": "memcached:11211" if service_enabled(values, "memcached") else "",
            "MYSQL_HOST": "mysql" if service_enabled(values, "mysql") else "",
            "MYSQL_DATABASE": values["mysql"].get("database", "ontoportal_ui"),
            "MYSQL_ROOT_PASSWORD": "${MYSQL_ROOT_PASSWORD:-change-me}",
            "OP_API_KEY": "${ONTOPORTAL_API_KEY:-change-me}",
            "SESSION_COOKIE_KEY": values["ui"].get("sessionCookieKey", "_session_id"),
            "RAILS_FORCE_SSL": values["ui"].get("forceSsl", "false"),
            "DB_HOST": "mysql" if service_enabled(values, "mysql") else "",
            "BIOPORTAL_WEB_UI_DATABASE_PASSWORD": "${MYSQL_ROOT_PASSWORD:-change-me}",
            "CACHE_HOST": "memcached" if service_enabled(values, "memcached") else "",
            "API_KEY": "${ONTOPORTAL_API_KEY:-change-me}",
            "OP_APIKEY": "${ONTOPORTAL_API_KEY:-change-me}",
            "API_URL": f"http://api:{values['api']['service']['port']}",
            "ANNOTATOR_URL": f"http://api:{values['api']['service']['port']}/annotator",
            "SITE": values["ui"].get("siteName", "OntoPortal"),
            "ORG": values["ui"].get("orgName", "OntoPortal"),
            "RELEASE_VERSION": values["ui"].get("releaseVersion", "OntoPortal deployment"),
            "FAIRNESS_DISABLED": values["ui"].get("fairnessDisabled", "true"),
            "NCBO_ANNOTATORPLUS_ENABLED": values["ui"].get("annotatorPlusEnabled", "false"),
            "BIOMIXER_URL": values["ui"].get("biomixerUrl", ""),
            "BIOMIXER_PUBLIC_APIKEY": values["ui"].get("biomixerPublicApiKey", ""),
            "USE_LEGACY_BIOMIXER": values["ui"].get("useLegacyBiomixer", "true"),
            "ONTOPANEL_VISUALIZER_URL": values["ui"].get("ontopanelVisualizerUrl")
            or (f"http://localhost:${{ONTOPANEL_PORT:-{values['ontopanel']['service']['port']}}}" if service_enabled(values, "ontopanel") else ""),
            "SPARQL_URL": f"http://{store['host']}:{store['port']}{values['store'].get('pathQuery', '/sparql/')}",
            "PUBLIC_SPARQL_URL": values["ui"].get("publicSparqlUrl", ""),
            "PUBLIC_FAIRNESS_URL": values["fairness"].get("publicUrl", ""),
            "SESSION_COOKIE_DOMAIN": values["ui"].get("sessionCookieDomain", ""),
            "SESSION_COOKIE_SAME_SITE": values["ui"].get("sessionCookieSameSite", ""),
            "SESSION_COOKIE_SECURE": values["ui"].get("sessionCookieSecure", ""),
        }
        if service_enabled(values, "matomo"):
            ui_env.update({"MATOMO_URL": values["matomo"].get("url") or "http://matomo/", "MATOMO_SITE_ID": str(values["matomo"].get("siteId", 1))})
        if service_enabled(values, "fairness"):
            ui_env.update({"FAIRNESS_URL": values["fairness"].get("publicUrl") or "http://fairness:8080"})
        if service_enabled(values, "assistant"):
            ui_env["AI_ASSISTANT_BACKEND_URL"] = (
                f"http://assistant:{values['assistant']['service']['port']}{values['assistant'].get('endpointPath', '/api/v1/chat/stream')}"
            )
        ui_env.update(env_map(values, "ui"))
        ui_steps = [
            "mkdir -p /data/ui/log /data/ui/tmp/pids /data/bundle/ui",
            "rm -rf log tmp || true",
            "ln -snf /data/ui/log log",
            "ln -snf /data/ui/tmp tmp",
            "gem install bundler -v 2.3.27 >/dev/null 2>&1 || true",
            "bundle _2.3.27_ check || bundle _2.3.27_ install",
            (
                'CLIENT_GEM_PATH="$$(bundle _2.3.27_ show ontologies_api_client 2>/dev/null || true)"; '
                'if [ -n "$$CLIENT_GEM_PATH" ] && [ -f "$$CLIENT_GEM_PATH/lib/ontologies_api_client/models/class.rb" ]; then '
                "sed -i 's/hasChildren,childre,/hasChildren,children,/g' \"$$CLIENT_GEM_PATH/lib/ontologies_api_client/models/class.rb\" || true; "
                "fi"
            ),
        ]
        if values["ui"].get("runDbPrepare", False):
            ui_steps.append(
                "for i in $$(seq 1 30); do "
                "if bundle _2.3.27_ exec rails db:prepare; then break; fi; "
                "if [ \"$$i\" = \"30\" ]; then echo \"ERROR: rails db:prepare failed after $${i} attempts\" >&2; exit 1; fi; "
                "echo \"Waiting for UI database to become ready ($${i}/30)\" >&2; sleep 5; "
                "done"
            )
        ui_steps.extend([
            "rm -f tmp/pids/*.pid || true",
            "exec " + bundle_command(values["ui"].get("startCommand", "bundle exec puma -C config/puma.rb")),
        ])
        ui_depends: Dict[str, Dict[str, str]] = {"api": {"condition": "service_healthy"}} if "api" in services else {}
        if "mysql" in services:
            ui_depends["mysql"] = {"condition": "service_healthy"}
        if "memcached" in services:
            ui_depends["memcached"] = {"condition": "service_started"}
        if service_enabled(values, "assistant"):
            ui_depends["assistant"] = {"condition": "service_started"}
        ui_healthcheck = base_healthcheck(int(values["ui"]["service"]["port"]))
        ui_healthcheck["retries"] = 60
        services["ui"] = {
            "image": image(values, "ui"),
            "restart": "unless-stopped",
            "depends_on": ui_depends,
            "ports": [f"${{UI_BIND:-0.0.0.0}}:${{UI_PORT:-{values['ui']['service']['port']}}}:{values['ui']['service']['port']}"],
            "environment": ui_env,
            "volumes": [f"{data_dir}:/data"],
            "working_dir": ui_dir,
            "command": bash_command(ui_steps),
            "healthcheck": ui_healthcheck,
        }

    if service_enabled(values, "fairness"):
        services["fairness"] = {
            "image": image(values, "fairness"),
            "restart": "unless-stopped",
            "ports": [f"127.0.0.1:${{FAIRNESS_PORT:-{values['fairness']['service']['port']}}}:{values['fairness']['service']['port']}"],
            "environment": {"ONTOPORTAL_API_URL": values["ui"].get("publicApiUrl"), "ONTOPORTAL_API_KEY": "${ONTOPORTAL_API_KEY:-change-me}"},
        }

    if service_enabled(values, "matomo"):
        services["matomo-db"] = {
            "image": image(values, "matomoDb"),
            "restart": "unless-stopped",
            "environment": {
                "MARIADB_DATABASE": values["matomo"].get("db", {}).get("name", "matomo"),
                "MARIADB_USER": values["matomo"].get("db", {}).get("user", "matomo"),
                "MARIADB_PASSWORD": "${MATOMO_DB_PASSWORD:-change-me}",
                "MARIADB_ROOT_PASSWORD": "${MATOMO_DB_ROOT_PASSWORD:-change-me}",
            },
            "volumes": [f"{data_dir}/matomo-db:/var/lib/mysql"],
        }
        services["matomo"] = {
            "image": image(values, "matomo"),
            "restart": "unless-stopped",
            "depends_on": {"matomo-db": {"condition": "service_started"}},
            "ports": ["${MATOMO_BIND:-127.0.0.1}:${MATOMO_PORT:-8088}:80"],
            "environment": {
                "MATOMO_DATABASE_HOST": "matomo-db",
                "MATOMO_DATABASE_DBNAME": values["matomo"].get("db", {}).get("name", "matomo"),
                "MATOMO_DATABASE_USERNAME": values["matomo"].get("db", {}).get("user", "matomo"),
                "MATOMO_DATABASE_PASSWORD": "${MATOMO_DB_PASSWORD:-change-me}",
            },
            "volumes": [f"{data_dir}/matomo:/var/www/html"],
        }

    if service_enabled(values, "assistant"):
        assistant_env = {
            "ONTOPORTAL_API_URL": values["ui"].get("publicApiUrl"),
            "ONTOPORTAL_API_KEY": "${ONTOPORTAL_API_KEY:-change-me}",
            "INTERNAL_API_TOKEN": "${ASSISTANT_INTERNAL_TOKEN:-change-me}",
            "OPENAI_API_KEY": "${OPENAI_API_KEY:-}",
        }
        if values["assistant"].get("databaseUrl"):
            assistant_env["DATABASE_URL"] = str(values["assistant"].get("databaseUrl"))
        services["assistant"] = {
            "image": image(values, "assistant"),
            "restart": "unless-stopped",
            "depends_on": {"api": {"condition": "service_healthy"}} if "api" in services else {},
            "ports": [f"127.0.0.1:${{ASSISTANT_PORT:-{values['assistant']['service']['port']}}}:{values['assistant']['service']['port']}"],
            "environment": assistant_env,
        }

    if service_enabled(values, "ontopanel"):
        services["ontopanel"] = {
            "image": image(values, "ontopanel"),
            "restart": "unless-stopped",
            "ports": [f"127.0.0.1:${{ONTOPANEL_PORT:-{values['ontopanel']['service']['port']}}}:{values['ontopanel']['service']['port']}"],
        }

    return {"name": values.get("profile", {}).get("name", "ontoportal"), "services": services}


def env_sample(values: Mapping[str, Any]) -> str:
    lines = [
        f"# Generated sample for profile: {values.get('profile', {}).get('name', 'ontoportal')}",
        "DATA_DIR=./data",
        "ONTOPORTAL_API_KEY=change-me",
        "ADMIN_PASSWORD=change-me",
        "MYSQL_ROOT_PASSWORD=change-me",
        "STORE_DBA_PASSWORD=change-me",
        "STORE_DAV_PASSWORD=change-me",
        "MATOMO_DB_PASSWORD=change-me",
        "MATOMO_DB_ROOT_PASSWORD=change-me",
    ]
    if service_enabled(values, "assistant"):
        lines.extend([
            "ASSISTANT_INTERNAL_TOKEN=change-me",
            "OPENAI_API_KEY=",
        ])
    lines.extend([
        "API_BIND=0.0.0.0",
        f"API_PORT={values.get('api', {}).get('service', {}).get('port', 9393)}",
        "UI_BIND=0.0.0.0",
        f"UI_PORT={values.get('ui', {}).get('service', {}).get('port', 3000)}",
        "SOLR_HEAP=1g",
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Docker Compose from OntoPortal Helm values")
    parser.add_argument("-f", "--values", action="append", type=Path, default=[], help="Values YAML to merge after chart defaults. Repeatable.")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Compose YAML output path")
    parser.add_argument("--env-output", type=Path, default=None, help=".env sample output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    values = load_yaml(BASE_VALUES)
    for vf in args.values:
        path = vf if vf.is_absolute() else REPO_ROOT / vf
        values = deep_merge(values, load_yaml(path))
    profile = values.get("profile", {}).get("name", "ontoportal")
    output = args.output or REPO_ROOT / "compose" / "generated" / f"docker-compose.{profile}.yml"
    env_output = args.env_output or REPO_ROOT / "compose" / "generated" / f".env.{profile}.sample"
    output.parent.mkdir(parents=True, exist_ok=True)
    env_output.parent.mkdir(parents=True, exist_ok=True)
    rendered = render(values)
    with output.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(rendered, fh, sort_keys=False, default_flow_style=False)
    env_output.write_text(env_sample(values), encoding="utf-8")
    print(f"wrote {display_path(output)}")
    print(f"wrote {display_path(env_output)}")


if __name__ == "__main__":
    main()
