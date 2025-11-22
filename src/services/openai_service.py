from openai import AsyncOpenAI
from src.config import OPENAI_KEY
import os

client = AsyncOpenAI(api_key=OPENAI_KEY)

async def transcribe_audio(file_path: str) -> str:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "rb") as audio_file:
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text"
        )
    
    return transcript

