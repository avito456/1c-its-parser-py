from __future__ import annotations

import os
import re
import shutil
from typing import List

from loguru import logger

from its_parser.models import DocPage

IMG_TAG_PATTERN = r'<img[^>]*?src="([^"]+)"[^>]*?>'


def _generate_html_styles() -> str:
    """Возвращает CSS стили для оглавления"""
    return """
        body { 
            font-family: Arial, sans-serif; 
            margin: 20px;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        /* Отображать метаданные всегда, если включен режим */
        body.show-metadata .metadata {
            display: block !important;
            position: static !important;
            margin-left: 20px !important;
            box-shadow: none !important;
            border: none !important;
            background: transparent !important;
            padding: 2px 0 !important;
            font-size: 0.8em !important;
            color: #777 !important;
        }
        body.show-metadata .toc-entry:hover .metadata {
            background: transparent !important;
        }
        .controls {
            margin: 15px 0;
            padding: 10px;
            background: #f8f8f8;
            border-radius: 5px;
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
        }
        .toc { 
            margin-left: 20px; 
            max-width: 100%;
            overflow-x: hidden;
        }
        .toc-entry { 
            margin: 8px 0;
            position: relative;  /* Для позиционирования метаданных */
            padding: 3px 5px;    /* Небольшие отступы для лучшего вида при наведении */
            overflow: hidden;    /* Обрезаем выходящий контент */
            border-radius: 4px;
        }
        /* Контейнер для строки с заголовком и кнопками */
        .entry-row {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        /* Контейнер для действий (кнопок) */
        .actions {
            display: flex;
            align-items: center;
            gap: 4px;
            opacity: 0.2;
            transition: opacity 0.2s;
        }
        .toc-entry:hover .actions {
            opacity: 1;
        }
        /* Кнопка открытия оригинальной страницы */
        .original-link {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 24px;
            height: 24px;
            color: #666;
            border-radius: 4px;
            transition: all 0.2s;
        }
        .original-link:hover {
            background-color: rgba(0, 119, 204, 0.1);
            color: #0077cc;
        }
        .original-link svg {
            width: 14px;
            height: 14px;
        }
        /* Подсветка строки при наведении */
        .toc-entry:hover {
            background-color: rgba(0, 0, 0, 0.03);
        }
        .title {
            color: #2156a5;
            text-decoration: none;
            font-size: 1.1em;
            display: block;      /* Блочный элемент для стабильного отображения */
            word-wrap: break-word; /* Перенос длинных слов */
            overflow-wrap: break-word;
            max-width: 100%;    /* Ограничиваем ширину */
            width: fit-content;  /* По содержимому */
            overflow: hidden;    /* Прячем вышедший за границы текст */
        }
        /* Ссылка на оригинальный URL */
        .url-link {
            color: #0077cc;
            text-decoration: none;
            word-break: break-all;
        }
        .url-link:hover {
            text-decoration: underline;
            color: #0055aa;
        }
        /* Класс для очень длинных заголовков */
        .title.truncated {
            white-space: nowrap;
            text-overflow: ellipsis;
        }
        .title:hover { 
            text-decoration: underline;
        }
        .level-0 { 
            margin: 20px 0 10px 0; 
            font-size: 1.2em; 
            font-weight: bold;
            border-bottom: 1px solid #eee;
            padding-bottom: 5px;
        }
        .metadata {
            font-size: 0.85em;
            color: #666;
            position: absolute;
            background: #f5f5f5;
            border: 1px solid #ddd;
            padding: 5px 10px;
            border-radius: 4px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            z-index: 10;
            display: none;
            top: calc(100% + 5px); /* Отступ от элемента */
            left: 20px;
            min-width: 200px;
            max-width: 600px;
            white-space: nowrap; /* Предотвращаем перенос текста внутри метаданных */
        }
        /* Слегка затемняем метаданные при постоянном отображении */
        body.show-metadata .metadata {
            opacity: 0.8;
        }
        body.show-metadata .toc-entry:hover .metadata {
            opacity: 1;
        }
        .toc-entry:hover .metadata { display: block; }
        .section {
            margin: 20px 0;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 5px;
        }
        .section-title {
            font-size: 1.3em;
            color: #333;
            margin-bottom: 10px;
            padding: 8px;
            border-bottom: 1px solid #ddd;
            border-radius: 4px;
            background-color: #f4f4f4;
        }
        button {
            padding: 8px 15px;
            background-color: #4285f4;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s ease;
        }
        button:hover {
            background-color: #3367d6;
        }
        /* Активное состояние кнопки */
        button.active {
            background-color: #1c3aa9;
            box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.2);
            position: relative;
        }
        button.active::after {
            content: '✓';
            position: absolute;
            right: 8px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 12px;
        }
        /* Адаптивные стили для маленьких экранов */
        @media (max-width: 768px) {
            .controls {
                flex-direction: column;
            }
            .controls button {
                width: 100%;
                margin: 2px 0;
                text-align: left;
                padding-left: 15px;
            }
            .toc {
                margin-left: 10px;
            }
            .metadata {
                max-width: 90%;
            }
        }
    """


