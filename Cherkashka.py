#!/usr/bin/env python3
import asyncio
import logging
import os
import random
import uuid
import requests
import json
from datetime import datetime, timedelta
from collections import deque
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, ErrorEvent
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Импортируем библиотеку yoomoney
try:
    from yoomoney import Client, Quickpay
    YOOMONEY_IMPORTED = True
except ImportError:
    YOOMONEY_IMPORTED = False
    logging.warning("Библиотека yoomoney не установлена. ЮMoney будет недоступен.")

load_dotenv()
logging.basicConfig(level=logging.INFO)

# файл для хранения балансов
BALANCE_FILE = "user_balances.json"
# файл для хранения истории транзакций
HISTORY_FILE = "transaction_history.json"

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN в файле .env или переменных окружения")

OWNER_ID = os.getenv("OWNER_ID")
if not OWNER_ID:
    raise ValueError("Не найден OWNER_ID в файле .env или переменных окружения")
OWNER_ID = int(OWNER_ID)

# Настройки CryptoBot
CRYPTOBOT_API_TOKEN = os.getenv("CRYPTOBOT_API_TOKEN")
# Настройки TON
TON_DEPOSIT_ADDRESS = os.getenv("TON_DEPOSIT_ADDRESS")
TON_API_KEY = os.getenv("TON_API_KEY")
# Настройки ЮMoney
YOOMONEY_RECEIVER = os.getenv("YOOMONEY_RECEIVER")
YOOMONEY_TOKEN = os.getenv("YOOMONEY_TOKEN")

DICE_COST = 10

# Вероятности выпадения
DICE_PROBABILITIES = {
    1: 0.3,
    2: 0.2,
    3: 0.2,
    4: 0.2,
    5: 0.08,
    6: 0.02
}

# <-- NEW: Призы за выпадение 6
PRIZES = [
    {"name": "ЗВЕЗДЫ В ТГ", "description": "25 звёзд", "url": "https://example.com/promo"}
]

# Доступные суммы для пополнения
DEPOSIT_AMOUNTS = [10, 20, 50, 100]

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

user_balances = {}
pending_payments = {}  # для хранения информации о платежах
transaction_history = {}  # для хранения истории транзакций пользователей
user_prizes = {}  # <-- NEW: для отслеживания полученных призов

# функции для сохранения и загрузки балансов
def save_balances():
    """Сохраняет балансы пользователей в файл"""
    try:
        with open(BALANCE_FILE, 'w') as f:
            json.dump(user_balances, f)
        logging.info(f"✅ Балансы сохранены ({len(user_balances)} пользователей)")
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения балансов: {e}")

def load_balances():
    """Загружает балансы пользователей из файла"""
    global user_balances
    try:
        if os.path.exists(BALANCE_FILE):
            with open(BALANCE_FILE, 'r') as f:
                user_balances = json.load(f)
                # Преобразуем ключи обратно в int (json сохраняет ключи как строки)
                user_balances = {int(k): v for k, v in user_balances.items()}
            logging.info(f"✅ Балансы загружены ({len(user_balances)} пользователей)")
        else:
            user_balances = {}
            logging.info("📁 Файл балансов не найден, создаём новый")
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки балансов: {e}")
        user_balances = {}

# функции для сохранения и загрузки истории транзакций
def save_history():
    """Сохраняет историю транзакций в файл"""
    try:
        # Преобразуем deque в список для сохранения
        history_to_save = {}
        for user_id, history in transaction_history.items():
            history_to_save[str(user_id)] = list(history)
        
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history_to_save, f)
        logging.info(f"✅ История сохранена ({len(transaction_history)} пользователей)")
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения истории: {e}")

def load_history():
    """Загружает историю транзакций из файла"""
    global transaction_history
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                loaded = json.load(f)
                # Преобразуем обратно в int ключи и deque значения
                transaction_history = {}
                for user_id, history_list in loaded.items():
                    transaction_history[int(user_id)] = deque(history_list, maxlen=20)
            logging.info(f"✅ История загружена ({len(transaction_history)} пользователей)")
        else:
            transaction_history = {}
            logging.info("📁 Файл истории не найден, создаём новый")
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки истории: {e}")
        transaction_history = {}

# <-- NEW: загрузка полученных призов
def load_prizes():
    """Загружает информацию о полученных призах"""
    global user_prizes
    try:
        if os.path.exists("user_prizes.json"):
            with open("user_prizes.json", 'r') as f:
                user_prizes = json.load(f)
                user_prizes = {int(k): v for k, v in user_prizes.items()}
            logging.info(f"✅ Призы загружены ({len(user_prizes)} пользователей)")
        else:
            user_prizes = {}
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки призов: {e}")
        user_prizes = {}

