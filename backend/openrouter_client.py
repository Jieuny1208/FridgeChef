"""
OpenRouter API client for AI model interactions.
PRD Step 1: 이미지 인식 (google/gemma-4-26b-a4b-it:free)
"""
import json
import re
import time
from typing import Dict, List, Optional

import requests

from backend.config import Config


SYSTEM_PROMPT_INGREDIENTS = (
    "너는 한국어로 응답하는 식재료 인식 어시스턴트다. "
    "입력 이미지에서 식별 가능한 식재료만 JSON으로 반환한다. "
    'JSON 포맷: {"ingredients":[{"name":"이름","category":"채소|과일|육류|해산물|유제품|계란|곡류|소스/양념|음료|기타","confidence":0.0~1.0}]}. '
    "JSON 외 설명, 코드펜스, 마크다운을 절대 출력하지 마라."
)
USER_PROMPT_INGREDIENTS = "이 냉장고 사진에서 식재료 목록을 뽑아줘. JSON만 반환해."


class OpenRouterClient:
    """Client for OpenRouter API (chat completions, vision)."""

    def __init__(self):
        self.api_key = Config.get_api_key()
        self.base_url = Config.OPENROUTER_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": Config.APP_NAME,
        }

    def chat_completion(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        response_format: Optional[Dict] = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> Dict:
        """Send chat completion request with exponential backoff for 429/5xx.

        Returns dict: {ok: bool, status: int, data|error}.
        """
        if model is None:
            model = Config.IMAGE_RECOGNITION_MODEL

        endpoint = f"{self.base_url}/chat/completions"
        payload: Dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        last_err: Dict = {"status": 0, "error": "unknown"}
        # H-1: cap retries at MAX_RETRIES so the backoff schedule and the
        # advertised retry count stay in sync.
        backoff = list(Config.RETRY_BACKOFF_SECONDS)[: Config.MAX_RETRIES]
        for attempt, wait in enumerate([0] + backoff):
            if wait:
                time.sleep(wait)
            try:
                resp = requests.post(
                    endpoint,
                    headers=self.headers,
                    json=payload,
                    timeout=Config.REQUEST_TIMEOUT,
                )
            except requests.exceptions.RequestException as e:
                last_err = {"status": 0, "error": f"network: {e}"}
                continue

            if resp.status_code == 200:
                return {"ok": True, "status": 200, "data": resp.json()}

            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text[:500]}

            last_err = {"status": resp.status_code, "error": body}

            if resp.status_code in (429, 502, 503, 504):
                continue
            if 400 <= resp.status_code < 500:
                break

        return {"ok": False, **last_err}

    def recognize_ingredients(self, image_base64: str) -> Dict:
        """Call vision model and return parsed ingredient list.

        Output schema:
          {"status": "success"|"error",
           "ingredients_by_category": {category: [name, ...]},
           "ingredients": [{"name","category","confidence"}],
           "raw_text": "...",
           "total_items": int,
           "error": "..." (only on error)}
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_INGREDIENTS},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT_INGREDIENTS},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        },
                    },
                ],
            },
        ]
        result = self.chat_completion(
            messages,
            model=Config.IMAGE_RECOGNITION_MODEL,
            response_format={"type": "json_object"},
        )
        if not result["ok"]:
            return self._error_payload(result)

        try:
            content = result["data"]["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            return {"status": "error", "error": f"unexpected response shape: {e}"}

        # H-2: some providers return ``content: null`` when they refuse to
        # answer or hit a content filter — treat as an empty/retryable parse.
        if content is None:
            content = ""

        parsed = self._parse_ingredient_json(content)
        if parsed["status"] == "error" and parsed.get("retryable"):
            # PRD §5.3: 1회 재호출 with stronger directive
            messages[0]["content"] += " 응답은 반드시 JSON 객체 하나여야 한다."
            result = self.chat_completion(
                messages,
                model=Config.IMAGE_RECOGNITION_MODEL,
                response_format={"type": "json_object"},
            )
            if result["ok"]:
                try:
                    content = result["data"]["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError):
                    content = ""
                if content is None:
                    content = ""
                parsed = self._parse_ingredient_json(content)

        return parsed

    @staticmethod
    def _error_payload(result: Dict) -> Dict:
        msg = result.get("error", "unknown error")
        if isinstance(msg, dict):
            inner = msg.get("error", {})
            if isinstance(inner, dict):
                meta = inner.get("metadata") or {}
                raw = meta.get("raw") if isinstance(meta, dict) else None
                msg = raw or inner.get("message") or json.dumps(msg, ensure_ascii=False)[:300]
        return {
            "status": "error",
            "error": f"HTTP {result.get('status')}: {msg}",
            "ingredients": [],
            "ingredients_by_category": {},
            "total_items": 0,
            "raw_text": "",
        }

    @staticmethod
    def _parse_ingredient_json(text: Optional[str]) -> Dict:
        """Parse model output into structured ingredients."""
        # H-2: defensive guard — caller may receive ``None`` from refusals.
        if not text:
            return {
                "status": "error",
                "error": "empty model response",
                "raw_text": "",
                "retryable": True,
                "ingredients": [],
                "ingredients_by_category": {},
                "total_items": 0,
            }
        snippet = text.strip()
        # Strip code fences if present
        snippet = re.sub(r"^```(?:json)?\s*|\s*```$", "", snippet, flags=re.IGNORECASE)
        # Sometimes model wraps JSON in extra prose; extract first JSON object
        match = re.search(r"\{.*\}", snippet, flags=re.DOTALL)
        json_str = match.group(0) if match else snippet
        try:
            obj = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "error": f"JSON parse failed: {e.msg}",
                "raw_text": text,
                "retryable": True,
                "ingredients": [],
                "ingredients_by_category": {},
                "total_items": 0,
            }

        items = obj.get("ingredients", []) if isinstance(obj, dict) else []
        normalized: List[Dict] = []
        by_cat: Dict[str, List[str]] = {}
        seen = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name", "")).strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            category = str(it.get("category", "기타")).strip() or "기타"
            try:
                conf = float(it.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            conf = max(0.0, min(1.0, conf))
            normalized.append({"name": name, "category": category, "confidence": conf})
            by_cat.setdefault(category, []).append(name)

        return {
            "status": "success",
            "ingredients": normalized,
            "ingredients_by_category": by_cat,
            "total_items": len(normalized),
            "raw_text": text,
        }

    def test_connection(self) -> bool:
        """Test API connection (cheap GET /models).

        M-6: Timeout reduced from 10s to 4s — this is a UI ping behind a button
        and a slow remote shouldn't block Streamlit re-renders for that long.
        """
        try:
            resp = requests.get(
                f"{self.base_url}/models", headers=self.headers, timeout=4
            )
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False
