"""SavedRecipe persistence — search, sort, CRUD with file lock (PRD §6.4-6.5)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from backend._storage import DATA_DIR, load_json, save_json, with_lock
from backend.models import SavedRecipe


SAVED_FILE = DATA_DIR / "saved_recipes.json"


# C-2: sentinel that distinguishes "field omitted" from "set to None".
# Callers pass UNSET (or simply omit the kwarg) to leave a field unchanged,
# and pass None to explicitly clear it (only meaningful for ``rating``).
class _Unset:
    _instance: Optional["_Unset"] = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "UNSET"

    def __bool__(self) -> bool:  # pragma: no cover - cosmetic
        return False


UNSET: Any = _Unset()


class RecipeStore:
    def __init__(self, path: Path = SAVED_FILE):
        self.path = path

    def _load_all(self) -> list:
        data = load_json(self.path, default={"saved_recipes": []})
        return list(data.get("saved_recipes", [])) if isinstance(data, dict) else []

    def _save_all(self, items: list, *, lock: bool = True) -> None:
        save_json(self.path, {"saved_recipes": items}, lock=lock)

    # ---------- queries ----------
    def list_for_user(
        self,
        user_id: str,
        *,
        query: str = "",
        sort: str = "recent",  # recent | rating | title
    ) -> List[SavedRecipe]:
        items = [
            SavedRecipe.model_validate(x)
            for x in self._load_all()
            if x.get("user_id") == user_id
        ]
        if query:
            q = query.strip().lower()
            def matches(r: SavedRecipe) -> bool:
                hay = (r.recipe.get("title", "") + " "
                       + " ".join(i.get("name", "") for i in r.recipe.get("ingredients_used", []))
                       + " " + " ".join(r.tags))
                return q in hay.lower()
            items = [r for r in items if matches(r)]

        if sort == "rating":
            items.sort(key=lambda r: ((r.rating or 0), r.saved_at), reverse=True)
        elif sort == "title":
            items.sort(key=lambda r: r.recipe.get("title", ""))
        else:  # recent
            items.sort(key=lambda r: r.saved_at, reverse=True)
        return items

    def get(self, user_id: str, recipe_id: str) -> Optional[SavedRecipe]:
        for x in self._load_all():
            if x.get("user_id") == user_id and x.get("id") == recipe_id:
                return SavedRecipe.model_validate(x)
        return None

    # ---------- mutations ----------
    def save(
        self,
        user_id: str,
        recipe: dict,
        *,
        note: str = "",
        rating: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> SavedRecipe:
        rid = recipe.get("id")
        if not rid:
            raise ValueError("recipe must have an id (Step 2 should provide it)")
        with with_lock():
            items = self._load_all()
            # Dedup by (user_id, recipe.id) — return existing if already saved
            for x in items:
                if x.get("user_id") == user_id and x.get("id") == rid:
                    return SavedRecipe.model_validate(x)
            sr = SavedRecipe(
                id=rid, user_id=user_id, recipe=recipe,
                note=note, rating=rating,
                saved_at=datetime.now(), tags=list(tags or []),
            )
            items.append(sr.model_dump(mode="json"))
            self._save_all(items, lock=False)
        return sr

    def update(
        self,
        user_id: str,
        recipe_id: str,
        *,
        note: Any = UNSET,
        rating: Any = UNSET,
        tags: Any = UNSET,
    ) -> SavedRecipe:
        """Patch a saved recipe.

        C-2: ``UNSET`` (the default) means "do not touch this field"; ``None``
        for ``rating`` means "clear the rating". For ``note``/``tags``, ``None``
        is treated the same as ``UNSET`` since their cleared form is "" / [].
        """
        with with_lock():
            items = self._load_all()
            for i, x in enumerate(items):
                if x.get("user_id") != user_id or x.get("id") != recipe_id:
                    continue
                if note is not UNSET and note is not None:
                    x["note"] = str(note)
                if rating is not UNSET:
                    if rating is None:
                        x["rating"] = None
                    else:
                        rv = int(rating)
                        if rv < 1 or rv > 5:
                            raise ValueError("rating must be between 1 and 5 (or None to clear)")
                        x["rating"] = rv
                if tags is not UNSET and tags is not None:
                    x["tags"] = list(tags)
                items[i] = x
                self._save_all(items, lock=False)
                return SavedRecipe.model_validate(x)
            raise KeyError(f"saved recipe not found: {recipe_id}")

    def delete(self, user_id: str, recipe_id: str) -> bool:
        with with_lock():
            items = self._load_all()
            new_items = [
                x for x in items
                if not (x.get("user_id") == user_id and x.get("id") == recipe_id)
            ]
            if len(new_items) == len(items):
                return False
            self._save_all(new_items, lock=False)
            return True

    def is_saved(self, user_id: str, recipe_id: str) -> bool:
        return self.get(user_id, recipe_id) is not None
