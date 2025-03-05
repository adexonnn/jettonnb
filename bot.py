# bot.py
import asyncio
import aiohttp
import logging
from aiogram import Dispatcher, types
from aiogram.client.bot import Bot, DefaultBotProperties
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from config import BOT_TOKEN, API_URL, ADMIN_ID
from database import conn, cursor, init_db

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

pending_configs = {}   # key: (user_id, slot), value: {'notif_type': str, 'threshold': float}
pending_setup = {}     # key: user_id, value: (slot, stage)
last_price = None

async def fetch_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL) as resp:
                data = await resp.json()
                price = float(data.get('pair', {}).get('priceUsd', 0))
                return price
    except Exception as e:
        logging.error(f"Ошибка при получении цены: {e}")
        return None

async def price_monitor():
    global last_price
    while True:
        price = await fetch_price()
        if price is not None:
            cursor.execute("SELECT user_id, slot, threshold, notif_type FROM notifications")
            notifs = cursor.fetchall()
            change_text = ""
            if last_price is not None:
                change_percent = round(((price - last_price) / last_price) * 100, 2) if last_price != 0 else 0
                if abs(change_percent) > 0.01:  # Показываем только при изменении > 0.01%
                    if change_percent > 0:
                        change_text = f"\n⚙️ Изменение: +{change_percent}% 🟢\n"
                    elif change_percent < 0:
                        change_text = f"\n⚙️ Изменение: {change_percent}% 🔴\n"
            last_price = price

            for user_id, slot, threshold, notif_type in notifs:
                if notif_type == "none":
                    continue
                match notif_type:
                    case "выше":
                        condition = price > threshold
                    case "равно":
                        condition = abs(price - threshold) < 0.00001
                    case "ниже":
                        condition = price < threshold
                    case _:
                        condition = False
                if condition:
                    try:
                        msg = (
                            f"❗️ Уведомление (ячейка {slot}): Цена = {price}"
                        )
                        if change_text:
                            msg += f"{change_text}"
                        await bot.send_message(user_id, msg)
                    except Exception as e:
                        logging.error(f"Ошибка отправки сообщения {user_id}: {e}")
                    cursor.execute(
                        "UPDATE notifications SET notif_type = 'none', threshold = 0 WHERE user_id = ? AND slot = ?",
                        (user_id, slot)
                    )
                    conn.commit()
        await asyncio.sleep(60)

