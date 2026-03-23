import os, asyncio, logging, httpx
from datetime import datetime
from dotenv import load_dotenv
from openai import AsyncOpenAI
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка
load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_KEY = os.getenv("AI_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()

ai_client = AsyncOpenAI(api_key=OPENAI_KEY, timeout=60.0)

SEARCH_QUERY = "Маркетолог удаленка"
VACANCIES_COUNT = 3

PROMPT = """
Ты — дерзкий и полезный автор Telegram-канала JobHack AI. Твоя задача — сделать сочную подборку горячих вакансий из предоставленного списка.

ПРАВИЛА:
1. Начни с цепляющей подводки (например: "Хватит отправлять резюме в черную дыру. Вот свежий топ вакансий на удаленке:").
2. Оформи список вакансий: название сделай кликабельным (ссылкой), обязательно укажи компанию и зарплату (если есть).
3. Текст должен быть коротким, без лишней воды и корпоративного булшита.
4. ЗАПРЕЩЕНО использовать слово "нейросеть". Пиши "наш ИИ-бот" или "JobHack AI".
5. ЗАПРЕЩЕНО использовать Markdown-заголовки (символы #). Только жирный шрифт (**) для акцентов.
6. В самом конце ОБЯЗАТЕЛЬНО добавь этот призыв к действию отдельным абзацем:
"🤖 Чтобы JobHack AI написал пробивное сопроводительное письмо под любую из этих вакансий за 10 секунд — просто отправь ее в нашего бота: @JobHackAI"
"""

async def get_vacancies():
    async with httpx.AsyncClient() as client:
        params = {"text": SEARCH_QUERY, "per_page": VACANCIES_COUNT, "order_by": "publication_time"}
        res = await client.get("https://api.hh.ru/vacancies", params=params, headers={"User-Agent": "JobHackAI/1.0"})
        return res.json().get('items', [])

async def generate_post(vacancies):
    raw_data = ""
    for v in vacancies:
        salary_data = v.get('salary')
        if salary_data:
            sal_from = salary_data.get('from')
            sal_to = salary_data.get('to')
            currency = salary_data.get('currency', 'руб.')
            if sal_from and sal_to:
                sal_text = f"от {sal_from} до {sal_to} {currency}"
            elif sal_from:
                sal_text = f"от {sal_from} {currency}"
            elif sal_to:
                sal_text = f"до {sal_to} {currency}"
            else:
                sal_text = "ЗП по итогам собеседования"
        else:
            sal_text = "ЗП не указана"
            
        raw_data += f"Вакансия: {v['name']} | Компания: {v.get('employer', {}).get('name')} | ЗП: {sal_text} | Ссылка: {v['alternate_url']}\n"

    res = await ai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": raw_data}]
    )
    return res.choices[0].message.content

async def posting_job():
    """Эта функция будет вызываться по расписанию"""
    logger.info(f"⏰ Запуск задачи постинга... Время: {datetime.now()}")
    
    vacs = await get_vacancies()
    if not vacs:
        logger.warning("Нет новых вакансий.")
        return

    post_text = await generate_post(vacs)
    
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=post_text, parse_mode="Markdown", disable_web_page_preview=True)
        logger.info("✅ Пост успешно опубликован по расписанию!")
    except Exception as e:
        logger.error(f"❌ Ошибка публикации: {e}")
    finally:
        await bot.session.close()

async def main():
    if not CHANNEL_ID:
        logger.error("❌ Добавь CHANNEL_ID в .env файл!")
        return

    # Настраиваем планировщик
    scheduler = AsyncIOScheduler()
    
    # 📌 НАСТРОЙКА ВРЕМЕНИ ПОСТОВ (по локальному времени сервера/компьютера)
    # Сейчас стоит: каждый день в 10:00 и в 16:00
    scheduler.add_job(posting_job, 'cron', hour=10, minute=0)
    scheduler.add_job(posting_job, 'cron', hour=16, minute=0)
    
    scheduler.start()
    logger.info("🕒 Автопостер запущен в фоновом режиме. Жду времени по расписанию...")
    
    # Бесконечный цикл, чтобы скрипт жил
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Автопостер остановлен вручную.")