#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
validator="$project_root/scripts/validate-release-no-key.sh"
fixture=$(mktemp "${TMPDIR:-/tmp}/agreement-release-no-key.XXXXXX")
trap 'rm -f "$fixture"' EXIT HUP INT TERM

write_fixture() {
  cat >"$fixture" <<EOF
OPENAI_API_KEY=$1
MODEL_GATEWAY_API_KEY=$2
MODEL_GATEWAY_MODE=$3
MODEL_GATEWAY_BASE_URL=$4
MODEL_GATEWAY_FALLBACK_MODE=$5
MODEL_GATEWAY_FALLBACK_MODEL=$6
EOF
}

validate_clean_environment() {
  env \
    -u OPENAI_API_KEY \
    -u MODEL_GATEWAY_API_KEY \
    -u MODEL_GATEWAY_MODE \
    -u MODEL_GATEWAY_BASE_URL \
    -u MODEL_GATEWAY_FALLBACK_MODE \
    -u MODEL_GATEWAY_FALLBACK_MODEL \
    "$validator" "$fixture"
}

write_fixture "" "" openai "" "" ""
validate_clean_environment

for case_name in openai_key compatible_mode hosted_fallback; do
  case "$case_name" in
    openai_key) write_fixture synthetic-key "" openai "" "" "" ;;
    compatible_mode) write_fixture "" "" openai-compatible http://127.0.0.1:8080/v1 "" "" ;;
    hosted_fallback) write_fixture "" "" openai "" openai gpt-5.4-mini ;;
  esac
  if validate_clean_environment >/dev/null 2>&1; then
    echo "No-key validation accepted provider-enabled case: $case_name" >&2
    exit 1
  fi
done

write_fixture "" "" openai "" "" ""
if env \
  -u MODEL_GATEWAY_API_KEY \
  -u MODEL_GATEWAY_MODE \
  -u MODEL_GATEWAY_BASE_URL \
  -u MODEL_GATEWAY_FALLBACK_MODE \
  -u MODEL_GATEWAY_FALLBACK_MODEL \
  OPENAI_API_KEY=synthetic-env-key \
  "$validator" "$fixture" >/dev/null 2>&1
then
  echo "No-key validation ignored an effective environment override." >&2
  exit 1
fi

echo "Release no-key configuration contracts pass."
