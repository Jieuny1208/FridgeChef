"""Pydantic models for Step 3 — users, profiles, saved recipes."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


DietLiteral = Literal["채식", "비건", "할랄", "저염", "저당"]
DifficultyLiteral = Literal["쉬움", "보통", "어려움"]


class User(BaseModel):
    """Authenticated user — password is stored as a bcrypt hash only."""
    model_config = ConfigDict(extra="ignore")

    id: str
    username: str
    password_hash: str
    created_at: datetime


class Profile(BaseModel):
    """Per-user preferences that prefill Step 2 options."""
    model_config = ConfigDict(extra="ignore")

    user_id: str
    display_name: str
    diet: List[DietLiteral] = Field(default_factory=list)
    allergens: List[str] = Field(default_factory=list)
    default_servings: int = 2
    default_max_minutes: int = 30
    default_difficulty: DifficultyLiteral = "쉬움"


class SavedRecipe(BaseModel):
    """A recipe saved by a user — wraps the Step 2 recipe payload."""
    model_config = ConfigDict(extra="ignore")

    id: str                   # PRD §9: hash(title + ingredients_used)
    user_id: str
    recipe: dict              # Step 2 Recipe (already validated upstream)
    note: str = ""
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    saved_at: datetime
    tags: List[str] = Field(default_factory=list)