def _generate_toc_entry(page: DocPage, index: int) -> str:
    """Генерирует HTML для одного элемента оглавления"""
    # Добавляем больше отступов для корректного отображения уровней
    indentation = page.level * 30  # 30px на каждый уровень вложенности

    return f"""
        <div class="toc-entry level-{page.level}" style="margin-left: {indentation}px;">
            <div class="entry-row">
                <a class="title" href="page_{index:04d}/page.html" title="{page.title}">{page.title}</a>
                <div class="actions">
                    <a href="{page.url}" target="_blank" class="original-link" title="Открыть оригинальную страницу">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <line x1="10" y1="14" x2="21" y2="3"></line>
                        </svg>
                    </a>
                </div>
            </div>
            <div class="metadata">
                <div><strong>URL:</strong> <a href="{page.url}" target="_blank" class="url-link">{page.url}</a></div>
                <div><strong>Уровень:</strong> {page.level}</div>
                <div><strong>Номер:</strong> {page.number}</div>
            </div>
        </div>"""


def build_toc_html(pages: List[DocPage]) -> str:
    """Создает HTML оглавления документации"""
    toc_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Оглавление документации</title>
    <style>{_generate_html_styles()}</style>
</head>
<body>
    <h1>Оглавление документации</h1>
    
    <div class="controls">
        <button data-level="1" class="level-filter">Показать только уровень 1</button>
        <button data-level="2" class="level-filter">Показать до уровня 2</button>
        <button data-level="3" class="level-filter">Показать до уровня 3</button>
        <button data-level="10" class="level-filter active">Показать все уровни</button>
        <button id="toggle-metadata">Показать/скрыть метаданные</button>
    </div>
    
    <div class="toc">
"""

    # Группируем страницы по основным разделам (уровень 0)
    current_level0 = None
    for i, page in enumerate(pages, 1):
        if page.level == 0:
            if current_level0 is not None:
                toc_html += "    </div>\n</div>\n"

            section_id = f"section_{i}"
            toc_html += f'<div class="section" id="{section_id}">\n'
            toc_html += f'    <div class="section-title">{page.title}</div>\n'
            toc_html += '    <div class="section-content">\n'
            current_level0 = page.title

        toc_html += _generate_toc_entry(page, i)

    if current_level0 is not None:
        toc_html += "    </div>\n</div>\n"

    toc_html += """
    </div>
    
    <script>
    // Переключение уровней с сохранением активного состояния
    document.querySelectorAll('.level-filter').forEach(button => {
        button.addEventListener('click', function() {
            const maxLevel = parseInt(this.getAttribute('data-level'));
            
            // Снимаем активное состояние со всех кнопок
            document.querySelectorAll('.level-filter').forEach(btn => {
                btn.classList.remove('active');
            });
            
            // Добавляем активное состояние текущей кнопке
            this.classList.add('active');
            
            // Показываем/скрываем элементы в зависимости от их уровня
            for (let i = 0; i <= 10; i++) {
                const elements = document.querySelectorAll('.level-' + i);
                
                for (let elem of elements) {
                    if (i <= maxLevel) {
                        elem.style.display = 'block';
                    } else {
                        elem.style.display = 'none';
                    }
                }
            }
            
            // Сохраняем выбор в localStorage
            localStorage.setItem('selectedLevel', maxLevel);
        });
    });
    
    // Переключение метаданных
    document.getElementById('toggle-metadata').addEventListener('click', function() {
        const body = document.body;
        const isActive = body.classList.contains('show-metadata');
        
        if (isActive) {
            body.classList.remove('show-metadata');
            this.classList.remove('active');
            localStorage.setItem('showMetadata', 'false');
        } else {
            body.classList.add('show-metadata');
            this.classList.add('active');
            localStorage.setItem('showMetadata', 'true');
        }
    });
    
    // При загрузке страницы
    document.addEventListener('DOMContentLoaded', function() {
        // Восстанавливаем выбранный уровень из localStorage
        const savedLevel = localStorage.getItem('selectedLevel');
        if (savedLevel) {
            const levelButton = document.querySelector(`.level-filter[data-level="${savedLevel}"]`);
            if (levelButton) {
                levelButton.click();
            }
        }
        
        // Восстанавливаем состояние отображения метаданных
        const showMetadata = localStorage.getItem('showMetadata');
        if (showMetadata === 'true') {
            document.getElementById('toggle-metadata').click();
        }
        
        // Инициализация тултипов для длинных названий
        const titles = document.querySelectorAll('.title');
        titles.forEach(title => {
            // Если текст слишком длинный, добавляем эллипсис
            if (title.offsetWidth < title.scrollWidth) {
                title.classList.add('truncated');
            }
        });
    });
    </script>
