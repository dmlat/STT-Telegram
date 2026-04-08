import asyncio
import logging
import os
import time
import math
import mutagen
import traceback
from openai import OpenAIError
from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, StateFilter
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, LabeledPrice, PreCheckoutQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from src.config import BOT_TOKEN, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, ADMIN_ID
from src.services.db_service import (
    init_db, get_or_create_user, add_voice_message, get_user_stats,
    add_review, check_user_limit, update_user_usage,
    create_transaction, complete_transaction, get_transaction, get_all_user_ids,
    add_balance_seconds,
)
from src.services.google_sheets_service import gs_service
from src.services.openai_service import transcribe_audio
from src.services.stars_invoice import parse_stars_invoice_payload
from src.services.stars_refund_service import (
    refund_telegram_stars_by_charge_id,
    refund_telegram_stars_by_tx_id,
)
from src.services.payment_service import (
    get_tariff_price,
    rub_price_to_stars,
    create_yookassa_payment,
    check_yookassa_payment,
)
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

class PaymentState(StatesGroup):
    waiting_for_custom_minutes = State()
    waiting_for_payment_method = State() # amount, minutes in data


class BroadcastState(StatesGroup):
    waiting_for_text = State()


# Mandatory test recipient before mass broadcast (see ReadMe/PROD.md)
BROADCAST_TEST_USER_ID = 280186359
BROADCAST_ANNOUNCEMENT_TEXT = (
    "Теперь доступны пакеты минут для расшифровки голоса в текст. Спасибо за ожидание."
)


def _is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


def _yookassa_configured() -> bool:
    return bool(YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY)


# --- Keyboards ---
def get_main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎙 Расшифровать")],
            [KeyboardButton(text="💡 Предложения по улучшению")],
            [KeyboardButton(text="💎 Мой баланс / Купить")]
        ],
        resize_keyboard=True
    )

def get_tariffs_kb():
    p = get_tariff_price
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"10 минут — {p(10)} ₽", callback_data="buy_10")],
        [InlineKeyboardButton(text=f"30 минут — {p(30)} ₽", callback_data="buy_30")],
        [InlineKeyboardButton(text=f"1 час — {p(60)} ₽", callback_data="buy_60")],
        [InlineKeyboardButton(text=f"5 часов — {p(300)} ₽", callback_data="buy_300")],
        [InlineKeyboardButton(text=f"10 часов — {p(600)} ₽", callback_data="buy_600")],
        [InlineKeyboardButton(text="✏️ Свой тариф", callback_data="buy_custom")],
        [InlineKeyboardButton(text="🔙 Закрыть", callback_data="payment_close")],
    ])


