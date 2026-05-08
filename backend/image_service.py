"""
Image processing service for handling uploaded images
"""
import base64
import io
import os
import re
import uuid
from PIL import Image, ImageOps, UnidentifiedImageError
from typing import Optional, Tuple
from backend.config import Config


# H-9: PIL format identifiers we are willing to accept for the magic-byte
# verification pass. Maps to a safe extension we use when sanitizing names.
_ALLOWED_PIL_FORMATS = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}


def _sanitize_filename(name: Optional[str]) -> str:
    """Return a UUID-prefixed filename safe for joining onto TEMP_FOLDER.

    Strips any directory components and rejects characters outside a small
    safe whitelist. If the input is empty or unusable we fall back to a pure
    UUID name so callers always receive a valid, non-traversing path.
    """
    base = (name or "").strip().replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not base or base in {".", ".."}:
        base = "image"
    # Always prepend a UUID so collisions and pre-existing names can't be
    # used to overwrite or read someone else's file.
    return f"{uuid.uuid4().hex}_{base}"

class ImageProcessor:
    """Service for processing uploaded images"""

    @staticmethod
    def validate_image(file) -> Tuple[bool, str]:
        """
        Validate uploaded image file

        Args:
            file: Streamlit UploadedFile object

        Returns:
            Tuple of (is_valid, error_message)
        """
        if file is None:
            return False, "파일이 선택되지 않았습니다"

        # Check file extension
        filename = file.name.lower()
        extension = filename.split('.')[-1] if '.' in filename else ''

        if extension not in Config.ALLOWED_EXTENSIONS:
            return False, f"지원하지 않는 파일 형식입니다. ({', '.join(Config.ALLOWED_EXTENSIONS)}만 지원)"

        # Check file size
        file.seek(0, 2)  # Move to end of file
        file_size = file.tell()
        file.seek(0)  # Reset to beginning

        if file_size > Config.MAX_IMAGE_SIZE:
            return False, f"파일 크기가 너무 큽니다. (최대 {Config.MAX_IMAGE_SIZE // (1024*1024)}MB)"

        # H-9: trust-but-verify — extensions can lie, so confirm the file
        # actually parses as one of our allowed image formats by inspecting
        # the magic bytes via PIL.
        try:
            file.seek(0)
            with Image.open(file) as probe:
                probe.verify()
                fmt = (probe.format or "").upper()
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
            file.seek(0)
            return False, "이미지 파일이 손상되었거나 지원하지 않는 형식입니다."
        finally:
            try:
                file.seek(0)
            except Exception:
                pass

        if fmt not in _ALLOWED_PIL_FORMATS:
            return False, f"지원하지 않는 이미지 형식입니다 (감지: {fmt or '알 수 없음'})."

        return True, ""

    @staticmethod
    def process_image(file) -> Optional[str]:
        """
        Process uploaded image and convert to base64

        Args:
            file: Streamlit UploadedFile object

        Returns:
            Base64 encoded string or None if processing failed
        """
        try:
            # Read image
            image = Image.open(file)

            # Apply EXIF rotation so phone photos are right-side-up (PRD §5.1)
            image = ImageOps.exif_transpose(image)

            # H-8: Flatten any mode that may carry alpha onto a white background.
            # The previous version used ``mask=None`` for ``LA``/``P`` which
            # silently dropped translucency, and ``P`` images with palette
            # transparency were never alpha-composited at all. Normalising to
            # RGBA first makes the alpha channel always-present and uniform.
            if image.mode != "RGB":
                if image.mode in ("RGBA", "LA") or (
                    image.mode == "P" and "transparency" in image.info
                ):
                    rgba = image.convert("RGBA")
                    bg = Image.new("RGB", rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.split()[-1])
                    image = bg
                else:
                    image = image.convert("RGB")

            # Resize if too large
            max_dim = Config.IMAGE_MAX_DIMENSION
            if image.width > max_dim or image.height > max_dim:
                image.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            # Convert to base64
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=85)
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

            return img_base64

        except Exception as e:
            print(f"Error processing image: {e}")
            return None

    @staticmethod
    def save_temp_image(file, filename: str = None) -> Optional[str]:
        """
        Save uploaded image to temp folder

        Args:
            file: Streamlit UploadedFile object
            filename: Optional custom filename (will be sanitized)

        Returns:
            Path to saved file or None if failed
        """
        try:
            # H-9: never trust the supplied filename — sanitize it and force
            # a UUID prefix so that path traversal (``../../etc/passwd``) and
            # accidental overwrites of pre-existing temp files are impossible.
            raw_name = filename if filename is not None else getattr(file, "name", None)
            safe_name = _sanitize_filename(raw_name)

            os.makedirs(Config.TEMP_FOLDER, exist_ok=True)
            filepath = os.path.join(Config.TEMP_FOLDER, safe_name)

            # Defensive: ensure the resolved path stays inside TEMP_FOLDER.
            real_temp = os.path.realpath(Config.TEMP_FOLDER)
            real_target = os.path.realpath(filepath)
            if not real_target.startswith(real_temp + os.sep) and real_target != real_temp:
                print(f"Refusing to write outside TEMP_FOLDER: {real_target}")
                return None

            with open(filepath, "wb") as f:
                f.write(file.getbuffer())

            return filepath

        except Exception as e:
            print(f"Error saving image: {e}")
            return None

    @staticmethod
    def encode_image(image) -> Optional[str]:
        """
        Encode PIL Image to base64 string

        Args:
            image: PIL Image object

        Returns:
            Base64 encoded string or None if failed
        """
        try:
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=85)
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            return img_base64
        except Exception as e:
            print(f"Error encoding image: {e}")
            return None

    @staticmethod
    def cleanup_temp_folder():
        """Clean up temporary image files older than 1 hour"""
        import time

        try:
            current_time = time.time()
            temp_folder = Config.TEMP_FOLDER

            for filename in os.listdir(temp_folder):
                filepath = os.path.join(temp_folder, filename)

                # Check file age
                file_age = current_time - os.path.getmtime(filepath)

                # Delete files older than 1 hour
                if file_age > 3600:
                    os.remove(filepath)
                    print(f"Cleaned up old temp file: {filename}")

        except Exception as e:
            print(f"Error cleaning temp folder: {e}")

    @staticmethod
    def create_test_image() -> str:
        """
        Create a simple test image for testing purposes

        Returns:
            Base64 encoded test image
        """
        # Create a simple test image with some "ingredients"
        image = Image.new('RGB', (400, 300), color='white')

        # Save as base64
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        return img_base64