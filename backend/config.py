"""
Configuration management for FridgeChef application
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def _read_secret(name: str, default=None):
    """Read a secret from env first, then Streamlit Cloud st.secrets.

    Streamlit Community Cloud injects secrets into st.secrets, not os.environ.
    """
    val = os.getenv(name)
    if val:
        return val
    try:
        import streamlit as st
        try:
            if name in st.secrets:
                return st.secrets[name]
        except Exception:
            pass
        # Streamlit Cloud sometimes nests secrets under a section
        for section_key in ("default", "secrets", "general"):
            try:
                section = st.secrets.get(section_key) if hasattr(st.secrets, "get") else None
                if section and name in section:
                    return section[name]
            except Exception:
                continue
    except Exception:
        pass
    return default


def _diagnose_missing(name: str) -> str:
    """Build a detailed diagnostic message for a missing secret."""
    parts = [f"'{name}' 값을 어디에서도 찾지 못했어요."]
    parts.append(f"- os.environ 에 '{name}': {'있음' if os.getenv(name) else '없음'}")
    try:
        import streamlit as st
        try:
            keys = list(st.secrets.keys()) if hasattr(st.secrets, "keys") else []
            parts.append(f"- st.secrets 키 목록: {keys if keys else '비어 있음'}")
        except Exception as e:
            parts.append(f"- st.secrets 접근 실패: {type(e).__name__}: {e}")
    except Exception as e:
        parts.append(f"- streamlit import 실패: {type(e).__name__}: {e}")
    return "\n".join(parts)


class Config:
    """Application configuration"""

    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    # Model configurations (PRD Step 1: Gemma 4)
    IMAGE_RECOGNITION_MODEL = "google/gemma-4-26b-a4b-it:free"
    RECIPE_GENERATION_MODEL = "google/gemma-4-31b-it:free"

    # Image settings
    MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
    IMAGE_MAX_DIMENSION = 1024

    # Application settings
    APP_NAME = "FridgeChef"
    APP_VERSION = "1.0.0"
    DEBUG = str(_read_secret('DEBUG', 'False')).lower() == 'true'

    # Paths
    TEMP_FOLDER = "data/temp"
    TEST_IMAGES_FOLDER = "tests/test_images"

    # API settings
    REQUEST_TIMEOUT = 60  # seconds (increased for image payloads)
    # H-1: keep MAX_RETRIES and the backoff schedule mutually consistent —
    # ``RETRY_BACKOFF_SECONDS`` provides exactly MAX_RETRIES wait intervals.
    RETRY_BACKOFF_SECONDS = [2, 5, 10, 25, 60]  # exponential per PRD §5.4
    MAX_RETRIES = len(RETRY_BACKOFF_SECONDS)

    @classmethod
    def get_api_key(cls):
        """Read API key fresh from env / st.secrets each time."""
        return _read_secret('OPENROUTER_API_KEY')

    # Backwards-compat: keep attribute access working but always read fresh.
    def __class_getitem__(cls, item):  # not used, just placeholder
        return None

    @classmethod
    def validate(cls):
        """Validate required configuration"""
        if not cls.get_api_key():
            raise ValueError(
                "OPENROUTER_API_KEY is not set in environment variables\n\n"
                + _diagnose_missing('OPENROUTER_API_KEY')
            )

        # Create folders if they don't exist
        os.makedirs(cls.TEMP_FOLDER, exist_ok=True)
        os.makedirs(cls.TEST_IMAGES_FOLDER, exist_ok=True)

        return True