def get_payment_method_kb(amount_rub: int):
    stars = rub_price_to_stars(amount_rub)
    rows = []
    if _yookassa_configured():
        rows.append([InlineKeyboardButton(text=f"YooKassa ({amount_rub} ₽)", callback_data="pay_method_yookassa")])
    rows.append([InlineKeyboardButton(text=f"Telegram Stars ({stars} ⭐)", callback_data=f"pay_method_stars_{stars}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="payment_back_to_tariffs")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_check_payment_kb(payment_id: str, url: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Оплатить", url=url)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_pay_{payment_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="payment_back_to_tariffs")]
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
def get_audio_duration(file_path: str) -> float:
    try:
        audio = mutagen.File(file_path)
        if audio is not None and audio.info is not None:
            return audio.info.length
    except Exception as e:
        logging.error(f"Error getting duration: {e}")
    return 0.0

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
        
        text_result, _ = await transcribe_audio(local_filename)
        return text_result
    except Exception as e:
        logging.error(f"Transcribe error: {e}")
        raise e
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
    try:
        await gs_service.update_user_stats(stats)
    except Exception as e:
        logging.exception("update_user_stats on /start failed (bot still replies): %s", e)

    await message.answer(
        "Привет! Я бот для транскрибации аудио.\n\n"
        "Просто **перешли** мне голосовое сообщение или **отправь** аудиофайл, и я пришлю тебе текст.\n\n"
        "📂 **Поддерживаемые форматы:**\n"
        "- Голосовые сообщения Telegram\n"
        "- Аудиофайлы: `mp3`, `ogg`, `wav`, `m4a`\n\n"
        "🎁 **Бесплатно:** 5 минут на пробу (один раз на аккаунт).\n"
        "Далее — по тарифам (от 59 ₽).",
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
        "Вы также можете записать **голосовое сообщение** (до 120 секунд) 😉.\n\n"
        "Мы внимательно читаем каждый отзыв!",
        reply_markup=get_cancel_kb(),
        parse_mode="Markdown"
    )
    await state.update_data(start_time=time.time())
    await state.set_state(FeedbackState.waiting_for_suggestion)

def format_minutes(minutes: float) -> str:
    """Formats float minutes (e.g. 4.9) to '4 мин 54 сек'"""
    total_seconds = int(round(minutes * 60))
    m = total_seconds // 60
    s = total_seconds % 60
    if m > 0 and s > 0:
        return f"{m} мин {s} сек"
    elif m > 0:
        return f"{m} мин"
    else:
        return f"{s} сек"

@dp.message(F.text == "💎 Мой баланс / Купить")
async def menu_balance(message: types.Message):
    user_id = message.from_user.id
    stats = await get_user_stats(user_id)
    
    balance_min = stats.get("balance_minutes", 0)
    free_min = stats.get("free_left_minutes", 0)
    
    balance_str = format_minutes(balance_min)
    free_str = format_minutes(free_min)
    
    text = (
        f"👤 **Ваш баланс:**\n"
        f"🟢 Куплено: **{balance_str}**\n"
        f"🎁 Бесплатно: **{free_str}**\n\n"
    )
    if not _yookassa_configured():
        text += (
            "💫 **Оплата пакетов:** через **Telegram Stars**.\n"
            "Оплата картой (YooKassa) появится позже.\n\n"
        )
    text += "👇 Пополнить баланс:"
    await message.answer(text, reply_markup=get_tariffs_kb(), parse_mode="Markdown")

# --- Payment Logic ---

@dp.callback_query(F.data.startswith("buy_"))
async def process_tariff_selection(callback: types.CallbackQuery, state: FSMContext):
    item = callback.data.split("_")[1]
    
    if item == "custom":
        await callback.message.answer(
            "Введите количество минут (числом), которое хотите купить:",
            reply_markup=get_cancel_kb()
        )
        await state.set_state(PaymentState.waiting_for_custom_minutes)
        await callback.answer()
        return

    minutes = int(item)
    price = get_tariff_price(minutes)
    
    await state.update_data(minutes=minutes, amount=price)
    
    await callback.message.edit_text(
        f"Вы выбрали: **{minutes} минут**\n"
        f"К оплате: **{price} ₽**\n\n"
        "Выберите способ оплаты:",
        reply_markup=get_payment_method_kb(price),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(PaymentState.waiting_for_custom_minutes, F.text)
async def process_custom_minutes(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await menu_balance(message)
        return

    try:
        minutes = int(message.text)
        if minutes <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите корректное положительное число.")
        return

    price = get_tariff_price(minutes)
    await state.update_data(minutes=minutes, amount=price)
    
    await message.answer(
        f"Вы выбрали: **{minutes} минут**\n"
        f"К оплате: **{price} ₽**\n\n"
        "Выберите способ оплаты:",
        reply_markup=get_payment_method_kb(price),
        parse_mode="Markdown"
    )
    # Leave FSM step so successful_payment is not intercepted by this handler (custom tariff + Stars).
    await state.set_state(None)

@dp.callback_query(F.data == "payment_back_to_tariffs")
async def back_to_tariffs(callback: types.CallbackQuery, state: FSMContext):
    await state.clear() # Clear potential custom input state
    await callback.message.edit_text(
        "Выберите тариф:",
        reply_markup=get_tariffs_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "payment_close")
async def close_payment(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data == "pay_method_yookassa")
async def pay_yookassa(callback: types.CallbackQuery, state: FSMContext):
    if not _yookassa_configured():
        await callback.answer("Оплата картой сейчас недоступна. Используйте Telegram Stars.", show_alert=True)
        return

    data = await state.get_data()
    amount = data.get("amount")
    minutes = data.get("minutes")
    
    if not amount or not minutes:
        await callback.answer("Ошибка сессии. Попробуйте снова.")
        return

    # Create Transaction (pending)
    tx_id = await create_transaction(
        user_id=callback.from_user.id,
        provider="yookassa",
        amount=amount,
        seconds=minutes * 60
    )
    
    # Create YooKassa payment
    res = create_yookassa_payment(
        amount=float(amount),
        description=f"Покупка {minutes} минут",
        return_url="https://t.me/Voice2Text_Instant_bot",
        metadata={"tx_id": tx_id}
    )
    
    if not res:
        await callback.answer("Ошибка создания платежа.")
        return
        
    # KB with tx_id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Оплатить", url=res['confirmation_url'])],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_pay_{tx_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="payment_back_to_tariffs")]
    ])
    
    await callback.message.edit_text(
        f"Счет на оплату **{amount} ₽** создан.\n"
        f"После оплаты нажмите **'✅ Я оплатил'**.",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("check_pay_"))
async def check_pay_handler(callback: types.CallbackQuery):
    tx_id = int(callback.data.split("_")[2])
    
    tx = await get_transaction(tx_id)
    if not tx:
        await callback.answer("Транзакция не найдена.")
        return
        
    if tx.status == "success":
        await callback.message.edit_text("✅ Этот счет уже оплачен.")
        return

    # Check yookassa
    status = check_yookassa_payment(tx.payment_id)
    
    if status == "succeeded":
        await complete_transaction(tx_id, "success")
        await callback.message.edit_text(
            "✅ **Оплата прошла успешно!**\n"
            "Минуты начислены на ваш баланс.",
            parse_mode="Markdown"
        )
    elif status == "canceled":
        await callback.message.edit_text("❌ Платеж был отменен.")
    else:
        await callback.answer(f"Статус: {status}. Попробуйте еще раз через минуту.", show_alert=True)


@dp.callback_query(F.data.startswith("pay_method_stars_"))
async def pay_stars(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    minutes = data.get("minutes")
    amount_rub = data.get("amount")
    amount_xtr = int(callback.data.split("_")[3])
    expected = rub_price_to_stars(int(amount_rub))
    if amount_xtr != expected:
        await callback.answer("Тариф устарел, откройте оплату заново.", show_alert=True)
        return

    await callback.message.answer_invoice(
        title=f"Пакет {minutes} минут",
        description=f"Покупка {minutes} минут расшифровки.",
        payload=f"buy_{minutes}_{amount_rub}",  # minutes + RUB list price for analytics
        provider_token="", # Empty for Stars
        currency="XTR",
        prices=[LabeledPrice(label=f"{minutes} мин", amount=amount_xtr)],
        start_parameter="buy_stars"
    )
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message, state: FSMContext):
    try:
        payment_info = message.successful_payment
        payload = payment_info.invoice_payload

        try:
            minutes, amount_rub = parse_stars_invoice_payload(payload)
        except (ValueError, TypeError) as e:
            logging.exception("Stars payment: bad invoice_payload %r: %s", payload, e)
            await message.answer(
                "Оплата прошла, но не удалось разобрать чек. Напишите в поддержку с временем оплаты.",
            )
            return

        u = message.from_user
        await get_or_create_user(u.id, u.username or "", u.first_name or "")

        tx_id = await create_transaction(
            user_id=u.id,
            provider="telegram_stars",
            amount=amount_rub,
            seconds=minutes * 60,
            payment_id=payment_info.telegram_payment_charge_id,
            invoice_payload=payload,
        )
        ok = await complete_transaction(tx_id, "success")
        if not ok:
            logging.error(
                "Stars payment: complete_transaction returned False (tx_id=%s, user=%s)",
                tx_id,
                u.id,
            )
            await message.answer(
                "Оплата получена; начисление не применено (конфликт статуса). Обратитесь в поддержку.",
            )
            return

        await message.answer(
            f"✅ **Оплата прошла успешно!**\n"
            f"На ваш баланс начислено **{minutes} минут**.",
            parse_mode="Markdown",
        )
    except Exception:
        logging.exception(
            "Stars payment: create/complete failed for user %s",
            message.from_user.id,
        )
        await message.answer(
            "Оплата прошла, но начисление временно не удалось. Напишите в поддержку.",
        )
    finally:
        await state.clear()


# --- Admin broadcast (see ReadMe/PROD.md) ---
@dp.message(Command("broadcast_test"))
async def cmd_broadcast_test(message: types.Message, bot: Bot):
    if not _is_admin(message.from_user.id):
        return
    try:
        await bot.send_message(BROADCAST_TEST_USER_ID, BROADCAST_ANNOUNCEMENT_TEXT)
        await message.answer(
            f"Тестовое сообщение отправлено пользователю `{BROADCAST_TEST_USER_ID}`.",
            parse_mode="Markdown",
        )
    except TelegramForbiddenError:
        await message.answer(
            "Не удалось доставить: пользователь недоступен или заблокировал бота."
        )
    except Exception as e:
        logging.exception("broadcast_test failed")
        await message.answer(f"Ошибка отправки: {e}")


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_for_text)
    await message.answer(
        "Отправьте **текст рассылки** следующим сообщением.\n"
        "/cancel_broadcast — отмена.\n\n"
        "Перед массовой рассылкой всегда делайте `/broadcast_test`.",
        parse_mode="Markdown",
    )


