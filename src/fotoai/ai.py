import base64
import time
from io import BytesIO
from pathlib import Path

from openai import OpenAI, RateLimitError
from PIL import Image
from pydantic import BaseModel

from fotoai.config import settings
from fotoai.metadata import ImageMetadata

# The OpenAI SDK already retries 429s internally, but with sub-second backoff
# based on the error's own retry hint. Token-per-minute caps recover on a
# rolling ~1 minute window, so on top of that we retry with longer backoff.
MAX_RATE_LIMIT_RETRIES = 5
RATE_LIMIT_BACKOFF_SECONDS = 5.0

# Adobe Stock's hard limit is 200 chars for titles and 49 for keywords;
# Shutterstock allows up to 50 keywords. We enforce the tighter bound so a
# single generated record is valid for both.
MAX_TITLE_CHARS = 200
MAX_KEYWORDS = 49


class AIResponse(BaseModel):
    # These analysis fields are generated before title/description/keywords
    # (structured-output field order drives generation order), so the model
    # enumerates concrete, buyer-searchable details instead of jumping
    # straight to a compressed, generic title.
    notable_subjects: list[str]
    notable_details: list[str]
    setting_and_context: str
    mood_and_style: list[str]

    title: str
    description: str
    keywords: list[str]


def _truncate_at_word_boundary(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(",.;:- ")


def _dedupe_keywords(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for keyword in keywords:
        keyword = keyword.strip()
        if not keyword or keyword.lower() in seen:
            continue
        seen.add(keyword.lower())
        result.append(keyword)
    return result[:MAX_KEYWORDS]


def encode_image(image_path: Path, max_dimension: int) -> str:
    """Downscales (if needed) and encodes an image to a base64 JPEG string."""
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        if max(img.size) > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def generate_metadata(image_path: Path, current_meta: ImageMetadata) -> AIResponse:
    """
    Sends the image and its current metadata to the configured AI model
    to generate a new optimized title, description, and keywords.
    """
    if not settings.ai.api_key:
        raise ValueError(
            "OpenAI API key is missing. Set it in config.toml or via the OPENAI_API_KEY env var."
        )

    client = OpenAI(
        api_key=settings.ai.api_key,
        base_url=settings.ai.base_url,
    )

    base64_image = encode_image(image_path, settings.ai.max_image_dimension)

    # Construct context from existing metadata
    context_lines = []
    if current_meta.title:
        context_lines.append(f"Current Title: {current_meta.title}")
    if current_meta.description:
        context_lines.append(f"Current Description: {current_meta.description}")
    if current_meta.keywords:
        context_lines.append(f"Current Keywords: {', '.join(current_meta.keywords)}")
    if current_meta.location_data:
        context_lines.append(f"Location Data: {current_meta.location_data}")

    prompt = "Please analyze this image and generate the requested metadata."
    if context_lines:
        prompt += "\n\nConsider the following existing metadata embedded in the photo:\n"
        prompt += "\n".join(context_lines)

    messages = [
        {
            "role": "system",
            "content": settings.prompts.system_prompt,
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                        "detail": "auto",
                    },
                },
            ],
        },
    ]

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            response = client.beta.chat.completions.parse(
                model=settings.ai.model,
                messages=messages,
                response_format=AIResponse,
            )
            parsed = response.choices[0].message.parsed
            parsed.title = _truncate_at_word_boundary(
                parsed.title.strip(), MAX_TITLE_CHARS
            )
            parsed.keywords = _dedupe_keywords(parsed.keywords)
            return parsed
        except RateLimitError:
            if attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            time.sleep(RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))
