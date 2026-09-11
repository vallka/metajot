import base64
import time
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Optional

from openai import OpenAI, RateLimitError
from PIL import Image
from pydantic import BaseModel

from fotoai.config import settings
from fotoai.metadata import ImageMetadata


class AdobeStockCategory(str, Enum):
    ANIMALS = "Animals"
    BUILDINGS_AND_ARCHITECTURE = "Buildings and Architecture"
    BUSINESS = "Business"
    DRINKS = "Drinks"
    THE_ENVIRONMENT = "The Environment"
    STATES_OF_MIND = "States of Mind"
    FOOD = "Food"
    GRAPHIC_RESOURCES = "Graphic Resources"
    HOBBIES_AND_LEISURE = "Hobbies and Leisure"
    INDUSTRY = "Industry"
    LANDSCAPES = "Landscapes"
    LIFESTYLE = "Lifestyle"
    PEOPLE = "People"
    PLANTS_AND_FLOWERS = "Plants and Flowers"
    CULTURE_AND_RELIGION = "Culture and Religion"
    SCIENCE = "Science"
    SOCIAL_ISSUES = "Social Issues"
    SPORTS = "Sports"
    TECHNOLOGY = "Technology"
    TRANSPORT = "Transport"
    TRAVEL = "Travel"


# Adobe Stock's CSV Category column takes the numeric ID shown in their
# upload-CSV dialog, not the category name.
ADOBE_CATEGORY_IDS: dict[str, int] = {
    category.value: i for i, category in enumerate(AdobeStockCategory, start=1)
}


class ShutterstockCategory(str, Enum):
    ABSTRACT = "Abstract"
    ANIMALS_WILDLIFE = "Animals/Wildlife"
    ARTS = "The Arts"
    BACKGROUNDS_TEXTURES = "Backgrounds/Textures"
    BEAUTY_FASHION = "Beauty/Fashion"
    BUILDINGS_LANDMARKS = "Buildings/Landmarks"
    BUSINESS_FINANCE = "Business/Finance"
    CELEBRITIES = "Celebrities"
    EDUCATION = "Education"
    FOOD_AND_DRINK = "Food and drink"
    HEALTHCARE_MEDICAL = "Healthcare/Medical"
    HOLIDAYS = "Holidays"
    INDUSTRIAL = "Industrial"
    INTERIORS = "Interiors"
    MISCELLANEOUS = "Miscellaneous"
    NATURE = "Nature"
    OBJECTS = "Objects"
    PARKS_OUTDOOR = "Parks/Outdoor"
    PEOPLE = "People"
    RELIGION = "Religion"
    SCIENCE = "Science"
    SIGNS_SYMBOLS = "Signs/Symbols"
    SPORTS_RECREATION = "Sports/Recreation"
    TECHNOLOGY = "Technology"
    TRANSPORTATION = "Transportation"
    VINTAGE = "Vintage"

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

    # Chosen last, once title/description/keywords have already forced the
    # model to settle on what the image actually is.
    adobe_category: AdobeStockCategory
    shutterstock_category_primary: ShutterstockCategory
    shutterstock_category_secondary: Optional[ShutterstockCategory] = None


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
            if (
                parsed.shutterstock_category_secondary
                == parsed.shutterstock_category_primary
            ):
                parsed.shutterstock_category_secondary = None
            return parsed
        except RateLimitError:
            if attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            time.sleep(RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))
