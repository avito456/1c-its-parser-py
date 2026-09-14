from __future__ import annotations

import os
import re
import shutil
import time
import urllib.parse
from typing import List, Optional

import requests
from loguru import logger
from selenium import webdriver
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchFrameException

from its_parser.html import generate_index_html, post_process_html, simplify_image_paths
from its_parser.models import DocPage


def download_image(browser: WebDriver, img_element: WebElement, save_dir: str) -> Optional[str]:
    """Скачивает изображение и заменяет путь в HTML"""
    try:
        src = img_element.get_attribute('src')
        if not src:
            return None

        # Получаем абсолютный URL изображения
        if src.startswith('/db/'):
            base_url = "https://its.1c.ru"
            src = f"{base_url}{src}"
        elif src.startswith('/'):
            base_url = urllib.parse.urlparse(browser.current_url).netloc
            src = f"https://{base_url}{src}"
        elif not src.startswith('http'):
            current_path = urllib.parse.urlparse(browser.current_url).path
            base_path = os.path.dirname(current_path)
            src = f"https://its.1c.ru{base_path}/{src}"

        # Загружаем изображение
        logger.debug("Скачиваем изображение: {src}", src=src)

        os.makedirs(save_dir, exist_ok=True)

        # Определяем расширение файла из URL
        url_path = urllib.parse.urlparse(src).path
        file_ext = os.path.splitext(url_path)[1]
        if not file_ext:
            file_ext = '.png'  # По умолчанию используем png

        # Создаем имя файла на основе счетчика изображений в папке
        existing_images = len([f for f in os.listdir(save_dir) if f.endswith(file_ext)])
        new_filename = f"image{existing_images+1:03d}{file_ext}"

        # Путь для сохранения файла
        save_path = os.path.join(save_dir, new_filename)

        cookies = {}
        for cookie in browser.get_cookies():
            cookies[cookie['name']] = cookie['value']

        headers = {
            'Referer': browser.current_url,
        }

        response = requests.get(
            src,
            cookies=cookies,
            headers=headers,
            allow_redirects=True
        )

        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            logger.debug("Сохранено изображение: {path}", path=save_path)
            return new_filename
        else:
            logger.debug("Ошибка скачивания {src}: статус {code}", src=src, code=response.status_code)
            logger.debug("Заголовки ответа: {headers}", headers=dict(response.headers))

    except Exception as e:
        logger.error("Ошибка скачивания изображения {src}: {e}", src=src, e=e)
    return None


