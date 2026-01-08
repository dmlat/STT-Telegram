import logging
import os
import ffmpeg
from openai import AsyncOpenAI
from src.config import OPENAI_KEY

client = AsyncOpenAI(api_key=OPENAI_KEY)

async def compress_audio(input_path: str, output_path: str) -> bool:
    """
    Compresses audio to OGG Opus with low bitrate (32k) to fit into 25MB limit.
    Returns True if successful, False otherwise.
    """
    try:
        # Convert to ogg opus with 32k bitrate and mono channel (ac 1) to save space
        stream = ffmpeg.input(input_path)
        stream = ffmpeg.output(stream, output_path, acodec='libopus', b='32k', ac=1, loglevel='error')
        ffmpeg.run(stream, overwrite_output=True)
        return True
    except ffmpeg.Error as e:
        logging.error(f"FFmpeg error: {e.stderr.decode('utf8') if e.stderr else str(e)}")
        return False
    except Exception as e:
        logging.error(f"Compression error: {e}")
        return False

async def transcribe_audio(file_path: str) -> tuple[str, str]:
    """
    Transcribes audio file using OpenAI Whisper API.
    Handles files > 25MB by attempting to compress them first.
    Returns: (text, status_detail)
    status_detail: 'original' or 'compressed'
    """
    file_size = os.path.getsize(file_path)
    final_path = file_path
    compressed_file = None
    status_detail = "original"
    
    # OpenAI limit is 25MB. We use 24MB as safety threshold.
    if file_size > 24 * 1024 * 1024:
        logging.info(f"File size {file_size} bytes exceeds limit. Attempting compression...")
        
        dir_name = os.path.dirname(file_path)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        compressed_file = os.path.join(dir_name, f"{base_name}_compressed.ogg")
        
        success = await compress_audio(file_path, compressed_file)
        
        if success:
            new_size = os.path.getsize(compressed_file)
            logging.info(f"Compression successful. New size: {new_size} bytes.")
            
            if new_size > 24 * 1024 * 1024:
                logging.warning("Compressed file still too large.")
                # Clean up immediately if failed check
                if os.path.exists(compressed_file):
                    os.remove(compressed_file)
                raise ValueError("FILE_TOO_LARGE_EVEN_AFTER_COMPRESSION")
            
            final_path = compressed_file
            status_detail = "compressed"
        else:
            logging.error("Compression failed.")
            raise ValueError("COMPRESSION_FAILED")

    try:
        with open(final_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                response_format="text"
            )
        return transcript, status_detail
    except Exception as e:
        logging.error(f"Transcription error: {e}")
        raise e
    finally:
        # Clean up compressed file if it was created
        if compressed_file and os.path.exists(compressed_file):
            os.remove(compressed_file)
