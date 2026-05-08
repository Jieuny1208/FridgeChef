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
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default


class Config:
    """Application configuration"""

    # OpenRouter API
    OPENROUTER_API_KEY = _read_secret('OPENROUTER_API_KEY')
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
    def validate(cls):
        """Validate required configuration"""
        if not cls.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is not set in environment variables")

        # Create folders if they don't exist
        os.makedirs(cls.TEMP_FOLDER, exist_ok=True)
        os.makedirs(cls.TEST_IMAGES_FOLDER, exist_ok=True)

        return True