@dp.message(Command("cancel_broadcast"), StateFilter(BroadcastState.waiting_for_text))
async def cmd_cancel_broadcast(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("Рассылка отменена.")


@dp.message(Command("admin_refund_stars"))
async def cmd_admin_refund_stars(message: types.Message, bot: Bot):
    """Полный refund Stars по id строки transactions (только ADMIN_ID)."""
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Использование: /admin_refund_stars <transaction_id>")
        return
    try:
        tx_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный transaction_id.")
        return
    ok, text = await refund_telegram_stars_by_tx_id(bot, tx_id)
    prefix = "✅ " if ok else "❌ "
    await message.answer(prefix + text)


@dp.message(Command("admin_refund_stars_charge"))
async def cmd_admin_refund_stars_charge(message: types.Message, bot: Bot):
    """Refund по user_id и telegram_payment_charge_id из чека."""
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer(
            "Использование: /admin_refund_stars_charge <telegram_user_id> <telegram_payment_charge_id>"
        )
        return
    try:
        uid = int(parts[1])
        charge_id = parts[2].strip()
    except ValueError:
        await message.answer("Некорректный user_id.")
        return
    if not charge_id:
        await message.answer("Пустой charge_id.")
        return
    ok, text = await refund_telegram_stars_by_charge_id(bot, uid, charge_id)
    prefix = "✅ " if ok else "❌ "
    await message.answer(prefix + text)


@dp.message(Command("admin_add_balance"))
async def cmd_admin_add_balance(message: types.Message):
    """Ручное начисление купленных секунд (только ADMIN_ID). См. ReadMe/PROD.md."""
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer(
            "Использование: /admin_add_balance <telegram_user_id> <секунды>\n"
            "Пример: /admin_add_balance 123456789 300"
        )
        return
    try:
        uid = int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        await message.answer("Некорректные числа.")
        return
    ok = await add_balance_seconds(uid, seconds)
    if ok:
        await message.answer(
            f"Начислено **{seconds}** сек пользователю `{uid}`.",
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            f"Пользователь `{uid}` не найден в БД (нужен хотя бы /start).",
            parse_mode="Markdown",
        )


@dp.message(
    StateFilter(BroadcastState.waiting_for_text),
    F.text,
    ~F.text.startswith("/"),
)
async def run_broadcast(message: types.Message, state: FSMContext, bot: Bot):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    text = message.text.strip()
    if not text:
        await message.answer("Пустой текст. Отправьте текст или /cancel_broadcast.")
        return
    await state.clear()
    user_ids = await get_all_user_ids()
    ok, fail = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            ok += 1
        except TelegramForbiddenError:
            fail += 1
            logging.info("Broadcast skip (forbidden): user_id=%s", uid)
        except Exception as e:
            fail += 1
            logging.warning("Broadcast fail user_id=%s: %s", uid, e)
        await asyncio.sleep(0.05)
    await message.answer(
        f"Готово. Отправлено: {ok}, ошибок/пропусков: {fail}, всего в базе: {len(user_ids)}."
    )


# --- Cancel Handler ---
@dp.message(F.text == "🔙 Назад", StateFilter(FeedbackState))
async def process_cancel_feedback(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. Возвращаюсь в главное меню.", reply_markup=get_main_menu_kb())

# --- Feedback Logic ---
@dp.message(FeedbackState.waiting_for_suggestion, F.text | F.voice)
async def process_suggestion_content(message: types.Message, state: FSMContext):
    user = message.from_user
    content = ""

    if message.voice:
        if message.voice.duration > 120:
            await message.answer("⚠️ Голосовое сообщение слишком длинное. Пожалуйста, отправьте отзыв короче 2 минут.")
            return

        msg_wait = await message.answer("Расшифровываю ваш отзыв...")
        try:
            content = await process_voice_file(bot, message.voice.file_id)
        except:
            await message.answer("Ошибка обработки аудио.")
            return
        finally:
            await bot.delete_message(message.chat.id, msg_wait.message_id)
    else:
        content = message.text
        if content == "🔙 Назад": 
            await state.clear()
            await message.answer("Меню", reply_markup=get_main_menu_kb())
            return

    await add_review(user.id, "suggestion", content)
    asyncio.create_task(gs_service.log_review({
        "user_id": user.id,
        "type": "Suggestion",
        "content": content
    }))
    
    await message.answer("Спасибо! Ваше предложение записано.", reply_markup=get_main_menu_kb())
    await state.clear()

@dp.message(FeedbackState.waiting_for_negative_custom, F.text | F.voice)
async def process_negative_custom_content(message: types.Message, state: FSMContext):
    user = message.from_user
    content = ""
    
    if message.voice:
        if message.voice.duration > 120:
            await message.answer("⚠️ Голосовое сообщение слишком длинное. Пожалуйста, отправьте отзыв короче 2 минут.")
            return

        msg_wait = await message.answer("Расшифровываю ваш отзыв...")
        try:
            content = await process_voice_file(bot, message.voice.file_id)
        except:
             await message.answer("Ошибка.")
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
    
    await message.answer("Спасибо за отзыв!", reply_markup=get_main_menu_kb())
    await state.clear()


# --- Main Audio Handler ---
@dp.message(F.audio | F.voice | F.document)
async def handle_audio(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state in [FeedbackState.waiting_for_suggestion, FeedbackState.waiting_for_negative_custom]:
        await message.answer("Пожалуйста, отправьте голосовое сообщение или текст для отзыва, либо нажмите 'Назад'.")
        return

    user = message.from_user
    file_id = None
    duration = 0
    file_size = 0
    
    if message.voice:
        file_id = message.voice.file_id
        duration = message.voice.duration
        file_size = message.voice.file_size
    elif message.audio:
        file_id = message.audio.file_id
        duration = message.audio.duration
        file_size = message.audio.file_size
    elif message.document:
        if message.document.mime_type and message.document.mime_type.startswith('audio/'):
            file_id = message.document.file_id
            duration = 0 # Will verify later
            file_size = message.document.file_size
        else:
            return

    if not file_id:
        return
        
    # Warn user about processing
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
        
        # Determine duration if unknown
        if duration == 0:
            duration = get_audio_duration(local_filename)
            if duration == 0:
                await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
                await message.answer("Не удалось определить длительность аудио.")
                if local_filename and os.path.exists(local_filename):
                    os.remove(local_filename)
                return

        # Check Limits
        can_process, missing_seconds = await check_user_limit(user.id, duration)
        
        if not can_process:
            if local_filename and os.path.exists(local_filename):
                os.remove(local_filename)
            
            await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
            
            text = (
                "⛔️ **Недостаточно минут!**\n\n"
                f"Для расшифровки этого файла ({int(duration)} сек) вам не хватает **{int(missing_seconds)} секунд**."
            )
            
            needed_minutes = math.ceil(missing_seconds / 60)
            price = get_tariff_price(needed_minutes)
            
            upsell_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"Купить {needed_minutes} мин за {price} ₽", callback_data=f"buy_{needed_minutes}")],
                [InlineKeyboardButton(text="💎 Выбрать тариф", callback_data="payment_back_to_tariffs")]
            ])
            
            await message.answer(text, reply_markup=upsell_kb, parse_mode="Markdown")
            return

        # Let's update status message
        await bot.edit_message_text("Отправляю в обработку... / Sending to processing...", chat_id=message.chat.id, message_id=status_msg.message_id)

        start_time = time.time()
        
        try:
            # transcribe_audio now returns (text, status_detail)
            text_result, status_detail = await transcribe_audio(local_filename)
            
            # Map status_detail to human readable string for DB/Logs
            final_status = "Без сжатия" if status_detail == "original" else "Сжатие"
            error = None
            
        except ValueError as ve:
            # Handled errors from service
            final_status = "Ошибка" # General Russian fail status
            error_raw = str(ve)
            error = error_raw # Default
            
            if "FILE_TOO_LARGE" in error_raw:
                await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
                await message.answer("⚠️ Файл слишком большой даже после сжатия. Пожалуйста, разделите его на части.")
                error = "Слишком большой (после сжатия)"
            elif "COMPRESSION_FAILED" in error_raw:
                await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
                await message.answer("⚠️ Ошибка при обработке файла.")
                error = "Ошибка сжатия"
            else:
                await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
                await message.answer("⚠️ Ошибка при расшифровке.")
                error = "Ошибка Whisper"
            
            # Log failure
            await add_voice_message(user.id, duration, 0, 0, final_status, error, text=None)
            asyncio.create_task(gs_service.log_voice_message({
                "user_id": user.id,
                "process_speed": 0,
                "length_sec": duration,
                "length_chars": 0,
                "status": final_status,
                "error_reason": error
            }))
            return

        end_time = time.time()
        
        processing_time = round(end_time - start_time, 2)
        text_len = len(text_result)
        
        await get_or_create_user(user.id, user.username, user.first_name)
        await update_user_usage(user.id, duration)
        await add_voice_message(user.id, duration, text_len, processing_time, final_status, None, text=text_result)
        
        # Stats logging
        stats = await get_user_stats(user.id)
        asyncio.create_task(gs_service.log_voice_message({
            "user_id": user.id,
            "process_speed": processing_time,
            "length_sec": duration,
            "length_chars": text_len,
            "status": final_status,
            "error_reason": ""
        }))
        asyncio.create_task(gs_service.update_user_stats(stats))

        # File creation
        timestamp = datetime.now(timezone.utc).strftime("%d.%m.%Y_%H-%M")
        txt_filename = f"{TEMP_DIR}/{timestamp}.txt"
        with open(txt_filename, "w", encoding="utf-8") as f:
            f.write(text_result)
            
        input_file = FSInputFile(txt_filename, filename=f"{timestamp}.txt")
        
        await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)

        if text_len < 4090:
            await message.answer(f"```\n{text_result}\n```", parse_mode="Markdown")
            await message.answer_document(input_file, caption="Вам понравилась расшифровка?", reply_markup=get_feedback_kb())
        else:
            await message.answer("⚠️ Расшифровка получилась очень длинной (больше лимита Telegram), поэтому отправляю её только файлом 👇")
            await message.answer_document(input_file, caption="Вам понравилась расшифровка?", reply_markup=get_feedback_kb())

    except OpenAIError as oe:
        logging.error(f"OpenAI API Error: {oe}")
        await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        await message.answer("⚠️ Сервис расшифровки временно недоступен (ошибка API). Попробуйте позже.")
        
        if ADMIN_ID:
            await bot.send_message(
                ADMIN_ID,
                f"🚨 **OpenAI Error**\nUser: {user.id} (@{user.username})\nError: `{oe}`"
            )

    except Exception as e:
        logging.error(f"Critical error processing voice: {e}")
        logging.error(traceback.format_exc())
        await bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        await message.answer("Произошла внутренняя ошибка сервера. Мы уже разбираемся.")
        
        if ADMIN_ID:
            tb = traceback.format_exc()[-1000:] # Last 1000 chars
            await bot.send_message(
                ADMIN_ID,
                f"🚨 **Critical Error**\nUser: {user.id} (@{user.username})\nError: `{e}`\nTrace:\n`{tb}`",
                parse_mode="Markdown"
            )
    
    finally:
        if local_filename and os.path.exists(local_filename):
            os.remove(local_filename)
        if txt_filename and os.path.exists(txt_filename):
            os.remove(txt_filename)

