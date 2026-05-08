"""Profile CRUD on top of profiles.json (PRD §6.2)."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from backend._storage import DATA_DIR, load_json, save_json, with_lock
from backend.models import DietLiteral, DifficultyLiteral, Profile


PROFILES_FILE = DATA_DIR / "profiles.json"


class ProfileService:
    def __init__(self, path: Path = PROFILES_FILE):
        self.path = path

    def _load_all(self) -> list:
        data = load_json(self.path, default={"profiles": []})
        return list(data.get("profiles", [])) if isinstance(data, dict) else []

    def _save_all(self, profiles: list, *, lock: bool = True) -> None:
        save_json(self.path, {"profiles": profiles}, lock=lock)

    def get(self, user_id: str) -> Optional[Profile]:
        for p in self._load_all():
            if p.get("user_id") == user_id:
                return Profile.model_validate(p)
        return None

    def create(self, user_id: str, display_name: str) -> Profile:
        profile = Profile(user_id=user_id, display_name=display_name)
        with with_lock():
            profiles = self._load_all()
            if any(p.get("user_id") == user_id for p in profiles):
                return Profile.model_validate(
                    next(p for p in profiles if p.get("user_id") == user_id)
                )
            profiles.append(profile.model_dump(mode="json"))
            self._save_all(profiles, lock=False)
        return profile

    def update(
        self,
        user_id: str,
        *,
        display_name: Optional[str] = None,
        diet: Optional[List[DietLiteral]] = None,
        allergens: Optional[List[str]] = None,
        default_servings: Optional[int] = None,
        default_max_minutes: Optional[int] = None,
        default_difficulty: Optional[DifficultyLiteral] = None,
    ) -> Profile:
        with with_lock():
            profiles = self._load_all()
            for i, p in enumerate(profiles):
                if p.get("user_id") != user_id:
                    continue
                if display_name is not None:
                    p["display_name"] = display_name
                if diet is not None:
                    p["diet"] = list(diet)
                if allergens is not None:
                    p["allergens"] = list(allergens)
                if default_servings is not None:
                    p["default_servings"] = int(default_servings)
                if default_max_minutes is not None:
                    p["default_max_minutes"] = int(default_max_minutes)
                if default_difficulty is not None:
                    p["default_difficulty"] = default_difficulty
                profiles[i] = p
                self._save_all(profiles, lock=False)
                return Profile.model_validate(p)
            raise KeyError(f"profile not found for user_id={user_id}")
