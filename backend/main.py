
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAI, APIError, AuthenticationError, RateLimitError
from pydantic import BaseModel, Field


# Load environment variables from the project-root .env file.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

app = FastAPI(
    title="ShortCraft AI",
    description="AI-powered YouTube Shorts generation platform",
    version="0.3.0",
)


class StoryInput(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    target_duration: int = Field(default=45, ge=30, le=60)


class ScriptRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    target_duration: int = Field(default=45, ge=30, le=60)
    style: str = Field(default="engaging", max_length=30)


@app.get("/")
def root():
    return {
        "project": "ShortCraft AI",
        "status": "running",
        "version": "0.3.0",
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/v1/story/prepare")
def prepare_story(story: StoryInput):
    cleaned_text = story.text.strip()

    if not cleaned_text:
        raise HTTPException(
            status_code=400,
            detail="Story text cannot be empty.",
        )

    words = cleaned_text.split()
    word_count = len(words)
    estimated_seconds = round((word_count / 150) * 60)
    target_word_count = round(story.target_duration * 2.2)

    return {
        "success": True,
        "original_text": cleaned_text,
        "character_count": len(cleaned_text),
        "word_count": word_count,
        "target_duration": story.target_duration,
        "estimated_seconds": estimated_seconds,
        "suggested_word_count": target_word_count,
        "message": "Story validated successfully.",
    }


@app.post("/api/v1/story/generate-script")
def generate_script(request: ScriptRequest):
    story_text = request.text.strip()

    if not story_text:
        raise HTTPException(
            status_code=400,
            detail="Story text cannot be empty.",
        )

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is missing from the project .env file.",
        )

    target_words = round(request.target_duration * 2.2)

    style_instructions = {
        "engaging": "Use an engaging, natural storytelling style.",
        "dramatic": "Use suspenseful pacing without inventing details.",
        "casual": "Use a conversational, relatable tone.",
        "mystery": "Emphasize genuine uncertainty and suspense in the source.",
    }

    style = request.style.lower()
    style_instruction = style_instructions.get(
        style,
        style_instructions["engaging"],
    )

    instructions = f"""
You are the narration script writer for ShortCraft AI,
an application that turns Reddit stories into YouTube Shorts.

Rewrite the user's source story as narration suitable for spoken audio.

Requirements:
- Aim for approximately {target_words} words for a
  {request.target_duration}-second video.
- {style_instruction}
- Start with a compelling hook based on the actual source.
- Use clear, natural spoken English and short sentences.
- Preserve the source's important events and meaning.
- Do not invent characters, events, dialogue, or outcomes.
- Do not claim that fictional or unverified events are facts.
- Do not include camera directions, headings, or explanations.
- Return only the narration script.
- If the source is too short to reach the target naturally,
  do not add fabricated events just to increase its length.
"""

    try:
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            instructions=instructions,
            input=story_text,
        )

        generated_script = response.output_text.strip()

        if not generated_script:
            raise HTTPException(
                status_code=502,
                detail="The AI returned an empty script. Please try again.",
            )

        script_word_count = len(generated_script.split())
        estimated_seconds = round((script_word_count / 150) * 60)

        return {
            "success": True,
            "original_word_count": len(story_text.split()),
            "script": generated_script,
            "script_word_count": script_word_count,
            "target_duration": request.target_duration,
            "estimated_script_seconds": estimated_seconds,
            "style": style,
            "message": "Narration script generated successfully.",
        }

    except AuthenticationError:
        raise HTTPException(
            status_code=401,
            detail="OpenAI authentication failed. Check your API key.",
        )

    except RateLimitError:
        raise HTTPException(
            status_code=429,
            detail=(
                "OpenAI rate limit or quota reached. "
                "Check your API account and billing limits."
            ),
        )

    except APIError:
        raise HTTPException(
            status_code=502,
            detail="OpenAI could not complete the request. Please try again.",
        )
