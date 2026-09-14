from __future__ import annotations

import os
import time

from dotenv import load_dotenv
from loguru import logger

from its_parser.browser import create_browser, login
from its_parser.downloader import clean_output_directory, save_all_pages
from its_parser.logging_setup import setup_logging
from its_parser.parser import extract_doc_structure

load_dotenv()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="""
Парсер документации 1С ИТС - инструмент для локального сохранения документации.

Примеры запуска:
  Простой запуск:
    its-parser --url https://its.1c.ru/db/edtdoc --login https://login.1c.ru/login
  
  С авторизацией через командную строку:
    its-parser --url https://its.1c.ru/db/edtdoc --login https://login.1c.ru/login --username user --password pass
  
  С ограничением количества страниц и запуском в фоновом режиме:
    its-parser --url https://its.1c.ru/db/edtdoc --login https://login.1c.ru/login --limit 20 --headless
  
  С расширенным выводом для отладки:
    its-parser --url https://its.1c.ru/db/edtdoc --login https://login.1c.ru/login --log-level DEBUG
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--url', required=True, help='URL документации для загрузки (например, https://its.1c.ru/db/edtdoc)')
    parser.add_argument('--login', required=True, help='URL страницы авторизации (например, https://login.1c.ru/login)')
    parser.add_argument('--username', required=False, help='Имя пользователя (если не указано, берется из .env файла)')
    parser.add_argument('--password', required=False, help='Пароль пользователя (если не указано, берется из .env файла)')
    parser.add_argument('--limit', type=int, help='Ограничение количества страниц для загрузки (по умолчанию - все страницы)')
    parser.add_argument('--headless', action='store_true', help='Запуск браузера в фоновом режиме без отображения окна')
    parser.add_argument('--log-level', default=os.environ.get('LOG_LEVEL', 'INFO'),
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Уровень логирования в stdout (по умолчанию: INFO)')
    parser.add_argument('--log-file', default=os.environ.get('LOG_FILE'),
                        help='Путь к файлу логов (если указан, логирование в файл включается)')
    parser.add_argument('--log-file-level', default=os.environ.get('LOG_FILE_LEVEL', 'DEBUG'),
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Уровень логирования в файл (по умолчанию: DEBUG)')
    args = parser.parse_args()

    setup_logging(
        stdout_level=args.log_level,
        log_file=args.log_file,
        log_file_level=args.log_file_level,
    )

    # Использование переменных окружения, если не указаны аргументы
    if not args.username:
        args.username = os.environ.get('USERNAME')
    if not args.password:
        args.password = os.environ.get('PASSWORD')

    # Проверка наличия учетных данных
    if not args.username or not args.password:
        raise ValueError("Необходимо указать username и password в аргументах или в файле .env")

    clean_output_directory()

    browser = create_browser(headless=args.headless)

    try:
        login(browser, args.login, args.username, args.password)

        logger.info("Загрузка документации...")
        browser.get(args.url)
        time.sleep(2)

        pages = extract_doc_structure(browser)

        if args.limit:
            logger.info("Сохранение {n} страниц...", n=args.limit)
        else:
            logger.info("Сохранение всех страниц...")

        save_all_pages(browser, pages, args.limit)
        logger.info("Готово!")

    except Exception as e:
        logger.error("Ошибка при выполнении")
        logger.exception("Детали ошибки: {url}", url=browser.current_url)
    finally:
        browser.quit()