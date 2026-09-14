# План: замена print() на loguru

## 1. Новый файл `logging_setup.py`

```python
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Union

from loguru import logger


def setup_logging(
    stdout_level: str = "INFO",
    log_file: Optional[Union[str, Path]] = None,
    log_file_level: str = "DEBUG",
) -> None:
    """Настраивает loguru: отдельный sink для stdout и опциональный sink для файла."""
    logger.remove()

    logger.add(
        sys.stderr,
        level=stdout_level.upper(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            str(log_path),
            level=log_file_level.upper(),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} — {message}",
            rotation="10 MB",
            retention="10 days",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
        )
```

---

## 2. Изменения в `pyproject.toml`

```toml
[project]
name = "1c-its-parser"
version = "0.1.0"
description = "Парсер документации 1С ИТС"
requires-python = ">=3.9"
dependencies = [
    "requests==2.28.2",
    "selenium>=4.0.0",
    "python-dotenv>=0.19.0",
    "urllib3>=1.26.0",
    "loguru>=0.7.0",
]
```

---

## 3. Изменения в `.env.example`

```
USERNAME=your_username
PASSWORD=your_password
LOG_LEVEL=INFO
LOG_FILE=
LOG_FILE_LEVEL=DEBUG
```

---

## 4. Добавление в `.gitignore`

```
logs/
```

---

## 5. Изменения в `main.py`

### 5.1. Новый импорт (после `from dotenv import load_dotenv`)

```python
from loguru import logger
from logging_setup import setup_logging
```

### 5.2. CLI-аргументы (в `main()`, после существующих `add_argument`)

```python
parser.add_argument('--log-level', default=os.environ.get('LOG_LEVEL', 'INFO'),
                    choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                    help='Уровень логирования в stdout (по умолчанию: INFO)')
parser.add_argument('--log-file', default=os.environ.get('LOG_FILE'),
                    help='Путь к файлу логов (если указан, логирование в файл включается)')
parser.add_argument('--log-file-level', default=os.environ.get('LOG_FILE_LEVEL', 'DEBUG'),
                    choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                    help='Уровень логирования в файл (по умолчанию: DEBUG)')
```

### 5.3. Вызов `setup_logging()` (в `main()`, сразу после `args = parser.parse_args()`)

```python
args = parser.parse_args()
setup_logging(
    stdout_level=args.log_level,
    log_file=args.log_file,
    log_file_level=args.log_file_level,
)
```

### 5.4. Аргумент `--verbose` — УДАЛЯЕТСЯ

Блоки `if args.verbose: print(...)` заменяются на `logger.debug(...)`. Вся логика управления видимостью отладочного вывода делегируется уровню логирования (`--log-level DEBUG` вместо `--verbose`).

### 5.5. Удаление `global args` в `main()`

Строка `global args` (1492) удаляется — `args` более не используется глобально.

### 5.6. Замена глобального `args` в функциях

Все функции, которые обращаются к глобальному `args`, получают нужные параметры аргументами:

| Функция | Глобальные обращения | Решение |
|---------|----------------------|---------|
| `download_image` | `args.verbose` → удаляется | Параметры не нужны |
| `extract_doc_structure` | `args.verbose` (47 мест) → все заменяются на `logger.*` | Параметры не нужны |
| `save_all_pages` | `args.verbose` | Параметры не нужны |
| `save_iframe_content` | `args.verbose` | Параметры не нужны |
| `post_process_html` | `args.headless` (line 1346) | Заменяется на `logger.error` безусловно |
| `simplify_image_paths` | `args.verbose` | Параметры не нужны |

### 5.7. Полная карта замены `print()` → `logger.*`

