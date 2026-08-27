#!/bin/sh
set -eu

environment_file=${1:-${STACK_ENV_FILE:-.env}}

test -f "$environment_file" || {
  echo "Missing no-key environment file: $environment_file" >&2
  exit 1
}

effective_value() {
  variable=$1
  if value=$(printenv "$variable"); then
    printf '%s\n' "$value"
  else
    sed -n "s/^${variable}=//p" "$environment_file" | tail -n 1
  fi
}

for variable in \
  OPENAI_API_KEY \
  MODEL_GATEWAY_API_KEY \
  MODEL_GATEWAY_BASE_URL \
  MODEL_GATEWAY_FALLBACK_MODE \
  MODEL_GATEWAY_FALLBACK_MODEL
do
  test -z "$(effective_value "$variable")" || {
    echo "The deterministic release gate requires $variable to be empty." >&2
    echo "Run provider-smoke separately with an ignored, authorized provider configuration." >&2
    exit 1
  }
done

mode=$(effective_value MODEL_GATEWAY_MODE)
mode=${mode:-openai}
test "$mode" != "openai-compatible" || {
  echo "The deterministic release gate does not accept an openai-compatible provider profile." >&2
  echo "Use the no-key profile and run provider-smoke separately." >&2
  exit 1
}

echo "Release configuration is deterministic/no-key."
