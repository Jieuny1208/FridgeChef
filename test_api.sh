#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

set -a; source ./.env; set +a
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY missing in .env}"

MODEL="google/gemma-4-31b-it:free"
ENDPOINT="https://openrouter.ai/api/v1/chat/completions"
HDR_REFERER="HTTP-Referer: http://localhost"
HDR_TITLE="X-Title: Study-04 API Test"

call_api () {
  local payload="$1"
  curl -sS -w "\n__HTTP__%{http_code}" "$ENDPOINT" \
    -H "Authorization: Bearer $OPENROUTER_API_KEY" \
    -H "Content-Type: application/json" \
    -H "$HDR_REFERER" -H "$HDR_TITLE" \
    -d "$payload"
}

show () {
  local resp="$1"
  local body="${resp%__HTTP__*}"
  local code="${resp##*__HTTP__}"
  echo "HTTP $code"
  if echo "$body" | jq -e '.choices[0].message.content' >/dev/null 2>&1; then
    echo "$body" | jq '{model, content: .choices[0].message.content, finish_reason: .choices[0].finish_reason, usage}'
  else
    echo "$body"
  fi
}

echo "=========================================="
echo "  Test 1: TEXT  ($MODEL)"
echo "=========================================="
text_payload=$(jq -n --arg model "$MODEL" '{
  model: $model,
  messages: [
    {role:"user", content:"Reply in one short sentence in Korean: confirm the connection works and tell me what model you are."}
  ]
}')
show "$(call_api "$text_payload")"

echo
echo "=========================================="
echo "  Test 2: IMAGE  ($MODEL)"
echo "=========================================="
IMG="sample_fridge.jpg"
[ -f "$IMG" ] || { echo "Image $IMG not found"; exit 1; }
img_b64=$(base64 -i "$IMG" | tr -d '\n')
data_url="data:image/jpeg;base64,$img_b64"

img_payload=$(jq -n --arg model "$MODEL" --arg url "$data_url" '{
  model: $model,
  messages: [
    {role:"user", content: [
       {type:"text", text:"이 이미지에 무엇이 보이는지 한국어로 2-3문장으로 설명해줘."},
       {type:"image_url", image_url: {url:$url}}
    ]}
  ]
}')
show "$(call_api "$img_payload")"
