import os
import json
import time
import shutil
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from send2trash import send2trash  # Импортируем библиотеку для удаления в корзину

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("organizer.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def get_default_downloads_dir():
    """Автоматически находит стандартную папку Загрузок для любой ОС"""
    home = Path.home()
    possible_names = ["Downloads", "Загрузки"]
    for name in possible_names:
        fallback_path = os.path.join(home, name)
        if os.path.exists(fallback_path):
            return fallback_path
    return os.path.join(home, "Downloads")

# Загрузка конфигурации
try:
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    logging.error("Файл config.json не найден!")
    exit(1)

WATCH_DIR = os.path.abspath(config['watch_directory']) if config['watch_directory'] else get_default_downloads_dir()
RULES = config['rules']
DELETE_OLD = config.get('delete_old_files', False)
MAX_AGE_DAYS = config.get('max_file_age_days', 30)

def clean_old_files(watch_dir, rules, max_age_days):
    """Находит и удаляет файлы в корзину, если они старше max_age_days"""
    logging.info(f"Проверка старых файлов (ограничение: {max_age_days} дней)...")
    now = time.time()
    cutoff = now - (max_age_days * 86400) # 86400 секунд в сутках
    
    # Проверяем только папки категорий, которые создал наш органайзер
    for folder_name in rules.keys():
        folder_path = os.path.join(watch_dir, folder_name)
        if not os.path.exists(folder_path):
            continue
            
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            
            # Проверяем только файлы (папки внутри категорий не трогаем)
            if os.path.isfile(item_path):
                # Получаем время последнего изменения файла
                file_modified_time = os.path.getmtime(item_path)
                
                if file_modified_time < cutoff:
                    try:
                        send2trash(item_path)
                        logging.info(f"🗑️ Старый файл отправлен в корзину: {folder_name}/{item}")
                    except Exception as e:
                        logging.error(f"Не удалось удалить {item}: {e}")

def move_file(file_path, watch_dir, rules):
    """Общая функция для перемещения одного файла по правилам"""
    if not os.path.exists(file_path) or os.path.isdir(file_path):
        return

    filename = os.path.basename(file_path)
    _, extension = os.path.splitext(filename)
    extension = extension.lower()

    if extension in ['.crdownload', '.tmp', '.part', '.download']:
        return

    moved = False
    for folder_name, extensions in rules.items():
        if extension in extensions:
            target_dir = os.path.join(watch_dir, folder_name)
            os.makedirs(target_dir, exist_ok=True)
            
            target_path = os.path.join(target_dir, filename)
            
            if os.path.exists(target_path):
                name, ext = os.path.splitext(filename)
                target_path = os.path.join(target_dir, f"{name}_{int(time.time())}{ext}")

            try:
                shutil.move(file_path, target_path)
                logging.info(f"Перемещен: {filename} -> {folder_name}/")
                moved = True
            except Exception as e:
                logging.error(f"Ошибка перемещения {filename}: {e}")
            break

    if not moved:
        others_dir = os.path.join(watch_dir, "Others")
        os.makedirs(others_dir, exist_ok=True)
        try:
            shutil.move(file_path, os.path.join(others_dir, filename))
            logging.info(f"Перемещен в неизвестные: {filename} -> Others/")
        except Exception as e:
            logging.error(f"Ошибка перемещения {filename} в Others: {e}")

def initial_clean(watch_dir, rules):
    """Сканирует корневую папку Загрузок перед стартом трекера"""
    logging.info("Запуск первичной сортировки новых файлов...")
    for item in os.listdir(watch_dir):
        item_path = os.path.join(watch_dir, item)
        if os.path.isfile(item_path):
            move_file(item_path, watch_dir, rules)
    logging.info("Первичная сортировка завершена.")

class DownloadHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        time.sleep(1)
        move_file(event.src_path, WATCH_DIR, RULES)

if __name__ == "__main__":
    if not os.path.exists(WATCH_DIR):
        logging.error(f"Указанная папка не существует: {WATCH_DIR}")
        exit(1)

    logging.info(f"Отслеживаемая папка: {WATCH_DIR}")
    
    # 1. Сначала сортируем новые файлы в корне
    initial_clean(WATCH_DIR, RULES)
    
    # 2. Затем очищаем старые файлы в подпапках, если функция включена
    if DELETE_OLD:
        clean_old_files(WATCH_DIR, RULES, MAX_AGE_DAYS)

    # 3. Запускаем постоянный мониторинг
    event_handler = DownloadHandler()
    observer = Observer()
    observer.schedule(event_handler, path=WATCH_DIR, recursive=False)
    
    logging.info("🚀 Скрипт запущен и следит за новыми файлами... (Ctrl+C для выхода)")
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("⏹️ Скрипт успешно остановлен.")
    observer.join()

