import json
import logging
import time
import shutil
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import send2trash

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("organizer.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def get_default_downloads_dir() -> Path:
    """Автоматически находит стандартную папку Загрузок для любой ОС"""
    home = Path.home()
    for name in ["Downloads", "Загрузки"]:
        fallback_path = home / name
        if fallback_path.exists():
            return fallback_path
    return home / "Downloads"

# Загрузка конфигурации
try:
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    logging.error("Файл config.json не найден!")
    exit(1)

WATCH_DIR = Path(config['watch_directory']) if config['watch_directory'] else get_default_downloads_dir()
RULES = config['rules']
DELETE_OLD = config.get('delete_old_files', False)
MAX_AGE_DAYS = config.get('max_file_age_days', 30)

# ОПТИМИЗАЦИЯ: Перестраиваем структуру правил для мгновенного поиска O(1) вместо O(N)
# Было: {'Documents': ['.pdf', '.docx']} -> Стало: {'.pdf': 'Documents', '.docx': 'Documents'}
EXTENSION_MAP = {ext.lower(): folder for folder, exts in RULES.items() for ext in exts}
IGNORED_EXTENSIONS = {'.crdownload', '.tmp', '.part', '.download'}

def clean_old_files(watch_dir: Path, rules: dict, max_age_days: int):
    """Находит и удаляет файлы в корзину, если они старше max_age_days"""
    logging.info(f"Проверка старых файлов (ограничение: {max_age_days} дней)...")
    cutoff = time.time() - (max_age_days * 86400)
    
    # Проверяем только папки категорий из правил
    for folder_name in rules.keys():
        folder_path = watch_dir / folder_name
        if not folder_path.exists():
            continue
            
        # Папку "Others" проверяем отдельно
        for item in folder_path.iterdir():
            if item.is_file() and item.stat().st_mtime < cutoff:
                try:
                    send2trash.send2trash(str(item))
                    logging.info(f"🗑️ Старый файл отправлен в корзину: {folder_name}/{item.name}")
                except Exception as e:
                    logging.error(f"Не удалось удалить {item.name}: {e}")

def wait_for_file_release(file_path: Path, timeout: int = 10) -> bool:
    """Ожидает окончания записи файла, если он большой или еще качается"""
    last_size = -1
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            if not file_path.exists():
                return False
            current_size = file_path.stat().st_size
            if current_size == last_size and current_size > 0:
                return True  # Файл перестал расти, запись окончена
            last_size = current_size
        except OSError:
            pass
        time.sleep(0.5)
    return False

def move_file(file_path: Path, watch_dir: Path):
    """Перемещение одного файла по оптимизированным правилам"""
    if not file_path.exists() or file_path.is_dir():
        return

    ext = file_path.suffix.lower()
    if ext in IGNORED_EXTENSIONS:
        return

    # Ждем завершения загрузки файла
    if not wait_for_file_release(file_path):
        return

    # Мгновенно определяем целевую папку по словарю
    target_folder = EXTENSION_MAP.get(ext, "Others")
    target_dir = watch_dir / target_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    
    target_path = target_dir / file_path.name
    
    # Обработка дубликатов имен
    if target_path.exists():
        target_path = target_dir / f"{file_path.stem}_{int(time.time())}{ext}"

    try:
        shutil.move(str(file_path), str(target_path))
        logging.info(f"Перемещен: {file_path.name} -> {target_folder}/")
    except Exception as e:
        logging.error(f"Ошибка перемещения {file_path.name}: {e}")

def initial_clean(watch_dir: Path):
    """Сканирует корневую папку Загрузок перед стартом трекера"""
    logging.info("Запуск первичной сортировки новых файлов...")
    for item in watch_dir.iterdir():
        if item.is_file():
            move_file(item, watch_dir)
    logging.info("Первичная сортировка завершена.")

class DownloadHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        # Передаем объект Path вместо строки
        move_file(Path(event.src_path), WATCH_DIR)


if __name__ == "__main__":
    if not WATCH_DIR.exists():
        logging.error(f"Указанная папка не существует: {WATCH_DIR}")
        exit(1)

    logging.info(f"Отслеживаемая папка: {WATCH_DIR}")
    
    initial_clean(WATCH_DIR)
    
    if DELETE_OLD:
        clean_old_files(WATCH_DIR, RULES, MAX_AGE_DAYS)

    event_handler = DownloadHandler()
    observer = Observer()
    observer.schedule(event_handler, path=str(WATCH_DIR), recursive=False)
    
    logging.info("🚀 Скрипт запущен... (Ctrl+C для выхода)")
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("⏹️ Скрипт успешно остановлен.")
    observer.join()
