#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
EMAIL="${EMAIL:-test@example.com}"
PASSWORD="${PASSWORD:-password123}"
TOKEN="${TOKEN:-}"
OUT="${OUT:-smoke_$(date +'%Y%m%d_%H%M%S').log}"

COOKIE_JAR="$(mktemp)"
HEADERS_TMP="$(mktemp)"
BODY_TMP="$(mktemp)"

section() { echo -e "\n===== $* =====" | tee -a "$OUT"; }
note()    { echo -e "-- $*" | tee -a "$OUT"; }

dump_curl() {
  local method="$1"; shift
  local url="$1"; shift
  local data="${1:-}"

  local AUTH_HEADER_STR=""
  [[ -n "$TOKEN" ]] && AUTH_HEADER_STR="-H Authorization: Bearer\ ${TOKEN}"

  local CMD="curl -sS -X ${method} ${url} -D ${HEADERS_TMP} -b ${COOKIE_JAR} -c ${COOKIE_JAR} -o ${BODY_TMP} -w $'\\n[HTTP %{http_code}]\\n' ${AUTH_HEADER_STR}"
  [[ -n "$data" ]] && CMD="curl -sS -X ${method} ${url} -H 'Content-Type: application/json' -d '${data//\'/\'\"\'\"\'}' -D ${HEADERS_TMP} -b ${COOKIE_JAR} -c ${COOKIE_JAR} -o ${BODY_TMP} -w $'\\n[HTTP %{http_code}]\\n' ${AUTH_HEADER_STR}"

  printf '%s\n' "\$ ${CMD}" | tee -a "$OUT" >/dev/null
  eval "${CMD}" | tee -a "$OUT"
  echo | tee -a "$OUT"
  echo "--- headers ---" | tee -a "$OUT"; cat "$HEADERS_TMP" | tee -a "$OUT"
  echo -e "\n--- body ---" | tee -a "$OUT"; cat "$BODY_TMP" | tee -a "$OUT"; echo | tee -a "$OUT"
}

