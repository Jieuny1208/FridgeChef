"""Recipe generation service.

PRD Step 2: AI 기반 레시피 추천 (google/gemma-4-31b-it:free)
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from jsonschema import Draft7Validator

from backend.config import Config
from backend.openrouter_client import OpenRouterClient
from backend.recipe_schema import DIFFICULTY_VALUES, RECIPE_SCHEMA


PROMPT_PATH = Path(__file__).parent / "prompts" / "recipe_system.txt"


# M-5: cache the system prompt — it's read on every recipe generation call but
# never changes at runtime. ``maxsize=1`` because there is only one prompt file.
@functools.lru_cache(maxsize=1)
def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


# H-3: Korean/English allergen alias dictionary. Substring matching alone gives
# false positives like "egg" → "eggplant" or "milk" → "milkshake". We expand
# each user-supplied allergen with its localized synonyms and then tokenize
# both sides so that matches respect word boundaries.
_ALLERGEN_ALIASES: Dict[str, List[str]] = {
    "계란": ["계란", "달걀", "egg", "eggs"],
    "달걀": ["계란", "달걀", "egg", "eggs"],
    "egg": ["계란", "달걀", "egg", "eggs"],
    "eggs": ["계란", "달걀", "egg", "eggs"],
    "우유": ["우유", "milk"],
    "milk": ["우유", "milk"],
    "유제품": ["우유", "치즈", "버터", "요거트", "유제품", "milk", "cheese", "butter", "yogurt", "dairy"],
    "dairy": ["우유", "치즈", "버터", "요거트", "유제품", "milk", "cheese", "butter", "yogurt", "dairy"],
    "땅콩": ["땅콩", "peanut", "peanuts"],
    "peanut": ["땅콩", "peanut", "peanuts"],
    "peanuts": ["땅콩", "peanut", "peanuts"],
    "견과류": ["견과", "견과류", "아몬드", "호두", "캐슈", "nut", "nuts", "almond", "walnut", "cashew"],
    "nuts": ["견과", "견과류", "아몬드", "호두", "캐슈", "nut", "nuts", "almond", "walnut", "cashew"],
    "밀": ["밀", "밀가루", "글루텐", "wheat", "gluten"],
    "wheat": ["밀", "밀가루", "글루텐", "wheat", "gluten"],
    "gluten": ["밀", "밀가루", "글루텐", "wheat", "gluten"],
    "콩": ["콩", "대두", "두부", "soy", "soybean", "tofu"],
    "soy": ["콩", "대두", "두부", "soy", "soybean", "tofu"],
    "새우": ["새우", "shrimp", "prawn"],
    "shrimp": ["새우", "shrimp", "prawn"],
    "갑각류": ["새우", "게", "랍스터", "갑각류", "shrimp", "crab", "lobster", "shellfish"],
    "shellfish": ["새우", "게", "랍스터", "갑각류", "shrimp", "crab", "lobster", "shellfish"],
}

# Token splitter: keep CJK runs and ASCII alphanumerics, drop punctuation/whitespace.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")


def _expand_allergen_terms(allergen: str) -> List[str]:
    a = allergen.strip().lower()
    if not a:
        return []
    expanded = list(_ALLERGEN_ALIASES.get(a, [a]))
    return [t.lower() for t in expanded]


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _matches_allergen_token(tokens: List[str], term: str) -> bool:
    """True iff ``term`` appears as a whole token (or, for CJK, as a substring
    of a CJK token — e.g. "계란" inside "계란말이")."""
    t = term.lower()
    if not t:
        return False
    is_cjk = any("가" <= ch <= "힣" for ch in t)
    if is_cjk:
        return any(t in tok for tok in tokens)
    # ASCII: require exact whole-token match to avoid egg→eggplant false hits.
    return t in tokens


def build_user_prompt(
    ingredients: List[Dict],
    *,
    servings: int,
    max_minutes: int,
    difficulty: str,
    diet: List[str],
    allergens: List[str],
    num_recipes: int,
    avoid_titles: Optional[List[str]] = None,
) -> str:
    names = ", ".join(it["name"] for it in ingredients) or "(재료 없음)"
    diet_s = ", ".join(diet) if diet else "없음"
    allergen_s = ", ".join(allergens) if allergens else "없음"
    avoid_s = ", ".join(avoid_titles or []) or "없음"

    return (
        f"재료: {names}\n"
        f"인분: {servings}, 최대 조리 시간: {max_minutes}분, 난이도: {difficulty}\n"
        f"식단 제한: {diet_s}\n"
        f"알레르기: {allergen_s}\n"
        f"추천 수(N): {num_recipes}\n"
        f"이미 추천된 제목(중복 금지): {avoid_s}\n"
        "응답은 위 시스템 메시지의 스키마를 따르는 JSON 객체 하나만 반환해라."
    )


def cache_key(
    ingredients: List[Dict],
    *,
    servings: int,
    max_minutes: int,
    difficulty: str,
    diet: List[str],
    allergens: List[str],
    num_recipes: int,
    avoid_titles: Optional[List[str]] = None,
) -> str:
    blob = json.dumps(
        {
            "ing": sorted([it["name"] for it in ingredients]),
            "s": servings,
            "m": max_minutes,
            "d": difficulty,
            "diet": sorted(diet),
            "a": sorted(allergens),
            "n": num_recipes,
            "avoid": sorted(avoid_titles or []),
            "model": Config.RECIPE_GENERATION_MODEL,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def recipe_id(recipe: Dict) -> str:
    """Stable id derived from title + ingredients + servings/minutes/difficulty.

    C-4: previously only ``title`` and ``ingredients_used`` names were hashed,
    so two recipes that differ only by serving size, prep time, or difficulty
    collapsed to the same id (and thus the dedup logic in app.py would silently
    drop one of them). Including the structural fields restores uniqueness.
    """
    names = sorted(
        (str(i.get("name", "")) for i in recipe.get("ingredients_used", [])),
        key=str,
    )
    parts = [
        str(recipe.get("title", "")),
        ",".join(names),
        f"s={recipe.get('servings', '')}",
        f"m={recipe.get('estimated_minutes', '')}",
        f"d={recipe.get('difficulty', '')}",
    ]
    blob = "|".join(parts).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:12]


def _strip_to_json(text: str) -> str:
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.IGNORECASE)
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    return m.group(0) if m else s


class RecipeGenerator:
    """Generate recipes via OpenRouter (gemma-4-31b-it:free) with schema validation."""

    def __init__(self, client: Optional[OpenRouterClient] = None):
        self.client = client or OpenRouterClient()
        self.model = Config.RECIPE_GENERATION_MODEL
        self.validator = Draft7Validator(RECIPE_SCHEMA)

    def generate(
        self,
        ingredients: List[Dict],
        *,
        servings: int = 2,
        max_minutes: int = 30,
        difficulty: str = "쉬움",
        diet: Optional[List[str]] = None,
        allergens: Optional[List[str]] = None,
        num_recipes: int = 3,
        avoid_titles: Optional[List[str]] = None,
    ) -> Dict:
        """Generate N recipes. Returns:
        {status: "success"|"error",
         recipes: [...] (each enriched with id + created_at on success),
         raw_text, model, error?}
        """
        if difficulty not in DIFFICULTY_VALUES:
            difficulty = "쉬움"
        diet = diet or []
        allergens = allergens or []

        if not ingredients:
            return {
                "status": "error",
                "error": "재료가 비어 있습니다. Step 1을 먼저 진행하세요.",
                "recipes": [],
                "raw_text": "",
                "model": self.model,
            }

        system = load_system_prompt()
        user = build_user_prompt(
            ingredients,
            servings=servings,
            max_minutes=max_minutes,
            difficulty=difficulty,
            diet=diet,
            allergens=allergens,
            num_recipes=num_recipes,
            avoid_titles=avoid_titles,
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        result = self.client.chat_completion(
            messages,
            model=self.model,
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=2500,
        )
        if not result.get("ok"):
            return self._error_payload(result)

        raw = self._extract_text(result)
        parsed_ok, recipes, validation_err = self._parse_and_validate(raw)

        if not parsed_ok:
            messages[0]["content"] = (
                system
                + "\n\n중요: 이전 응답이 JSON 스키마를 위반했다. "
                "반드시 위 스키마를 정확히 따른 JSON 객체 하나만 반환하라."
            )
            result = self.client.chat_completion(
                messages,
                model=self.model,
                response_format={"type": "json_object"},
                temperature=0.5,
                max_tokens=2500,
            )
            if result.get("ok"):
                raw = self._extract_text(result)
                parsed_ok, recipes, validation_err = self._parse_and_validate(raw)

        if not parsed_ok:
            return {
                "status": "error",
                "error": f"JSON 스키마 검증 실패: {validation_err}",
                "raw_text": raw,
                "recipes": [],
                "model": self.model,
            }

        recipes = self._post_filter(recipes, allergens=allergens, diet=diet)

        now = datetime.now().isoformat(timespec="seconds")
        for r in recipes:
            r["id"] = recipe_id(r)
            r["created_at"] = now

        return {
            "status": "success",
            "recipes": recipes,
            "raw_text": raw,
            "model": self.model,
        }

    @staticmethod
    def _extract_text(result: Dict) -> str:
        try:
            return result["data"]["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""

    def _parse_and_validate(self, raw: str) -> Tuple[bool, List[Dict], str]:
        if not raw:
            return False, [], "empty response"
        try:
            obj = json.loads(_strip_to_json(raw))
        except json.JSONDecodeError as e:
            return False, [], f"JSON parse: {e.msg}"
        errors = sorted(self.validator.iter_errors(obj), key=lambda e: list(e.path))
        if errors:
            first = errors[0]
            path = ".".join(str(p) for p in first.absolute_path) or "<root>"
            return False, [], f"{path}: {first.message}"
        return True, list(obj.get("recipes", [])), ""

    @staticmethod
    def _post_filter(
        recipes: List[Dict], *, allergens: List[str], diet: List[str]
    ) -> List[Dict]:
        """Drop recipes whose text mentions any forbidden allergen.

        H-3: Substring matching previously triggered false positives such as
        "egg" matching "eggplant" or "milk" matching "milkshake". We now
        expand each allergen via :data:`_ALLERGEN_ALIASES` and check token
        boundaries (whole-token for ASCII, substring for CJK because Korean
        compounds glue the term and modifier without whitespace).
        """
        if not (allergens or diet):
            return recipes

        bad_terms: List[str] = []
        for a in allergens or []:
            bad_terms.extend(_expand_allergen_terms(a))
        # de-dup while preserving order
        seen = set()
        bad_terms = [t for t in bad_terms if not (t in seen or seen.add(t))]
        if not bad_terms:
            return recipes

        out: List[Dict] = []
        for r in recipes:
            blob = " ".join(
                [r.get("title", ""), r.get("summary", ""), " ".join(r.get("steps", []))]
                + [i.get("name", "") for i in r.get("ingredients_used", [])]
                + [i.get("name", "") for i in r.get("extra_ingredients", [])]
            )
            tokens = _tokenize(blob)
            if any(_matches_allergen_token(tokens, term) for term in bad_terms):
                continue
            out.append(r)
        return out

    @staticmethod
    def _error_payload(result: Dict) -> Dict:
        msg = result.get("error", "unknown")
        if isinstance(msg, dict):
            inner = msg.get("error", {})
            if isinstance(inner, dict):
                meta = inner.get("metadata") or {}
                raw = meta.get("raw") if isinstance(meta, dict) else None
                msg = raw or inner.get("message") or json.dumps(msg, ensure_ascii=False)[:300]
        return {
            "status": "error",
            "error": f"HTTP {result.get('status')}: {msg}",
            "recipes": [],
            "raw_text": "",
            "model": Config.RECIPE_GENERATION_MODEL,
        }
