#!/usr/bin/env bash
# ponytail: simple ontology importer that uploads a tiny turtle ontology
set -euo pipefail

API_PORT="${API_PORT:-19393}"
PORT_FORWARD_ADDRESS="${PORT_FORWARD_ADDRESS:-127.0.0.1}"
PORT_FORWARD_WAIT_SECONDS="${PORT_FORWARD_WAIT_SECONDS:-20}"
: "${KUBECTL:=kubectl}"

NCBO_PROCESS_TIMEOUT_SECONDS="${NCBO_PROCESS_TIMEOUT_SECONDS:-900}"
NCBO_PROCESS_LOG_TAIL="${NCBO_PROCESS_LOG_TAIL:-200}"
NCBO_PROCESS_TASKS="${NCBO_PROCESS_TASKS:-process_rdf,generate_labels,index_all_data,index_search,process_annotator}"
SMOKE_ONTOLOGY_ACRONYM="${SMOKE_ONTOLOGY_ACRONYM:-SMOKETEST}"
SMOKE_SEARCH_TERM="${SMOKE_SEARCH_TERM:-Smoke Test Class}"
SMOKE_ANNOTATOR_TEXT="${SMOKE_ANNOTATOR_TEXT:-Smoke Test Class}"

ENV_FILE=""
NAMESPACE_ARG=""
RELEASE_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="${2:?--env-file requires a path}"
      shift 2
      ;;
    *)
      if [[ -z "${NAMESPACE_ARG}" ]]; then
        NAMESPACE_ARG="$1"
      elif [[ -z "${RELEASE_ARG}" ]]; then
        RELEASE_ARG="$1"
      else
        echo "ERROR: unexpected argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

NAMESPACE="${NAMESPACE_ARG:-ontoportal}"
RELEASE="${RELEASE_ARG:-ontoportal}"
SERVICE_PREFIX="${SERVICE_PREFIX:-${RELEASE}}"

TMP_DIR="$(mktemp -d -t ontoportal-import-smoke.XXXXXX)"
PF_PIDS=()
AUTH_CONFIG=""