extract_json_value() {
  local file="$1" key="$2"
  if command -v jq >/dev/null 2>&1; then jq -r --arg k "$key" '.[$k] // empty' "$file"; return; fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$file" "$key" <<'PY'
import json, sys
p, k = sys.argv[1], sys.argv[2]
try:
    with open(p) as f: d = json.load(f)
    v = d.get(k, "")
    print("" if isinstance(v, (dict, list)) else v)
except: print("")
PY
    return
  fi
  grep -o "\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$file" 2>/dev/null | head -n1 | sed -E "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"([^\"]*)\".*/\1/"
}

route_exists() {
  local path="$1"
  if ! command -v jq >/dev/null 2>&1; then return 0; fi  # skip check if jq missing
  jq -e --arg p "$path" '.paths[$p] | objects' "$BODY_TMP" >/dev/null 2>&1
}

echo "Writing output to: $OUT"
echo "Base URL: $BASE" | tee "$OUT"

section "M1 — Health checks"
dump_curl GET "${BASE}/health"             # may be 404 if double-prefixed
dump_curl GET "${BASE}/"                   # should be 200

section "Introspect OpenAPI"
dump_curl GET "${BASE}/openapi.json"
HAS_LIB_ROUTES="yes"
if command -v jq >/dev/null 2>&1; then
  if ! route_exists "/libraries" && ! route_exists "/libraries/{library_id}"; then
    HAS_LIB_ROUTES="no"
    note "Libraries routes NOT found in OpenAPI; will skip M3 library tests (fix router import)."
  fi
fi

section "M1 — Auth (login or use existing token)"
if [[ -z "$TOKEN" ]]; then
  note "Trying /auth/login (set TOKEN env if you want to skip login)"
  LOGIN_PAYLOAD=$(cat <<JSON
{"email":"${EMAIL}","password":"${PASSWORD}"}
JSON
)
  dump_curl POST "${BASE}/auth/login" "$LOGIN_PAYLOAD"
  TOKEN="$(extract_json_value "$BODY_TMP" "access_token" || true)"
  if [[ -z "$TOKEN" ]]; then
    note "No token. Protected endpoints (validate, libraries, citations) will likely return 401."
  else
    note "Access token acquired."
  fi
else
  note "Using TOKEN from env."
fi

section "M2 — Source types discovery"
dump_curl GET "${BASE}/citations/types"
dump_curl GET "${BASE}/meta/source-types"

if [[ -n "$TOKEN" ]]; then
  section "M2 — Validation (dry-run)"
  VALIDATE_PAYLOAD=$(cat <<'JSON'
{
  "type": "book",
  "details": {
    "authors": ["Doe, Jane", "Smith, John"],
    "title": "The Test Book",
    "publisher": "Testing House",
    "year": "2021",
    "city_of_publication": "New York"
  }
}
JSON
)
  dump_curl POST "${BASE}/citations/validate" "$VALIDATE_PAYLOAD"
else
  note "Skipping validation (no token)."
fi

if [[ "$HAS_LIB_ROUTES" == "yes" && -n "$TOKEN" ]]; then
  section "M3 — Create a library"
  LIB_CREATE_PAYLOAD=$(cat <<'JSON'
{ "name": "Smoke Test Library" }
JSON
)
  dump_curl POST "${BASE}/libraries" "$LIB_CREATE_PAYLOAD"
  LIBRARY_ID="$(extract_json_value "$BODY_TMP" "id" || true)"
  note "LIBRARY_ID=${LIBRARY_ID}"

  section "M3 — List libraries"
  dump_curl GET "${BASE}/libraries"

  section "M3 — Rename the library"
  LIB_RENAME_PAYLOAD=$(cat <<'JSON'
{ "name": "Smoke Test Library (Renamed)" }
JSON
)
  dump_curl PATCH "${BASE}/libraries/${LIBRARY_ID}" "$LIB_RENAME_PAYLOAD"

  section "M3 — Create a citation (book) in the library"
  CREATE_CITATION_PAYLOAD=$(cat <<JSON
{
  "library_id": ${LIBRARY_ID},
  "type": "book",
  "details": {
    "authors": ["Doe, Jane"],
    "title": "Service-Oriented Testing",
    "publisher": "ACME Press",
    "year": "2020",
    "city_of_publication": "Boston"
  },
  "style": "apa"
}
JSON
)
  dump_curl POST "${BASE}/citations" "$CREATE_CITATION_PAYLOAD"
  CITATION_ID="$(extract_json_value "$BODY_TMP" "id" || true)"
  note "CITATION_ID=${CITATION_ID}"

  section "M3 — Get the citation"
  dump_curl GET "${BASE}/citations/${CITATION_ID}"

  section "M3 — List citations in the library"
  dump_curl GET "${BASE}/citations?library_id=${LIBRARY_ID}"

  section "M3 — Patch the citation (update details + style)"
  PATCH_CITATION_PAYLOAD=$(cat <<'JSON'
{
  "details": {
    "title": "Service-Oriented Testing (2nd ed.)",
    "year": "2022"
  },
  "style": "mla"
}
JSON
)
  dump_curl PATCH "${BASE}/citations/${CITATION_ID}" "$PATCH_CITATION_PAYLOAD"

  section "M3 — Create another library and move the citation"
  LIB2_CREATE_PAYLOAD=$(cat <<'JSON'
{ "name": "Smoke Test Library #2" }
JSON
)
  dump_curl POST "${BASE}/libraries" "$LIB2_CREATE_PAYLOAD"
  LIBRARY2_ID="$(extract_json_value "$BODY_TMP" "id" || true)"
  note "LIBRARY2_ID=${LIBRARY2_ID}"

  MOVE_CITATION_PAYLOAD=$(cat <<JSON
{ "library_id": ${LIBRARY2_ID} }
JSON
)
  dump_curl PATCH "${BASE}/citations/${CITATION_ID}" "$MOVE_CITATION_PAYLOAD"

  section "M3 — Delete citation"
  dump_curl DELETE "${BASE}/citations/${CITATION_ID}"

  section "M3 — Cleanup: delete both libraries"
  dump_curl DELETE "${BASE}/libraries/${LIBRARY2_ID}"
  dump_curl DELETE "${BASE}/libraries/${LIBRARY_ID}"
else
  note "Skipping M3 (libraries/citations) because routes not mounted or no token."
fi

section "Done"
note "Full log saved to: ${OUT}"