def save_prizes():
    """Сохраняет информацию о полученных призах"""
    try:
        with open("user_prizes.json", 'w') as f:
            json.dump(user_prizes, f)
        logging.info(f"✅ Призы сохранены")
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения призов: {e}")

# функция добавления транзакции в историю
def add_transaction(user_id: int, transaction_type: str, amount: int, description: str = ""):
    """Добавляет запись в историю транзакций пользователя"""
    if user_id not in transaction_history:
        transaction_history[user_id] = deque(maxlen=20)  # храним последние 20 операций
    
    transaction = {
        "timestamp": datetime.now().isoformat(),
        "type": transaction_type,  # "deposit", "game", "admin", etc.
        "amount": amount,
        "description": description
    }
    
    transaction_history[user_id].append(transaction)
    save_history()

class PhotoStates(StatesGroup):
    waiting_for_photo = State()
    waiting_for_comment = State()

class DepositStates(StatesGroup):
    waiting_for_amount = State()

# состояние для выдачи баланса по username
class AdminStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_amount = State()

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="📝 Info", callback_data="info"),
        InlineKeyboardButton(text="📷 Отправить фото", callback_data="photo"),
        InlineKeyboardButton(text="🎮 Игры", callback_data="game_menu")
    )
    builder.adjust(3)
    return builder.as_markup()

def get_game_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="🎲 Бросить кубик", callback_data="game_roll"),
        InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
        InlineKeyboardButton(text="💳 Пополнить", callback_data="deposit_menu"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
    )
    builder.adjust(2, 2)
    return builder.as_markup()

def get_deposit_methods_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="₿ CryptoBot", callback_data="deposit_cryptobot"),
        InlineKeyboardButton(text="💎 TON", callback_data="deposit_ton"),
        InlineKeyboardButton(text="₽ ЮMoney", callback_data="deposit_yoomoney"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_game_menu")
    )
    builder.adjust(2, 1)
    return builder.as_markup()

