import asyncio
import logging
import os
import time
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from src.config import BOT_TOKEN
from src.services.db_service import init_db, get_or_create_user, add_voice_message, get_user_stats, add_review, check_user_limit, update_user_usage
from src.services.google_sheets_service import gs_service
from src.services.openai_service import transcribe_audio
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Temp directory
TEMP_DIR = "data/temp"
os.makedirs(TEMP_DIR, exist_ok=True)

# --- States ---
class FeedbackState(StatesGroup):
    waiting_for_negative_custom = State()
    waiting_for_suggestion = State()

# --- Keyboards ---
def get_main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎙 Расшифровать")],
            [KeyboardButton(text="💡 Предложения по улучшению")],
            [KeyboardButton(text="💎 Оформить доступ")]
        ],
        resize_keyboard=True
    )

def get_payment_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 день - 49 ₽", callback_data="pay_1_day")],
        [InlineKeyboardButton(text="7 дней - 249 ₽", callback_data="pay_7_days")],
        [InlineKeyboardButton(text="30 дней - 499 ₽", callback_data="pay_30_days")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="payment_close")] # Close inline menu
    ])

def get_pay_button_kb(amount: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {amount} ₽", url="https://example.com")], # Placeholder URL
        [InlineKeyboardButton(text="🔙 Назад", callback_data="payment_back")]
    ])

def get_feedback_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data="feedback_yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data="feedback_no")
        ]
    ])

def get_negative_reason_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤷‍♂️ Не уловил суть", callback_data="reason_bad_meaning")],
        [InlineKeyboardButton(text="📝 Плохая грамматика", callback_data="reason_bad_grammar")],
        [InlineKeyboardButton(text="🚫 Не прислал расшифровку", callback_data="reason_no_text")],
        [InlineKeyboardButton(text="✍️ Свой вариант", callback_data="reason_custom")]
    ])

def get_cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

# --- Helper for downloading and transcribing ---
async def process_voice_file(bot: Bot, file_id: str) -> str:
    """Downloads and transcribes a voice file, returns text."""
    local_filename = None
    try:
        file = await bot.get_file(file_id)
        file_path = file.file_path
        ext = os.path.splitext(file_path)[1]
        if not ext: ext = ".ogg"
        
        local_filename = f"{TEMP_DIR}/{file_id}{ext}"
        await bot.download_file(file_path, local_filename)
        
        text_result = await transcribe_audio(local_filename)
        return text_result
    finally:
        if local_filename and os.path.exists(local_filename):
            os.remove(local_filename)

# --- Handlers ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    await get_or_create_user(user.id, user.username, user.first_name)
    
    stats = await get_user_stats(user.id)
    await gs_service.update_user_stats(stats)
    
    await message.answer(
        "Привет! Я бот для транскрибации аудио.\n\n"
        "Просто **перешли** мне голосовое сообщение или **отправь** аудиофайл, и я пришлю тебе текст.\n\n"
        "📂 **Поддерживаемые форматы:**\n"
        "- Голосовые сообщения Telegram\n"
        "- Аудиофайлы: `mp3`, `ogg`, `wav`, `m4a`\n\n"
        "⚠️ **Ограничения:**\n"
        "- Файл должен быть не больше 20 МБ.\n"
        "- Пожалуйста, отправляй только аудио.",
        parse_mode="Markdown",
        reply_markup=get_main_menu_kb()
    )