</body>
</html>"""

    return toc_html


def post_process_html(html_file_path):
    """Постобработка HTML файла для исправления путей к изображениям"""
    try:
        with open(html_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Регулярное выражение для поиска всех тегов img
        img_tag_pattern = re.compile(IMG_TAG_PATTERN)

        # Ищем все теги img
        for match in img_tag_pattern.finditer(content):
            full_img_tag = match.group(0)
            src = match.group(1)

            # Проверяем, требуется ли коррекция пути
            if 'images/' not in src and ('/' in src or '%' in src or 'http' in src):
                # Извлекаем имя файла из сложного пути
                filename = src.split('/')[-1]
                # Заменяем сложный путь на простой
                new_src = f"images/{filename}"
                new_img_tag = full_img_tag.replace(src, new_src)
                content = content.replace(full_img_tag, new_img_tag)

        # Упрощаем все теги img
        content = re.sub(
            r'<img[^>]*?src="images/([^"]+)"[^>]*?width="([^"]*)"[^>]*?height="([^"]*)"[^>]*?>',
            r'<img src="images/\1" width="\2" height="\3" alt="">',
            content
        )

        # Убираем атрибуты, которые могут мешать отображению
        content = re.sub(
            r'<img([^>]*?)class="[^"]*?incomplete[^"]*?"([^>]*?)>',
            r'<img\1\2>',
            content
        )

        # Заменяем все URL-закодированные пути
        encoded_path_pattern = re.compile(r'images/[^"]*?%[^"]*?\.(?:png|jpg|gif|jpeg)')

        # Находим все закодированные пути
        for match in encoded_path_pattern.finditer(content):
            encoded_path = match.group(0)
            # Формируем новый путь с порядковым номером
            new_path = f"images/image{len(set(encoded_path_pattern.findall(content)))}.png"
            content = content.replace(encoded_path, new_path)

        # Заменяем ссылки на файлы в подкаталогах на прямые ссылки
        content = re.sub(
            r'images/[^"]+?/([^/"]+\.(?:png|jpg|gif|jpeg))',
            r'images/\1',
            content
        )

        # Сохраняем обработанный файл
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return True
    except Exception as e:
        logger.error("Ошибка при постобработке HTML: {e}", e=e)
        return False


def clean_img_tags(html_content):
    """Очищает теги img от ненужных атрибутов, оставляя только src, width, height и alt"""
    # Регулярное выражение для поиска тегов img
    img_pattern = re.compile(IMG_TAG_PATTERN)

    # Словарь для хранения замен
    replacements = {}

    # Обрабатываем каждый найденный тег img
    for match in img_pattern.finditer(html_content):
        full_tag = match.group(0)
        src = match.group(1)

        # Если тег уже обработан, пропускаем
        if full_tag in replacements:
            continue

        # Получаем значения width и height, если они есть
        width_match = re.search(r'width="([^"]+)"', full_tag)
        width = width_match.group(1) if width_match else ""

        height_match = re.search(r'height="([^"]+)"', full_tag)
        height = height_match.group(1) if height_match else ""

        # Создаем новый чистый тег
        if width and height:
            new_tag = f'<img src="{src}" width="{width}" height="{height}" alt="">'
        elif width:
            new_tag = f'<img src="{src}" width="{width}" alt="">'
        elif height:
            new_tag = f'<img src="{src}" height="{height}" alt="">'
        else:
            new_tag = f'<img src="{src}" alt="">'

        replacements[full_tag] = new_tag

    # Применяем все замены
    for old_tag, new_tag in replacements.items():
        html_content = html_content.replace(old_tag, new_tag)

    return html_content


def simplify_image_paths(page_dir):
    """Копирует все изображения из сложных путей в простую директорию изображений"""
    try:
        # Находим все подкаталоги с изображениями
        images_dir = os.path.join(page_dir, 'images')
        if not os.path.exists(images_dir):
            return False

        # Создаем простой каталог для изображений, если его нет
        simple_images_dir = os.path.join(page_dir, 'img')
        os.makedirs(simple_images_dir, exist_ok=True)

        # Счетчик изображений
        image_counter = 1

        # Словарь для отслеживания соответствий между старыми и новыми путями к файлам
        path_mapping = {}

        # Проходим по всем файлам в images и подкаталогах
        for root, dirs, files in os.walk(images_dir):
            for file in files:
                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    # Полный путь к исходному файлу
                    src_path = os.path.join(root, file)

                    # Получаем относительный путь от корня images
                    rel_path = os.path.relpath(src_path, images_dir)

                    # Определяем расширение файла
                    _, ext = os.path.splitext(file)

                    # Новое имя файла в формате imageNNN.ext
                    new_filename = f"image{image_counter:03d}{ext}"
                    dst_path = os.path.join(simple_images_dir, new_filename)

                    # Копируем файл
                    shutil.copy2(src_path, dst_path)

                    # Сохраняем соответствие путей
                    path_mapping[rel_path] = new_filename

                    logger.debug("Скопирован файл {src} -> {dst}", src=rel_path, dst=new_filename)

                    image_counter += 1

        # Обновляем HTML-файл, чтобы использовать новые пути
        html_file = os.path.join(page_dir, 'page.html')
        if os.path.exists(html_file):
            with open(html_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Получаем все ссылки на изображения в HTML
            img_tags = re.findall(r'<img[^>]*?src="([^"]+)"[^>]*?>', content)

            # Словарь для новых соответствий путей
            new_paths = {}

            # Обрабатываем каждую ссылку
            for src in img_tags:
                if src.startswith('images/'):
                    # Удаляем префикс images/
                    rel_path = src[7:]

                    # Если есть соответствие в path_mapping, используем его
                    if rel_path in path_mapping:
                        new_paths[src] = f"img/{path_mapping[rel_path]}"
                    else:
                        # Попробуем найти подходящий файл по имени
                        filename = os.path.basename(rel_path)
                        for old_path, new_name in path_mapping.items():
                            if os.path.basename(old_path) == filename:
                                new_paths[src] = f"img/{new_name}"
                                break
                        else:
                            # Если не нашли, просто копируем с порядковым номером
                            new_name = f"image{len(new_paths)+1:03d}{os.path.splitext(filename)[1]}"
                            new_paths[src] = f"img/{new_name}"

            # Заменяем пути в HTML
            for old_path, new_path in new_paths.items():
                content = content.replace(f'src="{old_path}"', f'src="{new_path}"')

            # Очищаем теги img от ненужных атрибутов
            content = clean_img_tags(content)

            # Сохраняем обновленный HTML
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.debug("Обновлён HTML-файл {file}", file=html_file)

        return True
    except Exception as e:
        logger.error("Ошибка при упрощении путей к изображениям: {e}", e=e)
        return False


def generate_index_html(pages: List[DocPage], output_dir: str) -> None:
    """Сохраняет оглавление документации в файл index.html"""
    toc_html = build_toc_html(pages)
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(toc_html)