def save_iframe_content(browser, iframe_id, output_dir='out'):
    """Сохраняем содержимое iframe"""
    try:
        WebDriverWait(browser, 15).until(
            EC.frame_to_be_available_and_switch_to_it((By.ID, iframe_id))
        )
        logger.debug("Переключились в iframe")

        try:
            WebDriverWait(browser, 15).until(
                lambda x: x.execute_script("return document.readyState") == "complete"
            )
            logger.debug("readyState iframe complete")

            images_dir = os.path.join(output_dir, 'images')
            os.makedirs(images_dir, exist_ok=True)

            images = browser.find_elements(By.TAG_NAME, "img")
            logger.debug("Найдено изображений: {n}", n=len(images))

            # Словарь для отслеживания уже скачанных изображений
            processed_images = {}

            for img in images:
                src = img.get_attribute('src')
                logger.debug("Обрабатываем изображение: {src}", src=src)

                # Если такой URL уже обрабатывался, используем существующий путь
                if src in processed_images:
                    new_src = processed_images[src]
                    img_path = f"images/{new_src}"
                    logger.debug("Используем существующий путь: {path}", path=img_path)
                else:
                    # Загружаем новое изображение
                    new_src = download_image(browser, img, images_dir)
                    if new_src:
                        img_path = f"images/{new_src}"
                        processed_images[src] = new_src
                        logger.debug("Обновляем путь на: {path}", path=img_path)
                    else:
                        logger.warning("Не удалось скачать изображение: {src}", src=src)
                        continue

                # Обновляем путь в HTML
                browser.execute_script("""
                    arguments[0].setAttribute('src', arguments[1]);
                    if (arguments[0].hasAttribute('data-src')) {
                        arguments[0].setAttribute('data-src', arguments[1]);
                    }
                    // Удаляем классы, которые могут мешать отображению
                    arguments[0].classList.remove('incomplete');
                    // Удаляем лишние стили, оставляя только размеры
                    var style = arguments[0].getAttribute('style');
                    if (style) {
                        var sizeStyles = [];
                        if (style.includes('width')) {
                            sizeStyles.push('width: ' + arguments[0].width + 'px');
                        }
                        if (style.includes('height')) {
                            sizeStyles.push('height: ' + arguments[0].height + 'px');
                        }
                        if (sizeStyles.length > 0) {
                            arguments[0].setAttribute('style', sizeStyles.join('; '));
                        } else {
                            arguments[0].removeAttribute('style');
                        }
                    }
                """, img, img_path)

            # Получаем обновленный HTML-код
            iframe_content = browser.page_source

            # Регулярное выражение для поиска тегов img с атрибутами width и height
            img_pattern = re.compile(r'<img[^>]*src="images/([^"]+)"[^>]*width="([^"]+)"[^>]*height="([^"]+)"[^>]*>')

            # Находим все совпадения и заменяем на упрощенный тег
            for match in img_pattern.finditer(iframe_content):
                src, width, height = match.groups()
                old_tag = match.group(0)
                new_tag = f'<img src="images/{src}" width="{width}" height="{height}" alt="">'
                iframe_content = iframe_content.replace(old_tag, new_tag)

            # Заменяем все оставшиеся сложные пути для изображений
            iframe_content = re.sub(
                r'src="[^"]*?/([^/"]+\.(png|jpg|gif|jpeg))"',
                r'src="images/\1"',
                iframe_content
            )

            # Обновляем или добавляем мета-тег с UTF-8
            if '<meta charset=' not in iframe_content and '<meta http-equiv="Content-Type"' not in iframe_content:
                iframe_content = re.sub(
                    r'<head[^>]*>',
                    r'<head>\n    <meta charset="utf-8">',
                    iframe_content
                )
            else:
                # Обновляем существующий мета-тег
                iframe_content = re.sub(
                    r'<meta[^>]*charset=[^>]*>',
                    r'<meta charset="utf-8">',
                    iframe_content
                )
                iframe_content = re.sub(
                    r'<meta[^>]*Content-Type[^>]*>',
                    r'<meta charset="utf-8">',
                    iframe_content
                )

            # Сохраняем содержимое в файл в UTF-8
            output_file = os.path.join(output_dir, 'page.html')
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(iframe_content)
            logger.debug("Содержимое iframe сохранено в {file}", file=output_file)

            # Выполняем постобработку HTML для исправления путей к изображениям
            if post_process_html(output_file):
                logger.debug("Постобработка HTML для {file}", file=output_file)

        finally:
            browser.switch_to.default_content()
            logger.debug("Вернулись к основному документу")

    except TimeoutException as e:
        logger.error("Таймаут при ожидании iframe")
        logger.exception("Детали таймаута iframe")
        raise
    except NoSuchFrameException as e:
        logger.error("Не удалось переключиться на iframe")
        logger.exception("Детали ошибки переключения iframe")
        raise
    except Exception as e:
        logger.error("Ошибка при обработке iframe")
        logger.exception("Детали обработки iframe")
        raise


def save_all_pages(browser: webdriver.WebDriver, pages: List[DocPage], limit: int = None) -> None:
    """Сохраняет все страницы документации"""
    if limit is not None:
        pages = pages[:limit]
        logger.info("Ограничение: будет сохранено {n} страниц", n=len(pages))

    # Создаем оглавление в HTML
    generate_index_html(pages)

    # Сохраняем страницы
    total = len(pages)
    for i, page in enumerate(pages, 1):
        try:
            logger.info("Обработка: {i}/{total} — {title}", i=i, total=total, title=page.title)
            logger.debug("  Level={level}, URL={url}", level=page.level, url=page.url)

            page_dir = os.path.join('out', f"page_{i:04d}")
            os.makedirs(page_dir, exist_ok=True)

            with open(os.path.join(page_dir, 'metadata.txt'), 'w', encoding='utf-8') as f:
                f.write(f"Title: {page.title}\n")
                f.write(f"Level: {page.level}\n")
                f.write(f"URL: {page.url}\n")

            browser.get(page.url)
            time.sleep(3)
            save_iframe_content(browser, "w_metadata_doc_frame", output_dir=page_dir)

            # Упрощаем пути к изображениям
            if simplify_image_paths(page_dir):
                logger.debug("Упрощены пути к изображениям: {title}", title=page.title)

        except Exception as e:
            logger.error("Ошибка при сохранении страницы: {title}", title=page.title)
            logger.exception("Детали ошибки сохранения страницы")


def clean_output_directory(directory='out'):
    """Очищает каталог вывода, если он существует"""
    if os.path.exists(directory):
        logger.info("Очистка каталога {dir}", dir=directory)
        shutil.rmtree(directory)
    os.makedirs(directory, exist_ok=True)