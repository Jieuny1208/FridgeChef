#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
set -a; source ./.env; set +a

img_b64=$(base64 -i sample_fridge.jpg | tr -d '\n')
payload=$(jq -n --arg url "data:image/jpeg;base64,$img_b64" '{
  model: "google/gemma-4-31b-it:free",
  messages:[{role:"user", content:[
    {type:"text", text:"이 이미지에 무엇이 보이는지 한국어로 2-3문장으로 설명해줘."},
    {type:"image_url", image_url:{url:$url}}
  ]}]
}')

for attempt in 1 2 3 4 5 6; do
  echo "=== attempt $attempt ==="
  resp=$(curl -sS -w "\n__HTTP__%{http_code}" https://openrouter.ai/api/v1/chat/completions \
    -H "Authorization: Bearer $OPENROUTER_API_KEY" \
    -H "Content-Type: application/json" \
    -H "HTTP-Referer: http://localhost" -H "X-Title: Study-04 API Test" \
    -d "$payload")
  body="${resp%__HTTP__*}"; code="${resp##*__HTTP__}"
  echo "HTTP $code"
  if [ "$code" = "200" ]; then
    echo "$body" | jq '{model, content: .choices[0].message.content, finish_reason: .choices[0].finish_reason, usage: {prompt_tokens: .usage.prompt_tokens, completion_tokens: .usage.completion_tokens, cost: .usage.cost}}'
    exit 0
  fi
  echo "$body" | jq -r '.error.message // .error // .' 2>/dev/null | head -3
  sleep 25
done
echo "FAILED after 6 attempts"
exit 1