cleanup() {
  for pid in "${PF_PIDS[@]:-}"; do
    kill "${pid}" >/dev/null 2>&1 || true
  done
  if [[ -n "${IMPORT_SMOKE_LOG_DIR:-}" ]]; then
    mkdir -p "${IMPORT_SMOKE_LOG_DIR}"
    for log in ontology-process.log last-search.json last-annotator.json; do
      if [[ -f "${TMP_DIR}/${log}" ]]; then
        cp "${TMP_DIR}/${log}" "${IMPORT_SMOKE_LOG_DIR}/"
      fi
    done
  fi
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

wait_for_tcp() {
  local port="$1"
  local deadline=$((SECONDS + PORT_FORWARD_WAIT_SECONDS))
  while (( SECONDS < deadline )); do
    if python3 - "${port}" <<'PY' >/dev/null 2>&1
import socket
import sys
with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1):
    pass
PY
    then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_port_forward() {
  local service="$1"
  local local_port="$2"
  local remote_port="$3"
  local label="$4"
  local log_file="${TMP_DIR}/${label}.port-forward.log"

  "${KUBECTL}" -n "${NAMESPACE}" port-forward --address "${PORT_FORWARD_ADDRESS}" "svc/${service}" "${local_port}:${remote_port}" >"${log_file}" 2>&1 &
  local pid="$!"
  PF_PIDS+=("${pid}")

  if wait_for_tcp "${local_port}"; then
    echo "[port-forward] ${service} ${local_port}:${remote_port} ready" >&2
    return 0
  fi

  echo "ERROR: port-forward failed for svc/${service} on ${local_port}:${remote_port}" >&2
  cat "${log_file}" >&2 || true
  return 1
}

if [[ -z "${API_BASE_URL:-}" ]]; then
  start_port_forward "${SERVICE_PREFIX}-api" "${API_PORT}" 9393 api
  API_BASE_URL="http://127.0.0.1:${API_PORT}"
fi

if [[ -z "${OP_APIKEY:-}" ]]; then
  OP_APIKEY=$("${KUBECTL}" -n "${NAMESPACE}" get secret "${SERVICE_PREFIX}-secrets" -o jsonpath='{.data.apiKey}' 2>/dev/null | base64 --decode || true)
fi

if [[ -z "${OP_APIKEY:-}" ]]; then
  echo "ERROR: OP_APIKEY is not set and could not be retrieved from secret ${SERVICE_PREFIX}-secrets" >&2
  exit 1
fi

AUTH_CONFIG="${TMP_DIR}/curl-auth.conf"
umask 077
printf 'header = "Authorization: apikey token=%s"\n' "${OP_APIKEY}" >"${AUTH_CONFIG}"

api_curl() {
  curl --config "${AUTH_CONFIG}" -H 'Accept: application/json' "$@"
}

json_count_positive() {
  jq -e '
    def has_errors:
      (type == "object") and (((.errors? // []) | length) > 0 or has("error"));
    if has_errors then false
    elif type == "array" then length > 0
    elif (.collection? | type) == "array" then (.collection | length) > 0
    elif (.annotations? | type) == "array" then (.annotations | length) > 0
    elif type == "object" and has("annotatedClass") then true
    else false
    end
  ' >/dev/null 2>&1
}

cat << 'EOF' > "${TMP_DIR}/smoke.ttl"
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://example.org/smoke#> .

<http://example.org/smoke> a owl:Ontology .

:SmokeClass a owl:Class ;
    rdfs:label "Smoke Test Class" ;
    rdfs:comment "A class for smoke testing" .
EOF

echo "Checking if ontology ${SMOKE_ONTOLOGY_ACRONYM} exists..." >&2
status_code=$(api_curl -s -o /dev/null -w "%{http_code}" "${API_BASE_URL%/}/ontologies/${SMOKE_ONTOLOGY_ACRONYM}" || true)

if [[ "${status_code}" == "200" ]]; then
  echo "Ontology ${SMOKE_ONTOLOGY_ACRONYM} already exists." >&2
else
  echo "Creating ontology ${SMOKE_ONTOLOGY_ACRONYM}..." >&2
  api_curl -fsS -X PUT "${API_BASE_URL%/}/ontologies/${SMOKE_ONTOLOGY_ACRONYM}" \
    -F "acronym=${SMOKE_ONTOLOGY_ACRONYM}" \
    -F "name=Smoke Test Ontology" \
    -F "hasOntologyLanguage=OWL" \
    -F "administeredBy[]=admin" >/dev/null
fi

echo "Uploading ontology submission..." >&2
submission_status=$(api_curl -sS -o "${TMP_DIR}/submission-response.json" -w "%{http_code}" -X POST "${API_BASE_URL%/}/ontologies/${SMOKE_ONTOLOGY_ACRONYM}/submissions" \
  -F "name=Smoke Test Ontology" \
  -F "administeredBy=admin" \
  -F "contact[][name]=Admin" \
  -F "contact[][email]=admin@example.org" \
  -F "description=Smoke Test Submission" \
  -F "released=$(date +%Y-%m-%d)" \
  -F "status=production" \
  -F "hasOntologyLanguage=OWL" \
  -F "URI=http://example.org/smoke" \
  -F "version=1.0.0" \
  -F "file=@${TMP_DIR}/smoke.ttl")
if [[ "${submission_status}" != "201" ]]; then
  echo "ERROR: ontology submission returned HTTP ${submission_status}" >&2
  cat "${TMP_DIR}/submission-response.json" >&2 || true
  exit 1
fi

if "${KUBECTL}" -n "${NAMESPACE}" get deployment "${SERVICE_PREFIX}-cron" >/dev/null 2>&1; then
  echo "Triggering ontology processing on cron pod..." >&2
  CRON_POD=$("${KUBECTL}" -n "${NAMESPACE}" get pods -l "app.kubernetes.io/instance=${RELEASE},app.kubernetes.io/component=cron" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -n "${CRON_POD}" ]]; then
    if ! command -v timeout >/dev/null 2>&1; then
      echo "ERROR: timeout command is required to bound ncbo_ontology_process" >&2
      exit 1
    fi
    set +e
    timeout --kill-after=30s "${NCBO_PROCESS_TIMEOUT_SECONDS}s" \
      "${KUBECTL}" -n "${NAMESPACE}" exec "${CRON_POD}" -- \
      bash -c 'if [ -f bin/ncbo_ontology_process ]; then exec bundle exec bin/ncbo_ontology_process "$@"; else exec bundle exec ncbo_ontology_process "$@"; fi' -- -o "${SMOKE_ONTOLOGY_ACRONYM}" -t "${NCBO_PROCESS_TASKS}" >"${TMP_DIR}/ontology-process.log" 2>&1
    process_rc=$?
    set -e
    case "${process_rc}" in
      0)
        echo "ncbo_ontology_process completed successfully." >&2
        ;;
      124|137)
        echo "WARN: ncbo_ontology_process exceeded ${NCBO_PROCESS_TIMEOUT_SECONDS}s; tailing last ${NCBO_PROCESS_LOG_TAIL} lines:" >&2
        tail -n "${NCBO_PROCESS_LOG_TAIL}" "${TMP_DIR}/ontology-process.log" >&2 || true
        echo "WARN: ncbo_ontology_process timed out; continuing to poll API for search/annotator readiness." >&2
        ;;
      *)
        echo "WARN: ncbo_ontology_process exited ${process_rc}; tailing last ${NCBO_PROCESS_LOG_TAIL} lines:" >&2
        tail -n "${NCBO_PROCESS_LOG_TAIL}" "${TMP_DIR}/ontology-process.log" >&2 || true
        echo "Continuing to poll API..." >&2
        ;;
    esac
    if [[ "${RESTART_MGREP_AFTER_ANNOTATOR:-true}" == "true" ]] && "${KUBECTL}" -n "${NAMESPACE}" get deployment "${SERVICE_PREFIX}-mgrep" >/dev/null 2>&1; then
      echo "Restarting mgrep to load generated annotator dictionary..." >&2
      "${KUBECTL}" -n "${NAMESPACE}" rollout restart deployment "${SERVICE_PREFIX}-mgrep" >/dev/null
      "${KUBECTL}" -n "${NAMESPACE}" rollout status deployment "${SERVICE_PREFIX}-mgrep" --timeout=5m >&2
    fi
  else
    echo "WARN: cron pod not found" >&2
  fi