async def ensure_user_notifications(user_id: int):
    cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id,))
    if cursor.fetchone()[0] < 3:
        for slot in range(1, 4):
            cursor.execute("INSERT OR IGNORE INTO notifications (user_id, slot) VALUES (?, ?)", (user_id, slot))
        conn.commit()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await ensure_user_notifications(message.from_user.id)
    info_text = (
        "👋 Приветствую!\n"
        "В этом боте ты можешь ставить уведомления на определённой цене токена, и если он достигнет этой цены - вы получите уведомление.\n\n"
        "Поддержка бота: <a href=\"https://t.me/yourusername\">@yourusername</a>\n\n"
        "❗️ Бот находится в тестировании, могут быть ошибки. Если нашли - пишите в поддержку.\n\n"
        "<a href=\"https://t.me/yourchannel\"><b>Канал</b></a> | <a href=\"https://t.me/youychat\"><b>Чат</b></a>"
    )
    await message.reply(info_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    
    cursor.execute("SELECT slot, threshold, notif_type FROM notifications WHERE user_id = ?", (message.from_user.id,))
    notifs = cursor.fetchall()
    kb = build_notif_keyboard(notifs)
    await message.reply("Привет! Настройки уведомлений:", reply_markup=kb)

def build_notif_keyboard(notifs):
    buttons = []
    for slot, threshold, notif_type in notifs:
        if notif_type == "none" and threshold == 0:
            text = f"Ячейка {slot}: Нету"
        else:
            type_display = f"({notif_type.capitalize()})"
            text = f"Ячейка {slot}: {type_display} {threshold}"
        buttons.append([InlineKeyboardButton(text=text.strip(), callback_data=f"config_slot:{slot}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("notif"))
async def cmd_notif(message: types.Message):
    await ensure_user_notifications(message.from_user.id)
    cursor.execute("SELECT slot, threshold, notif_type FROM notifications WHERE user_id = ?", (message.from_user.id,))
    notifs = cursor.fetchall()
    kb = build_notif_keyboard(notifs)
    await message.reply("Настройки уведомлений:", reply_markup=kb)

def build_config_keyboard(slot: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выше", callback_data=f"type:{slot}:выше"),
         InlineKeyboardButton(text="Ниже", callback_data=f"type:{slot}:ниже"),
         InlineKeyboardButton(text="Равно", callback_data=f"type:{slot}:равно")],
        [InlineKeyboardButton(text="Удалить", callback_data=f"delete:{slot}")]
    ])

@dp.callback_query()
async def callback_handler(callback: CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id
    if data.startswith("config_slot:"):
        slot = int(data.split(":")[1])
        pending_setup[user_id] = (slot, "awaiting_type")
        await callback.message.edit_text(
            f"<b>Настройка ячейки {slot}:</b>\n"
            "Выберите тип уведомления ниже:",
            reply_markup=build_config_keyboard(slot)
        )
        await callback.answer()
    elif data.startswith("type:"):
        _, slot, notif_type = data.split(":")
        slot = int(slot)
        pending_configs[(user_id, slot)] = pending_configs.get((user_id, slot), {})
        pending_configs[(user_id, slot)]["notif_type"] = notif_type
        pending_setup[user_id] = (slot, "awaiting_threshold")
        await callback.answer(f"Выбран тип: {notif_type}")
        await callback.message.reply("Введите цену для уведомления:")
    elif data.startswith("delete:"):
        _, slot = data.split(":")
        slot = int(slot)
        cursor.execute("UPDATE notifications SET notif_type = 'none', threshold = 0 WHERE user_id = ? AND slot = ?",
                       (user_id, slot))
        conn.commit()
        await callback.answer("Ячейка удалена")
        cursor.execute("SELECT slot, threshold, notif_type FROM notifications WHERE user_id = ?", (user_id,))
        notifs = cursor.fetchall()
        kb = build_notif_keyboard(notifs)
        await callback.message.edit_text("Настройки уведомлений:", reply_markup=kb)
    elif data.startswith("save_config:"):
        _, slot = data.split(":")
        slot = int(slot)
        conf = pending_configs.pop((user_id, slot), {})
        notif_type = conf.get("notif_type", "none")
        threshold = conf.get("threshold", 0)
        cursor.execute("UPDATE notifications SET notif_type = ?, threshold = ? WHERE user_id = ? AND slot = ?",
                       (notif_type, threshold, user_id, slot))
        conn.commit()
        await callback.answer("Настройки сохранены")
        cursor.execute("SELECT slot, threshold, notif_type FROM notifications WHERE user_id = ?", (user_id,))
        notifs = cursor.fetchall()
        kb = build_notif_keyboard(notifs)
        await callback.message.edit_text("Настройки уведомлений:", reply_markup=kb)
    else:
        await callback.answer()

@dp.message()
async def handle_config_input(message: types.Message):
    user_id = message.from_user.id
    if user_id not in pending_setup:
        return
    slot, stage = pending_setup[user_id]
    text = message.text.strip().lower()
    if stage == "awaiting_type":
        if text not in {"выше", "равно", "ниже"}:
            await message.reply("Некорректный тип. Введите: выше, равно или ниже.")
            return
        pending_configs[(user_id, slot)] = pending_configs.get((user_id, slot), {})
        pending_configs[(user_id, slot)]["notif_type"] = text
        pending_setup[user_id] = (slot, "awaiting_threshold")
        await message.reply("Введите цену для уведомления:")
    elif stage == "awaiting_threshold":
        try:
            threshold = float(text)
        except ValueError:
            await message.reply("Некорректное значение. Пожалуйста, введите число.")
            return
        notif_type = pending_configs[(user_id, slot)]["notif_type"]
        current_price = await fetch_price()
        if current_price is not None:
            condition_met = False
            match notif_type:
                case "выше":
                    condition_met = current_price > threshold
                case "равно":
                    condition_met = abs(current_price - threshold) < 0.00001
                    if not condition_met and abs(current_price - threshold) > 0.1:
                        await message.reply(f"❗️ Введённое значение слишком отличается от текущей цены: {current_price}. Пожалуйста, введите значение ближе к текущей цене.")
                        return
                case "ниже":
                    condition_met = current_price < threshold
            if condition_met:
                await message.reply(f"❗️ Текущая цена уже соответствует введённым данным: {current_price}. Настройка не сохранена.")
                pending_setup.pop(user_id)
                return
        pending_configs[(user_id, slot)]["threshold"] = threshold
        pending_setup.pop(user_id)
        await message.reply(
            f"Установлен тип: {pending_configs[(user_id, slot)]['notif_type']} и порог: {threshold}.\nНажмите «Сохранить» для подтверждения изменений.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Сохранить", callback_data=f"save_config:{slot}")]
            ])
        )

async def start_bot():
    asyncio.create_task(price_monitor())
    await dp.start_polling(bot)