| Строка | Было | Стало |
|--------|------|-------|
| **59-60** | `if args.verbose: print(f"Скачиваем изображение: {src}")` | `logger.debug("Скачиваем изображение: {src}", src=src)` |
| **95-96** | `if args.verbose: print(f"Сохранено изображение: {save_path}")` | `logger.debug("Сохранено изображение: {path}", path=save_path)` |
| **99-101** | `if args.verbose: print(f"Ошибка при скачивании {src}: статус {response.status_code}"); print(f"Заголовки ответа: {response.headers}")` | `logger.debug("Ошибка скачивания {src}: статус {code}", src=src, code=response.status_code); logger.debug("Заголовки ответа: {headers}", headers=dict(response.headers))` |
| **104-105** | `if args.verbose: print(f"Ошибка при скачивании изображения {src}: {str(e)}")` | `logger.error("Ошибка скачивания изображения {src}: {e}", src=src, e=e)` |
| **110** | `print("Извлекаем структуру документации...")` | `logger.info("Извлекаем структуру документации...")` |
| **227-228** | `if collapsed_nodes > 0 and args.verbose: print(f"Внимание: после разворачивания остались свернутые узлы ({collapsed_nodes})")` | `if collapsed_nodes > 0: logger.warning("После разворачивания остались свернутые узлы: {n}", n=collapsed_nodes)` |
| **257-258** | `if collapsed_nodes > 0 and args.verbose: print(f"Всё еще остались свернутые узлы: {collapsed_nodes}")` | `if collapsed_nodes > 0: logger.warning("Всё ещё остались свернутые узлы: {n}", n=collapsed_nodes)` |
| **384-385** | `if js_results and len(js_results) > 0 and args.verbose: print(f"JavaScript метод нашел {len(js_results)} ссылок")` | `if js_results: logger.debug("JavaScript метод нашёл {n} ссылок", n=len(js_results))` |
| **408-409** | `if args.verbose: print(f"Добавлена страница через JS: {page}")` | `logger.debug("Добавлена страница через JS: {page}", page=page)` |
| **411-412** | `if args.verbose: print(f"Ошибка при обработке JS результата: {str(e)}")` | `logger.error("Ошибка при обработке JS результата: {e}", e=e)` |
| **415-416** | `if args.verbose: print(f"Ошибка при JavaScript обходе дерева: {str(e)}")` | `logger.error("Ошибка при JavaScript обходе дерева: {e}", e=e)` |
| **420-421** | `if args.verbose: print("JavaScript метод не дал результатов, используем стандартный обход")` | `logger.debug("JavaScript метод не дал результатов, используем стандартный обход")` |
| **453-454** | `if args.verbose: print("Развернут элемент через JavaScript")` | `logger.debug("Развернут элемент через JavaScript")` |
| **456-457** | `if args.verbose: print(f"Не удалось развернуть элемент через JavaScript: {str(e)}")` | `logger.warning("Не удалось развернуть элемент через JavaScript: {e}", e=e)` |
| **467-468** | `if args.verbose: print("Развернут элемент через клик")` | `logger.debug("Развернут элемент через клик")` |
| **470-471** | `if args.verbose: print(f"Не удалось развернуть элемент: {str(e2)}")` | `logger.warning("Не удалось развернуть элемент: {e}", e=e2)` |
| **492-493** | `if args.verbose: print("Пропущен элемент без ссылки или заголовка")` | `logger.debug("Пропущен элемент без ссылки или заголовка")` |
| **505-506** | `if args.verbose: print(f"Добавлена страница: {page}")` | `logger.debug("Добавлена страница: {page}", page=page)` |
| **519-520** | `if args.verbose: print(f"Ошибка при обработке элемента: {str(e)}")` | `logger.error("Ошибка при обработке элемента: {e}", e=e)` |
| **529-530** | `if args.verbose: print("Стандартный обход дал мало результатов, пробуем JavaScript метод")` | `logger.debug("Стандартный обход дал мало результатов, пробуем JavaScript метод")` |
| **605-606** | `if ... and args.verbose: print(f"JavaScript извлек {len(js_results)} ссылок")` | `logger.debug("JavaScript извлёк {n} ссылок", n=len(js_results))` |
| **633-634** | `if args.verbose: print(f"Обработка ссылок, найдено уровней от {min_level} до {max_level}")` | `logger.debug("Обработка ссылок, уровней от {min} до {max}", min=min_level, max=max_level)` |
| **673-677** | `if args.verbose: print(f"Добавлена страница через JavaScript: {page} {debug_info}")` | `logger.debug("Добавлена страница через JavaScript: {page} {info}", page=page, info=debug_info)` |
| **679-680** | `if args.verbose: print(f"Ошибка при обработке JS результата: {str(e)}")` | `logger.error("Ошибка при обработке JS результата: {e}", e=e)` |
| **682-683** | `if args.verbose: print(f"Ошибка при JavaScript извлечении ссылок: {str(e)}")` | `logger.error("Ошибка при JavaScript извлечении ссылок: {e}", e=e)` |
| **685-688** | `if args.verbose: print("\nСтруктура документации:"); for page in pages: print(...)` | `logger.debug("Структура документации:"); [logger.debug("  {number} {title}", number=page.number, title=page.title) for page in pages]` |
| **691** | `print("Внимание: не найдено ни одной страницы в дереве")` | `logger.warning("Не найдено ни одной страницы в дереве")` |
| **692-694** | `if args.verbose: print("Содержимое дерева:"); print(tree.get_attribute('innerHTML'))` | `logger.debug("Содержимое дерева: {html}", html=tree.get_attribute('innerHTML'))` |
| **698** | `print("Пробуем получить хотя бы какие-то ссылки со страницы...")` | `logger.info("Пробуем получить ссылки напрямую со страницы...")` |
| **718** | `print(f"Удалось получить {len(pages)} ссылок напрямую со страницы")` | `logger.info("Удалось получить {n} ссылок напрямую со страницы", n=len(pages))` |
| **720-721** | `if args.verbose: print(f"Не удалось получить ссылки напрямую: {str(e)}")` | `logger.error("Не удалось получить ссылки напрямую: {e}", e=e)` |
| **723** | `print(f"Найдено {len(pages)} страниц")` | `logger.info("Найдено {n} страниц", n=len(pages))` |
| **967** | `print(f"Ограничение: будет сохранено {len(pages)} страниц")` | `logger.info("Ограничение: будет сохранено {n} страниц", n=len(pages))` |
| **1100-1106** | `if args.verbose: print(...) else: print(...)` | `logger.info("Обработка: {i}/{total} — {title}", i=i, total=total, title=page.title); logger.debug("  Level={level}, URL={url}", level=page.level, url=page.url)` |
| **1122-1123** | `if args.verbose: print(f"Упрощены пути к изображениям для страницы {page.title}")` | `logger.debug("Упрощены пути к изображениям: {title}", title=page.title)` |
| **1126** | `print(f"Ошибка при сохранении страницы {page.title}")` | `logger.error("Ошибка при сохранении страницы: {title}", title=page.title)` |
| **1127-1128** | `if args.verbose: print(f"Детали: {str(e)}")` | `logger.exception("Детали ошибки сохранения страницы")` |
| **1137-1138** | `if args.verbose: print("Переключились в iframe")` | `logger.debug("Переключились в iframe")` |
| **1144-1145** | `if args.verbose: print("readyState iframe complete")` | `logger.debug("readyState iframe complete")` |
| **1151-1152** | `if args.verbose: print(f"Найдено изображений: {len(images)}")` | `logger.debug("Найдено изображений: {n}", n=len(images))` |
| **1159-1160** | `if args.verbose: print(f"Обрабатываем изображение: {src}")` | `logger.debug("Обрабатываем изображение: {src}", src=src)` |
| **1166-1167** | `if args.verbose: print(f"Используем существующий путь: {img_path}")` | `logger.debug("Используем существующий путь: {path}", path=img_path)` |
| **1174-1175** | `if args.verbose: print(f"Обновляем путь на: {img_path}")` | `logger.debug("Обновляем путь на: {path}", path=img_path)` |
| **1176-1177** | `elif args.verbose: print(f"Не удалось скачать изображение: {src}")` | `logger.warning("Не удалось скачать изображение: {src}", src=src)` |
| **1250-1251** | `if args.verbose: print(f"Содержимое iframe сохранено в {output_file}")` | `logger.debug("Содержимое iframe сохранено в {file}", file=output_file)` |
| **1255-1256** | `if args.verbose: print(f"Выполнена постобработка HTML для {output_file}")` | `logger.debug("Постобработка HTML для {file}", file=output_file)` |
| **1260-1261** | `if args.verbose: print("Вернулись к основному документу")` | `logger.debug("Вернулись к основному документу")` |
| **1264** | `print("Ошибка: таймаут при ожидании iframe")` | `logger.error("Таймаут при ожидании iframe")` |
| **1265-1266** | `if args.verbose: print(f"Детали: {str(e)}")` | `logger.exception("Детали таймаута iframe")` |
| **1269** | `print("Ошибка: не удалось переключиться на iframe")` | `logger.error("Не удалось переключиться на iframe")` |
| **1270-1271** | `if args.verbose: print(f"Детали: {str(e)}")` | `logger.exception("Детали ошибки переключения iframe")` |
| **1274** | `print("Ошибка при обработке iframe")` | `logger.error("Ошибка при обработке iframe")` |
| **1275-1276** | `if args.verbose: print(f"Детали: {str(e)}")` | `logger.exception("Детали обработки iframe")` |
| **1282** | `print(f"Очистка каталога {directory}")` | `logger.info("Очистка каталога {dir}", dir=directory)` |
| **1346-1347** | `if not args.headless: print(f"Ошибка при постобработке HTML: {str(e)}")` | `logger.error("Ошибка при постобработке HTML: {e}", e=e)` |
| **1433-1434** | `if args.verbose: print(f"Скопирован файл {rel_path} -> {new_filename}")` | `logger.debug("Скопирован файл {src} -> {dst}", src=rel_path, dst=new_filename)` |
| **1482-1483** | `if args.verbose: print(f"Обновлен HTML-файл {html_file}")` | `logger.debug("Обновлён HTML-файл {file}", file=html_file)` |
| **1487-1488** | `if args.verbose: print(f"Ошибка при упрощении путей к изображениям: {str(e)}")` | `logger.error("Ошибка при упрощении путей к изображениям: {e}", e=e)` |
| **1561** | `print("Авторизация...")` | `logger.info("Авторизация...")` |
| **1577** | `print("Загрузка документации...")` | `logger.info("Загрузка документации...")` |
| **1584** | `print(f"Сохранение {args.limit} страниц...")` | `logger.info("Сохранение {n} страниц...", n=args.limit)` |
| **1586** | `print("Сохранение всех страниц...")` | `logger.info("Сохранение всех страниц...")` |
| **1589** | `print("Готово!")` | `logger.info("Готово!")` |
| **1592** | `print("Ошибка при выполнении")` | `logger.error("Ошибка при выполнении")` |
| **1593-1595** | `if args.verbose: print(f"Детали: {str(e)}"); print("URL в момент ошибки:", browser.current_url)` | `logger.exception("Детали ошибки: {url}", url=browser.current_url)` |

### 5.8. Удаление `--verbose` из argparse

Удалить строку:
```python
parser.add_argument('--verbose', action='store_true', help='Включить расширенный вывод для отладки')
```

---

## 6. Итого: что меняется

| Файл | Действие |
|------|----------|
| `logging_setup.py` | Создаётся — новый файл |
| `main.py` | Модифицируется: +импорт, +3 CLI-аргумента, `setup_logging()` вызов, удаление `--verbose`, удаление `global args`, 73 замены `print()` → `logger.*`, 47 удалений `if args.verbose:` |
| `pyproject.toml` | Добавляется `loguru>=0.7.0` в dependencies |
| `.env.example` | Добавляются `LOG_LEVEL`, `LOG_FILE`, `LOG_FILE_LEVEL` |
| `.gitignore` | Добавляется `logs/` |