fi

echo "Polling for ontology to be parsed and indexed..." >&2
MAX_POLLS="${MAX_POLLS:-90}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
SUCCESS=false

for ((i=1; i<=MAX_POLLS; i++)); do
  search_res=$(api_curl -sG "${API_BASE_URL%/}/search" --data-urlencode "q=${SMOKE_SEARCH_TERM}" --data-urlencode "ontologies=${SMOKE_ONTOLOGY_ACRONYM}" || true)
  printf '%s\n' "${search_res}" >"${TMP_DIR}/last-search.json"
  if echo "${search_res}" | json_count_positive; then
    anno_res=$(api_curl -sG "${API_BASE_URL%/}/annotator" --data-urlencode "text=${SMOKE_ANNOTATOR_TEXT}" --data-urlencode "ontologies=${SMOKE_ONTOLOGY_ACRONYM}" --data-urlencode 'format=json' || true)
    printf '%s\n' "${anno_res}" >"${TMP_DIR}/last-annotator.json"
    if echo "${anno_res}" | json_count_positive; then
      SUCCESS=true
      break
    fi
  fi
  echo "Waiting for ontology processing... (attempt $i/$MAX_POLLS)" >&2
  sleep "${POLL_INTERVAL}"
done

if [[ "${SUCCESS}" != "true" ]]; then
  echo "ERROR: Ontology processing timed out or failed to parse/index correctly." >&2
  for log in last-search.json last-annotator.json; do
    if [[ -s "${TMP_DIR}/${log}" ]]; then
      echo "${log}: $(jq -c 'if type == "array" then {type, length} elif type == "object" then {type, keys: keys, errors: .errors?} else {type} end' "${TMP_DIR}/${log}" 2>/dev/null || head -c 200 "${TMP_DIR}/${log}")" >&2
    fi
  done
  exit 1
fi

ENV_CONTENT="APP_SMOKE_ONTOLOGY=${SMOKE_ONTOLOGY_ACRONYM}
APP_SMOKE_SEARCH_TERM=\"${SMOKE_SEARCH_TERM}\"
APP_SMOKE_ANNOTATOR_TEXT=\"${SMOKE_ANNOTATOR_TEXT}\"
TEST_ONTOLOGY_ACRONYM=${SMOKE_ONTOLOGY_ACRONYM}
TEST_ONTOLOGY_TERM=\"${SMOKE_SEARCH_TERM}\"
TEST_ANNOTATOR_TEXT=\"${SMOKE_ANNOTATOR_TEXT}\""

if [[ -n "${ENV_FILE}" ]]; then
  echo "${ENV_CONTENT}" > "${ENV_FILE}"
  echo "Wrote env variables to ${ENV_FILE}" >&2
else
  echo "${ENV_CONTENT}"
fi
