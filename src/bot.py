import asyncio
import logging
import os
import time
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from src.config import BOT_TOKEN
from src.services.db_service import init_db, get_or_create_user, add_voice_message, get_user_stats
from src.services.google_sheets_service import gs_service
from src.services.openai_service import transcribe_audio

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Temp directory
TEMP_DIR = "data/temp"
os.makedirs(TEMP_DIR, exist_ok=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    await get_or_create_user(user.id, user.username, user.first_name)
    
    # Update google sheets initial entry
    stats = await get_user_stats(user.id)
    await gs_service.update_user_stats(stats)
    
    await message.answer(
        "Привет! Перешли мне голосовое сообщение, и я расшифрую его в текст.\n"
        "Hello! Forward me a voice message and I will transcribe it to text."
    )

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user = message.from_user
    voice = message.voice
    
    # Basic info
    file_id = voice.file_id
    duration = voice.duration
    file_size = voice.file_size

    await message.answer("Обрабатываю голосовое... / Processing voice...")
    
    # Download file
    file = await bot.get_file(file_id)
    file_path = file.file_path
    local_filename = f"{TEMP_DIR}/{file_id}.ogg" # Telegram usually sends OGG
    
    await bot.download_file(file_path, local_filename)
    
    start_time = time.time()
    
    try:
        # Transcribe
        text_result = await transcribe_audio(local_filename)
        
        end_time = time.time()
        processing_time = round(end_time - start_time, 2)
        text_len = len(text_result)
        
        # DB Update
        await add_voice_message(user.id, duration, text_len, processing_time)
        stats = await get_user_stats(user.id)
        
        # Google Sheets Update (Background)
        asyncio.create_task(gs_service.log_voice_message({
            "user_id": user.id,
            "process_speed": processing_time,
            "length_sec": duration,
            "length_chars": text_len
        }))
        asyncio.create_task(gs_service.update_user_stats(stats))

        # Create TXT file
        txt_filename = f"{TEMP_DIR}/{file_id}.txt"
        with open(txt_filename, "w", encoding="utf-8") as f:
            f.write(text_result)
            
        # Send response
        input_file = FSInputFile(txt_filename)
        
        # Logic: < 4096 chars -> Text + File, else -> File only
        # User update: "if text fits in one message -> message AND txt file. If longer -> ONLY txt file"
        
        if text_len < 4090: # Safety margin
            # Format as code for easy copying
            await message.answer(f"```\n{text_result}\n```", parse_mode="Markdown")
            await message.answer_document(input_file, caption="Transcription file")
        else:
            await message.answer_document(input_file, caption="Text is too long for a message, here is the file.")

    except Exception as e:
        logging.error(f"Error processing voice: {e}")
        await message.answer("Произошла ошибка при обработке. / Error processing request.")
    
    finally:
        # Cleanup
        if os.path.exists(local_filename):
            os.remove(local_filename)
        if os.path.exists(txt_filename):
            os.remove(txt_filename)

async def main():
    # Init DB
    await init_db()
    
    # Connect Google Sheets
    gs_service.connect()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

