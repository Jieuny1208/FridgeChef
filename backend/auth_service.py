"""Authentication service: signup, login, logout. Bcrypt password hashing.

Local-study scope — see PRD §6.1 security note.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import bcrypt

from backend._storage import DATA_DIR, load_json, save_json, with_lock
from backend.models import Profile, User
from backend.profile_service import PROFILES_FILE, ProfileService


USERS_FILE = DATA_DIR / "users.json"
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
PASSWORD_MIN = 8


class AuthError(Exception):
    pass


def _validate_username(username: str) -> str:
    u = username.strip().lower()
    if not USERNAME_RE.match(u):
        raise AuthError("아이디는 영문 소문자/숫자/언더스코어 3-20자여야 합니다.")
    return u


def _validate_password(password: str) -> None:
    if len(password) < PASSWORD_MIN:
        raise AuthError(f"비밀번호는 {PASSWORD_MIN}자 이상이어야 합니다.")
    if not re.search(r"[a-zA-Z]", password) or not re.search(r"\d", password):
        raise AuthError("비밀번호는 영문과 숫자를 모두 포함해야 합니다.")


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(password: str, hash_str: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hash_str.encode("utf-8"))
    except (ValueError, TypeError):
        return False


class AuthService:
    """File-backed auth (PRD: 학습용 local persistence, no DB)."""

    def __init__(self, users_path: Path = USERS_FILE):
        self.path = users_path

    def _load_all(self) -> list:
        data = load_json(self.path, default={"users": []})
        if isinstance(data, dict):
            return list(data.get("users", []))
        return []

    def _save_all(self, users: list, *, lock: bool = True) -> None:
        save_json(self.path, {"users": users}, lock=lock)

    def find_by_username(self, username: str) -> Optional[User]:
        u = username.strip().lower()
        for entry in self._load_all():
            if entry.get("username") == u:
                return User.model_validate(entry)
        return None

    def signup(
        self,
        username: str,
        password: str,
        display_name: str,
    ) -> Tuple[User, Profile]:
        """Create user + profile atomically under a single lock context.

        C-3: Previously the lock was released after writing users.json and
        re-acquired by ProfileService.create. If the profile write failed (or
        crashed mid-way), we'd be left with an orphan user. Now we hold the
        lock across both writes and roll the user back if the profile write
        raises.
        """
        u = _validate_username(username)
        _validate_password(password)
        name = display_name.strip()
        if not name:
            raise AuthError("표시 이름을 입력하세요.")

        with with_lock():
            users = self._load_all()
            if any(x.get("username") == u for x in users):
                raise AuthError("이미 사용 중인 아이디입니다.")

            user = User(
                id=str(uuid.uuid4()),
                username=u,
                password_hash=_hash_password(password),
                created_at=datetime.now(),
            )
            users_after = users + [user.model_dump(mode="json")]
            self._save_all(users_after, lock=False)

            try:
                # Inline profile creation while still holding the global lock.
                profiles_data = load_json(PROFILES_FILE, default={"profiles": []})
                profiles = (
                    list(profiles_data.get("profiles", []))
                    if isinstance(profiles_data, dict)
                    else []
                )
                profile = Profile(user_id=user.id, display_name=name)
                if not any(p.get("user_id") == user.id for p in profiles):
                    profiles.append(profile.model_dump(mode="json"))
                    save_json(PROFILES_FILE, {"profiles": profiles}, lock=False)
            except Exception:
                # Roll back the user write so users.json doesn't keep an orphan.
                self._save_all(users, lock=False)
                raise

        return user, profile

    def login(self, username: str, password: str) -> User:
        # Generic message: don't leak whether user exists (PRD §8)
        generic = AuthError("아이디 또는 비밀번호가 올바르지 않습니다.")
        u = username.strip().lower()
        if not u or not password:
            raise generic
        user = self.find_by_username(u)
        if user is None or not _verify_password(password, user.password_hash):
            raise generic
        return user
