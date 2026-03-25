import os
import asyncio
import logging
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from shorts_maker import make_short
from youtube_uploader import get_youtube_service, format_youtube_date, upload_video

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ ---
SHEET_NAME = "Jobhakai"
CREDENTIALS_FILE = "credentials.json"
READY_VIDEOS_DIR = "ready_videos"

async def process_jobs():
    logger.info("📊 Подключение к Google Таблице...")
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open(SHEET_NAME).sheet1
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к таблице: {e}")
        return

    try:
        logger.info("🔄 Подключение к YouTube API...")
        youtube = get_youtube_service()
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к YouTube API: {e}")
        return

    records = sheet.get_all_records()
    if not records:
        logger.info("Таблица пуста.")
        return

    for i, row in enumerate(records, start=2): # +2 т.к. первая строка - заголовки, индекс gspread начинается с 1
        status = str(row.get('Status', '')).strip().upper()
        
        if status not in ("NEW", "DONE"):
            continue

        try:
            if status == "NEW":
                post_date_str = str(row.get('Post Date', '')).strip()
                if not post_date_str:
                    logger.warning(f"[Строка {i}] Статус NEW, но нет 'Post Date', пропускаем.")
                    continue
                    
                # Парсинг даты
                dt = None
                try:
                    dt = datetime.datetime.strptime(post_date_str, "%d.%m.%Y %H:%M:%S")
                except ValueError:
                    try:
                        dt = datetime.datetime.strptime(post_date_str, "%Y-%m-%d %H:%M")
                    except ValueError:
                        pass
                
                if not dt:
                    logger.warning(f"[Строка {i}] Некорректный 'Post Date' - {post_date_str}")
                    continue
                    
                # 3. Если время пришло или прошло
                if datetime.datetime.now() >= dt:
                    logger.info(f"[Строка {i}] Время {dt} пришло. Меняем статус на PROCESSING.")
                    sheet.update_cell(i, 5, "PROCESSING") # В колонку Status (E)
                    
                    # Извлекаем параметры для создания видео
                    screen_title = row.get('Screen title', row.get('Screen_title', ''))
                    script = row.get('Script', '')
                    
                    os.makedirs(READY_VIDEOS_DIR, exist_ok=True)
                    filename = f"{READY_VIDEOS_DIR}/video_{i}.mp4"
                    
                    logger.info(f"[Строка {i}] Начинаем создание видео (shorts_maker.py)...")
                    # Вызов создания видео
                    await make_short(script, screen_title, output_filename=filename)
                    logger.info(f"[Строка {i}] Видео успешно создано: {filename}")
                    
                    # Сохраняем путь к видео: допустим, в колонку G (7). Пользователь не указал конкретную колонку,
                    # поэтому мы просто сохраняем в локальную память и обновляем базовые вещи
                    try:
                        sheet.update_cell(i, 7, filename) # Используем колонку G
                    except Exception as e:
                        logger.warning(f"Не удалось записать путь к видео в колонку G: {e}")

                    # Смена на DONE 
                    sheet.update_cell(i, 5, "DONE")
                    logger.info(f"[Строка {i}] Статус изменен на DONE.")
                    
                    # Обновляем локальный статус в словаре, чтобы сразу ПЕРЕЙТИ к шагу загрузки (4)
                    status = "DONE"
                    row['Status'] = 'DONE'
                else:
                    logger.info(f"[Строка {i}] Время для 'NEW' ещё не пришло: {dt}.")
                    continue

            if status == "DONE":
                yt_title = row.get('YT Title', 'JobHack AI Shorts')
                yt_desc = row.get('YT Description', '#shorts #jobhackai')
                post_date_str = str(row.get('Post Date', '')).strip()
                
                # Используем форматирование из youtube_uploader
                iso_date = format_youtube_date(post_date_str)
                
                # Путь к видео (берём либо из G, либо стандартизированный)
                filename = f"{READY_VIDEOS_DIR}/video_{i}.mp4"
                
                logger.info(f"[Строка {i}] Начинаем загрузку видео {filename} на YouTube...")
                
                # Вызов функции загрузки
                video_id = upload_video(youtube, filename, yt_title, yt_desc, iso_date)
                
                logger.info(f"[Строка {i}] Видео успешно загружено на YouTube! ID: {video_id}")
                
                # При успехе смени статус на SCHEDULED
                sheet.update_cell(i, 5, "SCHEDULED")
                logger.info(f"[Строка {i}] Статус изменен на SCHEDULED.")
                
        except Exception as e:
            logger.error(f"[Строка {i}] ❌ Возникла ошибка: {e}", exc_info=False)
            logger.error(f"[Строка {i}] ❌ Подробности:", exc_info=True)
            try:
                sheet.update_cell(i, 5, "ERROR")
            except Exception as update_err:
                logger.error(f"Не удалось выставить статус ERROR на строке {i}: {update_err}")

async def main():
    while True:
        logger.info("🔄 Запуск цикла проверки задач (Диспетчер autoposter.py)...")
        await process_jobs()
        logger.info("⏳ Ожидание перед следующей проверкой (60 сек)...")
        await asyncio.sleep(60)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Автопостер остановлен вручную.")