def get_deposit_amounts_keyboard(method):
    builder = InlineKeyboardBuilder()
    for amount in DEPOSIT_AMOUNTS:
        builder.add(InlineKeyboardButton(
            text=f"{amount} руб.", 
            callback_data=f"deposit_{method}_{amount}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="deposit_menu"))
    builder.adjust(2, 2)
    return builder.as_markup()

def roll_dice():
    r = random.random()
    cumulative = 0
    for number, prob in DICE_PROBABILITIES.items():
        cumulative += prob
        if r < cumulative:
            return number
    return 6

# <-- NEW: функция получения случайного приза
def get_random_prize():
    return random.choice(PRIZES)

# Функции для работы с CryptoBot
async def create_cryptobot_invoice(amount, user_id):
    """Создание счета в CryptoBot"""
    try:
        headers = {
            'Crypto-Pay-API-Token': CRYPTOBOT_API_TOKEN,
            'Content-Type': 'application/json'
        }
        # Конвертация рублей в доллары (упрощённо, курс 1 USD = 100 RUB)
        usd_amount = amount / 100
        
        data = {
            'asset': 'USDT',
            'amount': str(usd_amount),
            'description': f'Пополнение баланса на {amount} RUB',
            'payload': str(user_id)
        }
        
        response = requests.post(
            'https://pay.crypt.bot/api/createInvoice',
            headers=headers,
            json=data
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                return result['result']
    except Exception as e:
        logging.error(f"CryptoBot error: {e}")
    return None

# Функции для работы с TON
async def create_ton_invoice(amount, user_id):
    """Создание платежа в TON"""
    try:
        # TON сумма в нанотонах (1 TON = 10^9 нанотонов)
        # Курс упрощённо: 1 TON = 100 RUB
        ton_amount = amount / 100
        nano_amount = int(ton_amount * 1_000_000_000)
        
        payment_id = str(uuid.uuid4())[:8]
        comment = f"user_{user_id}_{payment_id}"
        
        # Сохраняем информацию о платеже
        pending_payments[payment_id] = {
            "user_id": user_id,
            "amount": amount,
            "method": "ton",
            "created_at": datetime.now(),
            "status": "pending",
            "comment": comment
        }
        
        # Формируем ссылку для оплаты
        transfer_url = f"ton://transfer/{TON_DEPOSIT_ADDRESS}?amount={nano_amount}&text={comment}"
        
        return {
            "url": transfer_url,
            "payment_id": payment_id,
            "comment": comment
        }
    except Exception as e:
        logging.error(f"TON error: {e}")
    return None

# Функция для работы с ЮMoney
async def create_yoomoney_invoice(amount, user_id):
    """Создание платежа в ЮMoney с комиссией за счёт плательщика"""
    if not YOOMONEY_IMPORTED:
        logging.error("Библиотека yoomoney не установлена")
        return None
        
    try:
        payment_id = str(uuid.uuid4())[:8]
        label = f"user_{user_id}_{payment_id}"
        
        # Сохраняем информацию о платеже
        pending_payments[payment_id] = {
            "user_id": user_id,
            "amount": amount,  # Сумма, которая придёт тебе
            "method": "yoomoney",
            "created_at": datetime.now(),
            "status": "pending",
            "label": label
        }
        
        # Создаём Quickpay без fee_type (библиотека его не поддерживает)
        quickpay = Quickpay(
            receiver=YOOMONEY_RECEIVER,
            quickpay_form="shop",
            targets=f"Пополнение баланса на {amount} руб.",
            paymentType="AC",  # AC - карты, PC - кошелёк ЮMoney
            sum=amount,
            label=label
        )
        
        # Добавляем fee_type к URL вручную
        base_url = quickpay.base_url
        if "?" in base_url:
            payment_url = f"{base_url}&fee_type=payer"
        else:
            payment_url = f"{base_url}?fee_type=payer"
        
        # Правильные комиссии ЮMoney:
        # При оплате картой: +2% от суммы
        # При оплате с кошелька ЮMoney: +0.5% от суммы
        card_total = amount * 1.02
        wallet_total = amount * 1.005
        
        logging.info(f"YooMoney invoice created: {payment_id} for user {user_id}, amount {amount} (fee by payer)")
        
        return {
            "url": payment_url,
            "payment_id": payment_id,
            "label": label,
            "card_total": round(card_total, 2),
            "wallet_total": round(wallet_total, 2)
        }
    except Exception as e:
        logging.error(f"YooMoney error: {e}")
        return None

# Функция проверки оплаты TON
async def check_ton_payments():
    """Проверка входящих TON транзакций (запускается в фоне)"""
    if not TON_DEPOSIT_ADDRESS or not TON_API_KEY:
        return
    
    last_lt = 0
    try:
        with open('ton_last_lt.txt', 'r') as f:
            last_lt = int(f.read())
    except:
        pass
    
    while True:
        try:
            # Запрос к TON Center API
            url = f"https://toncenter.com/api/v2/getTransactions"
            params = {
                'address': TON_DEPOSIT_ADDRESS,
                'limit': 20,
                'api_key': TON_API_KEY
            }
            
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data['ok']:
                    for tx in data['result']:
                        lt = int(tx['transaction_id']['lt'])
                        if lt <= last_lt:
                            continue
                        
                        # Проверяем входящее сообщение
                        in_msg = tx.get('in_msg', {})
                        if in_msg.get('source') and in_msg.get('value'):
                            value = int(in_msg['value'])
                            comment = in_msg.get('message', '')
                            
                            # Ищем комментарий с информацией о пользователе
                            if comment.startswith('user_'):
                                parts = comment.split('_')
                                if len(parts) >= 2:
                                    user_id = int(parts[1])
                                    payment_id = parts[2] if len(parts) > 2 else None
                                    
                                    # Начисляем баланс (конвертируем нанотоны в рубли)
                                    ton_amount = value / 1_000_000_000
                                    rub_amount = int(ton_amount * 100)  # 1 TON = 100 RUB
                                    
                                    current = user_balances.get(user_id, 0)
                                    user_balances[user_id] = current + rub_amount
                                    save_balances()
                                    
                                    # Добавляем в историю
                                    add_transaction(user_id, "deposit", rub_amount, f"Пополнение через TON")
                                    
                                    try:
                                        await bot.send_message(
                                            user_id,
                                            f"✅ Оплата через TON получена!\n"
                                            f"Зачислено: {rub_amount} руб.\n"
                                            f"Текущий баланс: {user_balances[user_id]} руб."
                                        )
                                    except:
                                        pass
                                    
                                    # Обновляем статус платежа
                                    if payment_id and payment_id in pending_payments:
                                        pending_payments[payment_id]['status'] = 'completed'
                            
                            last_lt = max(last_lt, lt)
                    
                    # Сохраняем последний обработанный lt
                    with open('ton_last_lt.txt', 'w') as f:
                        f.write(str(last_lt))
            
        except Exception as e:
            logging.error(f"TON check error: {e}")
        
        await asyncio.sleep(10)  # Проверяем каждые 10 секунд

# Функция проверки платежей ЮMoney с начислением запрошенной суммы
async def check_yoomoney_payments():
    """Проверка поступлений на кошелек ЮMoney"""
    if not YOOMONEY_TOKEN or not YOOMONEY_RECEIVER:
        logging.warning("YooMoney не настроен")
        return
    
    if not YOOMONEY_IMPORTED:
        logging.warning("Библиотека yoomoney не установлена")
        return
    
    try:
        client = Client(YOOMONEY_TOKEN)
        last_operation_id = None
        
        # Загружаем последний обработанный ID
        try:
            with open('yoomoney_last_id.txt', 'r') as f:
                last_operation_id = f.read().strip()
        except:
            pass
        
        logging.info("✅ YooMoney payment checker started")
        
        while True:
            try:
                # Получаем историю операций (последние 10)
                history = client.operation_history(records=10)
                
                for op in history.operations:
                    # Проверяем только успешные входящие платежи
                    if op.direction == 'in' and op.status == 'success':
                        # Пропускаем уже обработанные
                        if last_operation_id and op.operation_id == last_operation_id:
                            continue
                        
                        # Проверяем, есть ли метка (label) с информацией о пользователе
                        if hasattr(op, 'label') and op.label and op.label.startswith('user_'):
                            try:
                                # Разбираем метку формата: user_12345678_abc123
                                parts = op.label.split('_')
                                user_id = int(parts[1])
                                payment_id = parts[2] if len(parts) > 2 else None
                                
                                # Используем сумму из pending_payments, а не из операции
                                if payment_id and payment_id in pending_payments:
                                    payment_info = pending_payments[payment_id]
                                    amount = payment_info['amount']  # Сумма, которую хотел пользователь
                                    
                                    # Начисляем баланс
                                    current = user_balances.get(user_id, 0)
                                    user_balances[user_id] = current + amount
                                    save_balances()
                                    
                                    # Добавляем в историю
                                    add_transaction(user_id, "deposit", amount, f"Пополнение через ЮMoney")
                                    
                                    # Отмечаем платёж как выполненный
                                    pending_payments[payment_id]['status'] = 'completed'
                                    
                                    # Уведомляем пользователя
                                    try:
                                        await bot.send_message(
                                            user_id,
                                            f"✅ Оплата через ЮMoney получена!\n"
                                            f"Зачислено: {amount} руб.\n"
                                            f"Текущий баланс: {user_balances[user_id]} руб.",
                                            reply_markup=get_game_menu_keyboard()
                                        )
                                        logging.info(f"YooMoney payment for user {user_id}: {amount} RUB")
                                    except Exception as e:
                                        logging.error(f"Failed to notify user {user_id}: {e}")
                                    
                                    # Обновляем последний обработанный ID
                                    last_operation_id = op.operation_id
                                    with open('yoomoney_last_id.txt', 'w') as f:
                                        f.write(str(last_operation_id))
                                else:
                                    logging.warning(f"Payment {payment_id} not found in pending_payments")
                                    
                            except (ValueError, IndexError) as e:
                                logging.error(f"Error parsing YooMoney label: {e}")
                
            except Exception as e:
                logging.error(f"YooMoney check error: {e}")
            
            await asyncio.sleep(10)  # Проверяем каждые 10 секунд
            
    except Exception as e:
        logging.error(f"YooMoney initialization error: {e}")

# Функция проверки платежей CryptoBot
async def check_cryptobot_payments():
    """Проверка статусов платежей в CryptoBot"""
    if not CRYPTOBOT_API_TOKEN:
        return
    
    headers = {
        'Crypto-Pay-API-Token': CRYPTOBOT_API_TOKEN,
        'Content-Type': 'application/json'
    }
    
    while True:
        try:
            # Получаем все активные платежи
            response = requests.get(
                'https://pay.crypt.bot/api/getInvoices',
                headers=headers,
                params={'status': 'active'}
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    for invoice in data['result']['items']:
                        payment_id = invoice.get('invoice_id')
                        
                        # Проверяем, есть ли такой платеж в ожидающих
                        if payment_id in pending_payments:
                            # Если статус изменился на paid
                            if invoice['status'] == 'paid':
                                payment = pending_payments[payment_id]
                                user_id = payment['user_id']
                                amount = payment['amount']
                                
                                # Начисляем баланс
                                current = user_balances.get(user_id, 0)
                                user_balances[user_id] = current + amount
                                save_balances()
                                
                                # Добавляем в историю
                                add_transaction(user_id, "deposit", amount, f"Пополнение через CryptoBot")
                                
                                payment['status'] = 'completed'
                                
                                # Уведомляем пользователя
                                try:
                                    await bot.send_message(
                                        user_id,
                                        f"✅ Оплата через CryptoBot получена!\n"
                                        f"Зачислено: {amount} руб.\n"
                                        f"Текущий баланс: {user_balances[user_id]} руб."
                                    )
                                except:
                                    pass
                                
                                logging.info(f"CryptoBot payment {payment_id} completed for user {user_id}")
            
        except Exception as e:
            logging.error(f"CryptoBot check error: {e}")
        
        await asyncio.sleep(5)  # Проверяем каждые 5 секунд

# функция автосохранения
async def auto_save_balances():
    """Автоматически сохраняет балансы каждые 5 минут"""
    while True:
        await asyncio.sleep(300)  # 5 минут
        save_balances()
        save_history()
        save_prizes()
        logging.info("💾 Автосохранение выполнено")

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        f"👋 Привет, {message.from_user.full_name}!",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нет активного действия.")
        return
    await state.clear()
    await message.answer("✅ Действие отменено.", reply_markup=get_main_keyboard())

# Команда статистики для админа
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Недостаточно прав.")
        return
    
    total_users = len(user_balances)
    total_balance = sum(user_balances.values())
    total_payments = len(pending_payments)
    total_prizes = sum(len(prizes) for prizes in user_prizes.values())
    
    # Средний баланс
    avg_balance = total_balance / total_users if total_users > 0 else 0
    
    # Пользователи с положительным балансом
    active_users = sum(1 for b in user_balances.values() if b > 0)
    
    await message.answer(
        f"📊 **Статистика бота**\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💰 Общий баланс: {total_balance} руб.\n"
        f"📈 Средний баланс: {avg_balance:.2f} руб.\n"
        f"✅ Активных пользователей: {active_users}\n"
        f"💳 Ожидающих платежей: {total_payments}\n"
        f"🎁 Всего выдано призов: {total_prizes}",
        parse_mode="Markdown"
    )

# Команда истории транзакций
@dp.message(Command("history"))
async def cmd_history(message: Message):
    user_id = message.from_user.id
    
    if user_id not in transaction_history or not transaction_history[user_id]:
        await message.answer("📭 У вас пока нет операций.")
        return
    
    history_text = "📜 **Ваши последние операции:**\n\n"
    
    for tx in reversed(list(transaction_history[user_id])):
        date = datetime.fromisoformat(tx["timestamp"]).strftime("%d.%m %H:%M")
        emoji = "➕" if tx["amount"] > 0 else "➖"
        history_text += f"{emoji} {date} | {abs(tx['amount'])} руб. | {tx['description']}\n"
    
    # Добавляем информацию о призах
    if user_id in user_prizes and user_prizes[user_id]:
        history_text += f"\n🎁 **Полученные призы:** {len(user_prizes[user_id])}"
    
    await message.answer(history_text, parse_mode="Markdown")

# Команда для просмотра призов
@dp.message(Command("prizes"))
async def cmd_prizes(message: Message):
    user_id = message.from_user.id
    
    if user_id not in user_prizes or not user_prizes[user_id]:
        await message.answer("🎁 У вас пока нет полученных призов.")
        return
    
    prizes_text = "🎁 **Ваши призы:**\n\n"
    for i, prize in enumerate(user_prizes[user_id], 1):
        prizes_text += f"{i}. {prize['name']}\n"
        if 'url' in prize:
            prizes_text += f"   🔗 [Ссылка]({prize['url']})\n"
        prizes_text += f"   📝 {prize['description']}\n\n"
    
    await message.answer(prizes_text, parse_mode="Markdown")

# Админ панель для выдачи баланса
@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Недостаточно прав.")
        return
    
    await state.set_state(AdminStates.waiting_for_username)
    await message.answer(
        "👤 Введите username пользователя (без @) или его ID:\n"
        "Например: `durov` или `123456789`",
        parse_mode="Markdown"
    )

@dp.message(AdminStates.waiting_for_username)
async def admin_process_username(message: Message, state: FSMContext):
    username_or_id = message.text.strip()
    target_user_id = None
    
    # Пробуем получить ID по username
    if username_or_id.isdigit():
        target_user_id = int(username_or_id)
    else:
        try:
            # Пытаемся найти пользователя по username
            username = username_or_id if username_or_id.startswith('@') else f"@{username_or_id}"
            chat = await bot.get_chat(username)
            target_user_id = chat.id
        except Exception as e:
            await message.answer(f"❌ Пользователь {username_or_id} не найден. Проверьте username.")
            await state.clear()
            return
    
    await state.update_data(target_user_id=target_user_id)
    await state.set_state(AdminStates.waiting_for_amount)
    await message.answer("💰 Введите сумму для начисления:")

@dp.message(AdminStates.waiting_for_amount)
async def admin_process_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной.")
            return
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    
    data = await state.get_data()
    target_user_id = data['target_user_id']
    
    # Начисляем баланс
    current = user_balances.get(target_user_id, 0)
    user_balances[target_user_id] = current + amount
    save_balances()
    
    # Добавляем в историю
    add_transaction(target_user_id, "admin", amount, f"Начислено администратором")
    
    # Уведомляем пользователя
    try:
        await bot.send_message(
            target_user_id,
            f"💰 Вам начислено {amount} руб. от администратора!\n"
            f"Текущий баланс: {user_balances[target_user_id]} руб."
        )
        user_notified = "✅ Пользователь уведомлён"
    except:
        user_notified = "⚠️ Не удалось уведомить пользователя (возможно, он не писал боту)"
    
    await message.answer(
        f"✅ Баланс пользователя {target_user_id} пополнен на {amount} руб.\n"
        f"Новый баланс: {user_balances[target_user_id]} руб.\n"
        f"{user_notified}"
    )
    await state.clear()

@dp.callback_query(F.data == "info")
async def callback_info(callback: CallbackQuery):
    user = callback.from_user
    info_text = (
        f"🆔 ID: {user.id}\n"
        f"👤 Имя: {user.first_name}\n"
    )
    if user.last_name:
        info_text += f"👥 Фамилия: {user.last_name}\n"
    if user.username:
        info_text += f"📱 Username: @{user.username}\n"
    info_text += f"🌐 Язык: {user.language_code}"
    await callback.message.answer(info_text, reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "photo")
async def callback_photo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PhotoStates.waiting_for_photo)
    await callback.message.answer(
        "📸 Отправь мне фото, которое хочешь передать.\n"
        "Если передумаешь, нажми /cancel"
    )
    await callback.answer()

@dp.callback_query(F.data == "game_menu")
async def callback_game_menu(callback: CallbackQuery):
    await callback.message.answer(
        "🎮 Добро пожаловать в меню игр! Выбери действие:",
        reply_markup=get_game_menu_keyboard()
    )
    await callback.answer()

# <-- NEW: Обновлённый обработчик броска кубика с призами
@dp.callback_query(F.data == "game_roll")
async def callback_game_roll(callback: CallbackQuery):
    user_id = callback.from_user.id
    current_balance = user_balances.get(user_id, 0)

    if current_balance < DICE_COST:
        await callback.message.answer(
            f"❌ Недостаточно средств! Бросок стоит {DICE_COST} руб.\n"
            f"Твой баланс: {current_balance} руб.\n"
            "Пополни баланс через кнопку 💳 Пополнить.",
            reply_markup=get_game_menu_keyboard()
        )
        await callback.answer()
        return

    user_balances[user_id] = current_balance - DICE_COST
    save_balances()
    
    number = roll_dice()
    
    # Добавляем в историю
    add_transaction(user_id, "game", -DICE_COST, f"Бросок кубика: выпало {number}")

    # Формируем сообщение
    result_message = f"🎲 Ты бросил кубик и выпало число: {number}\n"
    result_message += f"Списано {DICE_COST} руб. Остаток: {user_balances[user_id]} руб.\n"
    
    # <-- NEW: Если выпала 6, даём приз
    if number == 6:
        prize = get_random_prize()
        
        # Сохраняем приз в историю пользователя
        if user_id not in user_prizes:
            user_prizes[user_id] = []
        user_prizes[user_id].append({
            "name": prize["name"],
            "description": prize["description"],
            "url": prize.get("url"),
            "date": datetime.now().isoformat()
        })
        save_prizes()
        
        # Добавляем в историю транзакций
        if "amount" in prize:
            add_transaction(user_id, "prize", prize["amount"], f"Приз: {prize['name']}")
        
        # Формируем сообщение о призе
        result_message += f"\n🎉 **ПОЗДРАВЛЯЕМ!** 🎉\n"
        result_message += f"Ты выиграл: **{prize['name']}**\n"
        result_message += f"📝 {prize['description']}\n"
        
        if "url" in prize:
            result_message += f"🔗 [Получить приз]({prize['url']})\n"
        if "amount" in prize:
            # Если приз - деньги, начисляем сразу
            user_balances[user_id] = user_balances.get(user_id, 0) + prize["amount"]
            save_balances()
            result_message += f"💰 {prize['amount']} руб. зачислено на баланс!\n"
    
    result_message += f"\nХочешь попробовать ещё?"
    
    await callback.message.answer(
        result_message,
        parse_mode="Markdown",
        reply_markup=get_game_menu_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "balance")
async def callback_balance(callback: CallbackQuery):
    user_id = callback.from_user.id
    balance = user_balances.get(user_id, 0)
    await callback.message.answer(
        f"💰 Твой текущий баланс: **{balance}** руб.\n\n"
        f"📜 Для просмотра истории используй /history\n"
        f"🎁 Для просмотра призов используй /prizes",
        parse_mode="Markdown",
        reply_markup=get_game_menu_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit_menu")
async def callback_deposit_menu(callback: CallbackQuery):
    await callback.message.answer(
        "💳 Выбери способ пополнения:",
        reply_markup=get_deposit_methods_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit_cryptobot")
async def callback_deposit_cryptobot(callback: CallbackQuery):
    if not CRYPTOBOT_API_TOKEN:
        await callback.message.answer(
            "❌ CryptoBot временно недоступен. Попробуй другой способ.",
            reply_markup=get_deposit_methods_keyboard()
        )
        await callback.answer()
        return
    
    await callback.message.answer(
        "💰 Выбери сумму пополнения (в рублях):",
        reply_markup=get_deposit_amounts_keyboard("cryptobot")
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit_ton")
async def callback_deposit_ton(callback: CallbackQuery):
    if not TON_DEPOSIT_ADDRESS:
        await callback.message.answer(
            "❌ TON временно недоступен. Попробуй другой способ.",
            reply_markup=get_deposit_methods_keyboard()
        )
        await callback.answer()
        return
    
    await callback.message.answer(
        "💰 Выбери сумму пополнения (в рублях):",
        reply_markup=get_deposit_amounts_keyboard("ton")
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit_yoomoney")
async def callback_deposit_yoomoney(callback: CallbackQuery):
    if not YOOMONEY_RECEIVER:
        await callback.message.answer(
            "❌ ЮMoney временно недоступен. Попробуй другой способ.",
            reply_markup=get_deposit_methods_keyboard()
        )
        await callback.answer()
        return
    
    if not YOOMONEY_IMPORTED:
        await callback.message.answer(
            "❌ Библиотека ЮMoney не установлена. Попробуй другой способ.",
            reply_markup=get_deposit_methods_keyboard()
        )
        await callback.answer()
        return
    
    await callback.message.answer(
        "💰 Выбери сумму пополнения (в рублях):",
        reply_markup=get_deposit_amounts_keyboard("yoomoney")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("deposit_cryptobot_"))
async def callback_process_cryptobot(callback: CallbackQuery):
    amount = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    invoice = await create_cryptobot_invoice(amount, user_id)
    
    if invoice:
        payment_id = invoice.get('invoice_id', str(uuid.uuid4())[:8])
        pending_payments[payment_id] = {
            "user_id": user_id,
            "amount": amount,
            "method": "cryptobot",
            "created_at": datetime.now(),
            "status": "pending"
        }
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="💳 Перейти к оплате",
            url=invoice['pay_url']
        ))
        builder.add(InlineKeyboardButton(
            text="✅ Проверить оплату",
            callback_data=f"check_payment_{payment_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="🔙 Отмена",
            callback_data="back_to_game_menu"
        ))
        builder.adjust(1)
        
        await callback.message.answer(
            f"💵 Счёт на {amount} руб. (эквивалент в USDT)\n\n"
            f"Нажми «Перейти к оплате», затем «Проверить оплату» после подтверждения.",
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.answer(
            "❌ Ошибка создания счёта. Попробуй позже.",
            reply_markup=get_deposit_methods_keyboard()
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("deposit_ton_"))
async def callback_process_ton(callback: CallbackQuery):
    amount = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    invoice = await create_ton_invoice(amount, user_id)
    
    if invoice:
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="💎 Оплатить в TON",
            url=invoice['url']
        ))
        builder.add(InlineKeyboardButton(
            text="✅ Проверить оплату",
            callback_data=f"check_payment_{invoice['payment_id']}"
        ))
        builder.add(InlineKeyboardButton(
            text="🔙 Отмена",
            callback_data="back_to_game_menu"
        ))
        builder.adjust(1)
        
        await callback.message.answer(
            f"💎 Счёт на {amount} руб. (эквивалент в TON)\n\n"
            f"Комментарий для платежа: `{invoice['comment']}`\n"
            f"Перейди по ссылке в кошельке TON для оплаты.",
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.answer(
            "❌ Ошибка создания счёта. Попробуй позже.",
            reply_markup=get_deposit_methods_keyboard()
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("deposit_yoomoney_"))
async def callback_process_yoomoney(callback: CallbackQuery):
    amount = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    invoice = await create_yoomoney_invoice(amount, user_id)
    
    if invoice:
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="💳 Перейти к оплате",
            url=invoice['url']
        ))
        builder.add(InlineKeyboardButton(
            text="✅ Проверить оплату",
            callback_data=f"check_payment_{invoice['payment_id']}"
        ))
        builder.add(InlineKeyboardButton(
            text="🔙 Отмена",
            callback_data="back_to_game_menu"
        ))
        builder.adjust(1)
        
        await callback.message.answer(
            f"₽ Счёт на **{amount} руб.** через ЮMoney\n\n"
            f"💰 Ты получишь на баланс: **{amount} руб.**\n"
            f"💳 Комиссия за счёт плательщика:\n"
            f"• При оплате картой: ~{invoice['card_total']} руб.\n"
            f"• При оплате с кошелька ЮMoney: ~{invoice['wallet_total']} руб.\n\n"
            f"1. Нажми «Перейти к оплате»\n"
            f"2. Выбери способ оплаты\n"
            f"3. После оплаты нажми «Проверить оплату»\n\n"
            f"Деньги зачислятся автоматически в течение минуты.",
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.answer(
            "❌ Ошибка создания счёта. Попробуй позже.",
            reply_markup=get_deposit_methods_keyboard()
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("check_payment_"))
async def callback_check_payment(callback: CallbackQuery):
    payment_id = callback.data.replace("check_payment_", "")
    
    if payment_id not in pending_payments:
        await callback.message.answer(
            "❌ Платёж не найден или уже обработан.",
            reply_markup=get_game_menu_keyboard()
        )
        await callback.answer()
        return
    
    payment = pending_payments[payment_id]
    
    if payment['status'] == 'completed':
        user_id = payment['user_id']
        amount = payment['amount']
        await callback.message.answer(
            f"✅ Платёж подтверждён!\n"
            f"Зачислено: {amount} руб.\n"
            f"Текущий баланс: {user_balances.get(user_id, 0)} руб.",
            reply_markup=get_game_menu_keyboard()
        )
    else:
        await callback.message.answer(
            "⏳ Платёж ещё обрабатывается.\n"
            "Деньги придут автоматически в течение минуты.",
            reply_markup=get_game_menu_keyboard()
        )
    
    await callback.answer()

@dp.callback_query(F.data == "back_to_game_menu")
async def callback_back_to_game_menu(callback: CallbackQuery):
    await callback.message.answer(
        "🔙 Возвращаемся в игровое меню.",
        reply_markup=get_game_menu_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def callback_back_to_main(callback: CallbackQuery):
    await callback.message.answer(
        "🔙 Возвращаемся в главное меню.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.message(PhotoStates.waiting_for_photo, F.photo)
async def handle_photo(message: Message, state: FSMContext):
    photo = message.photo[-1]
    await state.update_data(photo_file_id=photo.file_id, caption=message.caption)
    await state.set_state(PhotoStates.waiting_for_comment)
    await message.answer(
        "✏️ Теперь можешь добавить комментарий к фото (просто напиши текст)\n"
        "или отправь /skip, чтобы пропустить этот шаг."
    )

@dp.message(PhotoStates.waiting_for_photo)
async def handle_wrong_photo(message: Message):
    await message.answer("❌ Пожалуйста, отправь именно фото (изображение).")

@dp.message(PhotoStates.waiting_for_comment)
async def handle_comment(message: Message, state: FSMContext):
    comment = message.text
    data = await state.get_data()
    photo_file_id = data['photo_file_id']
    user = message.from_user
    user_info = f"От пользователя {user.full_name} (@{user.username})\nID: {user.id}\n"
    if comment:
        user_info += f"Комментарий: {comment}"
    await bot.send_photo(
        chat_id=OWNER_ID,
        photo=photo_file_id,
        caption=user_info
    )
    await message.answer(
        "✅ Фото успешно отправлено! Спасибо.",
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.message(PhotoStates.waiting_for_comment, Command("skip"))
async def skip_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    photo_file_id = data['photo_file_id']
    user = message.from_user
    user_info = f"От пользователя {user.full_name} (@{user.username})\nID: {user.id}\n(без комментария)"
    await bot.send_photo(
        chat_id=OWNER_ID,
        photo=photo_file_id,
        caption=user_info
    )
    await message.answer(
        "✅ Фото отправлено без комментария.",
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.message(PhotoStates.waiting_for_comment)
async def handle_wrong_comment(message: Message):
    await message.answer("❓ Пожалуйста, напиши текстовый комментарий или отправь /skip.")

@dp.message(F.photo)
async def handle_user_photo_outside(message: Message):
    await message.answer(
        "📸 Чтобы отправить фото мне, нажми кнопку «Отправить фото» ниже.",
        reply_markup=get_main_keyboard()
    )

@dp.message()
async def handle_other(message: Message):
    await message.answer(
        "❓ Я понимаю только команды с кнопок.\n"
        "Пожалуйста, воспользуйся кнопками под сообщением 👇",
        reply_markup=get_main_keyboard()
    )

@dp.errors()
async def errors_handler(event: ErrorEvent):
    logging.error(f"❌ Ошибка: {event.exception}", exc_info=True)

async def main():
    # Загружаем балансы из файла
    load_balances()
    # Загружаем историю
    load_history()
    # Загружаем призы
    load_prizes()
    
    # Запускаем автосохранение
    asyncio.create_task(auto_save_balances())
    
    # Запускаем фоновые проверки всех платёжных систем
    if TON_DEPOSIT_ADDRESS and TON_API_KEY:
        asyncio.create_task(check_ton_payments())
        logging.info("✅ TON checker started")
    
    if YOOMONEY_TOKEN and YOOMONEY_RECEIVER and YOOMONEY_IMPORTED:
        asyncio.create_task(check_yoomoney_payments())
        logging.info("✅ YooMoney checker started")
    
    if CRYPTOBOT_API_TOKEN:
        asyncio.create_task(check_cryptobot_payments())
        logging.info("✅ CryptoBot checker started")
    
    me = await bot.me()
    print(f"✅ Запущен бот: @{me.username} (ID: {me.id})")
    print(f"💰 Загружено балансов: {len(user_balances)} пользователей")
    print(f"📜 Загружено историй: {len(transaction_history)} пользователей")
    print(f"🎁 Загружено призов: {len(user_prizes)} пользователей")
    print("🚀 Бот начал polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())