@dp.callback_query(F.data == "feedback_yes")
async def feedback_yes(callback: types.CallbackQuery):
    user = callback.from_user
    await add_review(user.id, "positive", None)
    asyncio.create_task(gs_service.log_review({"user_id": user.id, "type": "Positive", "content": "-"}))
    await callback.message.edit_caption(caption="Спасибо за отзыв! 🚀")
    await callback.answer()

@dp.callback_query(F.data == "feedback_no")
async def feedback_no(callback: types.CallbackQuery):
    await callback.message.edit_caption(
        caption="Укажите причину:",
        reply_markup=get_negative_reason_kb()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("reason_"))
async def feedback_reason(callback: types.CallbackQuery, state: FSMContext):
    reason_code = callback.data.split("_", 1)[1]
    if reason_code == "custom":
        await callback.message.answer(
            "Напишите, что не так?\n"
            "Вы также можете отправить голосовое сообщение (до 120 секунд).",
            reply_markup=get_cancel_kb()
        )
        await state.set_state(FeedbackState.waiting_for_negative_custom)
        await callback.answer()
        return

    await add_review(callback.from_user.id, f"negative_{reason_code}", reason_code)
    # Log to sheets...
    await callback.message.edit_caption(caption="Спасибо, мы учтём это! 🛠")
    await callback.answer()

# --- Catch-all for text messages (never swallow /commands) ---
@dp.message(F.text & ~F.text.startswith("/"))
async def handle_any_text(message: types.Message):
    await message.answer("Просто пришлите мне аудиофайл или голосовое сообщение!", reply_markup=get_main_menu_kb())


async def main():
    if not BOT_TOKEN or not str(BOT_TOKEN).strip():
        raise SystemExit("BOT_TOKEN is not set or empty — check .env on the server.")

    await init_db()
    gs_service.connect()
    logging.info("Starting polling…")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