@dp.message(F.text == "🎙 Расшифровать")
async def menu_transcribe(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Просто пришлите мне аудиофайл или голосовое сообщение!", reply_markup=get_main_menu_kb())

@dp.message(F.text == "💡 Предложения по улучшению")
async def menu_suggestions(message: types.Message, state: FSMContext):
    await message.answer(
        "Напишите, пожалуйста, ваши пожелания по улучшению продукта.\n"
        "Вы также можете записать **голосовое сообщение** 😉.\n\n"
        "Мы внимательно читаем каждый отзыв!",
        reply_markup=get_cancel_kb(),
        parse_mode="Markdown"
    )
    await state.update_data(start_time=time.time())
    await state.set_state(FeedbackState.waiting_for_suggestion)

@dp.message(F.text == "💎 Оформить доступ")
async def menu_subscription(message: types.Message):
    await message.answer(
        "💳 **Стоимость доступа** 👇\n\n"
        "Выберите подходящий тариф:",
        reply_markup=get_payment_kb(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("pay_"))
async def process_payment_selection(callback: types.CallbackQuery):
    plan = callback.data.split("_")[1] + "_" + callback.data.split("_")[2]
    
    prices = {
        "1_day": 49,
        "7_days": 249,
        "30_days": 499
    }
    
    price = prices.get(plan, 0)
    
    await callback.message.edit_text(
        f"Вы выбрали тариф: **{plan.replace('_', ' ')}**\n"
        f"К оплате: **{price} ₽**\n\n"
        f"Нажимая кнопку оплаты, вы соглашаетесь с [офертой](https://example.com).", # Placeholder
        reply_markup=get_pay_button_kb(price),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "payment_back")
async def payment_back(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💳 **Стоимость доступа** 👇\n\n"
        "Выберите подходящий тариф:",
        reply_markup=get_payment_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "payment_close")
async def payment_close(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# --- Cancel Handler ---
@dp.message(F.text == "🔙 Назад", StateFilter(FeedbackState))
async def process_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. Возвращаюсь в главное меню.", reply_markup=get_main_menu_kb())

# --- Feedback Logic (Text & Voice) ---

@dp.message(FeedbackState.waiting_for_suggestion, F.text | F.voice)
async def process_suggestion_content(message: types.Message, state: FSMContext):
    # Check timeout (5 minutes = 300 seconds)
    data = await state.get_data()
    start_time = data.get("start_time", 0)
    if time.time() - start_time > 300:
        await state.clear()
        # If it's voice, treat as normal transcription
        if message.voice or message.audio or message.document:
            await handle_audio(message, state)
            return
        else:
            await message.answer("Время ожидания отзыва истекло. Пожалуйста, воспользуйтесь меню.", reply_markup=get_main_menu_kb())
            return

    user = message.from_user
    content = ""

    if message.voice:
        msg_wait = await message.answer("Расшифровываю ваш отзыв...")
        try:
            content = await process_voice_file(bot, message.voice.file_id)
        except Exception as e:
            logging.error(f"Error transcribing feedback: {e}")
            await message.answer("Не удалось расшифровать отзыв, попробуйте текстом.")
            return
        finally:
            await bot.delete_message(message.chat.id, msg_wait.message_id)
    else:
        content = message.text
        if content == "🔙 Назад": # Should be caught by cancel handler but safe check
            await state.clear()
            await message.answer("Меню", reply_markup=get_main_menu_kb())
            return

    # Log to DB
    await add_review(user.id, "suggestion", content)
    # Log to Sheets
    asyncio.create_task(gs_service.log_review({
        "user_id": user.id,
        "type": "Suggestion",
        "content": content
    }))
    
    await message.answer("Спасибо! Ваше предложение записано. Вместе мы сделаем продукт лучше!", reply_markup=get_main_menu_kb())
    await state.clear()

@dp.message(FeedbackState.waiting_for_negative_custom, F.text | F.voice)
async def process_negative_custom_content(message: types.Message, state: FSMContext):
    # Check timeout (5 minutes = 300 seconds)
    data = await state.get_data()
    start_time = data.get("start_time", 0)
    if time.time() - start_time > 300:
        await state.clear()
        # If it's voice, treat as normal transcription
        if message.voice or message.audio or message.document:
            await handle_audio(message, state)
            return
        else:
            await message.answer("Время ожидания отзыва истекло. Пожалуйста, воспользуйтесь меню.", reply_markup=get_main_menu_kb())
            return

    user = message.from_user
    content = ""

    if message.voice:
        msg_wait = await message.answer("Расшифровываю ваш отзыв...")
        try:
            content = await process_voice_file(bot, message.voice.file_id)
        except Exception as e:
            logging.error(f"Error transcribing feedback: {e}")
            await message.answer("Не удалось расшифровать отзыв, попробуйте текстом.")
            return
        finally:
            await bot.delete_message(message.chat.id, msg_wait.message_id)
    else:
        content = message.text
        if content == "🔙 Назад": 
            await state.clear()
            await message.answer("Меню", reply_markup=get_main_menu_kb())
            return
    
    await add_review(user.id, "negative_custom", content)
    asyncio.create_task(gs_service.log_review({
        "user_id": user.id,
        "type": "Negative (Custom)",
        "content": content
    }))
    
    await message.answer("Спасибо за подробный отзыв! Мы работаем над исправлением.", reply_markup=get_main_menu_kb())
    await state.clear()

# --- Main Audio Handler (Global) ---
@dp.message(F.audio | F.voice | F.document)
async def handle_audio(message: types.Message, state: FSMContext):
    # If we are in feedback state, ignore this handler (it should have been caught above if it was voice)
    # But F.voice above only catches if state matches. 
    # If we are here, it means it's a normal transcription request OR a document/audio file sent during feedback (which we don't support for feedback, only voice)
    
    current_state = await state.get_state()
    if current_state in [FeedbackState.waiting_for_suggestion, FeedbackState.waiting_for_negative_custom]:
        await message.answer("Пожалуйста, отправьте голосовое сообщение или текст для отзыва, либо нажмите 'Назад'.")
        return

    user = message.from_user
    
    file_id = None
    duration = 0
    
    if message.voice:
        file_id = message.voice.file_id
        duration = message.voice.duration
    elif message.audio:
        file_id = message.audio.file_id
        duration = message.audio.duration
    elif message.document:
        if message.document.mime_type and message.document.mime_type.startswith('audio/'):
            file_id = message.document.file_id
            duration = 0 
        else:
            return

    if not file_id:
        return

    # Check limits
    # We need duration to check limit. For voice/audio it's available. For files we might not know yet.
    # If duration is 0 (e.g. document), we'll assume a small cost or check after processing?
    # Strategy: Let's trust Telegram duration if available, else allow processing and check after (risky but simpler)
    # Or: Reject documents without duration for free users?
    # Let's use what we have. If duration is 0, we can't check pre-limit properly.
    # NOTE: Telegram 'document' object doesn't always have duration. Audio/Voice does.
    
    can_process = await check_user_limit(user.id, duration)
    if not can_process:
        await message.answer(
            "⛔️ **Лимит превышен!**\n\n"
            "На бесплатном тарифе доступно **10 минут** расшифровки в сутки.\n"
            "Вы исчерпали свой лимит на сегодня.\n\n"
            "Оформите **Безлимитный доступ**, чтобы продолжить пользоваться ботом без ограничений! 👇",
            reply_markup=get_payment_kb(), # Show payment options directly
            parse_mode="Markdown"
        )
        return

    status_msg = await message.answer("Скачиваю и обрабатываю файл... / Downloading and processing...")
    
    local_filename = None
    txt_filename = None
    
    try:
        file = await bot.get_file(file_id)
        file_path = file.file_path
        ext = os.path.splitext(file_path)[1]
        if not ext: ext = ".ogg"
        
        local_filename = f"{TEMP_DIR}/{file_id}{ext}"
        await bot.download_file(file_path, local_filename)
        
        start_time = time.time()
        text_result = await transcribe_audio(local_filename)
        end_time = time.time()
        
        processing_time = round(end_time - start_time, 2)
        text_len = len(text_result)
        
        # Data logging
        await get_or_create_user(user.id, user.username, user.first_name)
        
        # Update usage
        await update_user_usage(user.id, duration)
        
        await add_voice_message(user.id, duration, text_len, processing_time)
        
        stats = await get_user_stats(user.id)
        asyncio.create_task(gs_service.log_voice_message({
            "user_id": user.id,
            "process_speed": processing_time,
            "length_sec": duration,
            "length_chars": text_len
        }))
        asyncio.create_task(gs_service.update_user_stats(stats))

        # File creation
        timestamp = datetime.now(timezone.utc).strftime("%d.%m.%Y_%H-%M")
        txt_filename = f"{TEMP_DIR}/{timestamp}.txt"
        with open(txt_filename, "w", encoding="utf-8") as f:
            f.write(text_result)
            
        input_file = FSInputFile(txt_filename, filename=f"{timestamp}.txt")
        
        # Send result
        await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)

        if text_len < 4090:
            await message.answer(f"```\n{text_result}\n```", parse_mode="Markdown")
            await message.answer_document(input_file, caption="Вам понравилась расшифровка?", reply_markup=get_feedback_kb())
        else:
            await message.answer_document(input_file, caption="Текст слишком длинный для сообщения. Вам понравилась расшифровка?", reply_markup=get_feedback_kb())

    except Exception as e:
        logging.error(f"Error processing voice: {e}")
        await message.answer("Произошла ошибка при обработке.")
    
    finally:
        if local_filename and os.path.exists(local_filename):
            os.remove(local_filename)
        if txt_filename and os.path.exists(txt_filename):
            os.remove(txt_filename)

# --- Callbacks ---

@dp.callback_query(F.data == "feedback_yes")
async def feedback_yes(callback: types.CallbackQuery):
    user = callback.from_user
    # Log positive
    await add_review(user.id, "positive", None)
    asyncio.create_task(gs_service.log_review({
        "user_id": user.id,
        "type": "Positive",
        "content": "-"
    }))
    await callback.message.edit_caption(caption="Спасибо за отзыв! 🚀")
    await callback.answer()

@dp.callback_query(F.data == "feedback_no")
async def feedback_no(callback: types.CallbackQuery):
    await callback.message.edit_caption(
        caption="Укажите, пожалуйста, причину. Это помогает нам стать лучше.\n"
                "Или напишите своё предложение. Буду очень благодарен!",
        reply_markup=get_negative_reason_kb()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("reason_"))
async def feedback_reason(callback: types.CallbackQuery, state: FSMContext):
    reason_code = callback.data.split("_", 1)[1]
    user = callback.from_user
    
    reason_map = {
        "bad_meaning": "Не уловил суть",
        "bad_grammar": "Плохая грамматика",
        "no_text": "Не прислал расшифровку"
    }
    
    if reason_code == "custom":
        await callback.message.answer("Напишите, что именно пошло не так?\nВы можете также записать голосовое сообщение 😉", reply_markup=get_cancel_kb())
        await state.update_data(start_time=time.time())
        await state.set_state(FeedbackState.waiting_for_negative_custom)
        await callback.answer()
        return

    reason_text = reason_map.get(reason_code, "Unknown")
    
    # Log negative
    await add_review(user.id, f"negative_{reason_code}", reason_text)
    asyncio.create_task(gs_service.log_review({
        "user_id": user.id,
        "type": "Negative",
        "content": reason_text
    }))
    
    await callback.message.edit_caption(caption="Спасибо, мы учтём это! 🛠")
    await callback.answer()

async def main():
    await init_db()
    gs_service.connect()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
