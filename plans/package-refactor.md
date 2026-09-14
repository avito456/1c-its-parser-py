# План: преобразование проекта в пакет `its_parser`

## Целевая структура каталогов

```
1c-its-parser-py/
├── src/
│   └── its_parser/
│       ├── __init__.py          # версия, публичный API
│       ├── __main__.py          # python -m its_parser
│       ├── models.py            # DocPage (строки 29-39)
│       ├── browser.py           # настройка Chrome, авторизация (строки 1500-1561)
│       ├── parser.py            # extract_doc_structure — дерево + извлечение (строки 106-703)
│       ├── downloader.py        # download_image, save_iframe_content, save_all_pages (строки 41-1100)
│       ├── html.py              # генерация CSS/HTML оглавления, постобработка (строки 705-939, 1245-1444)
│       ├── cli.py               # argparse + main() (строки 1446-1564)
│       └── logging_setup.py     # setup_logging (перенос из корня)
├── pyproject.toml               # обновлённый: [build-system], [project.scripts]
├── uv.lock
├── README.md
├── LICENSE
├── .env.example
├── .gitignore
└── plans/
    └── loguru-migration.md
```

## Старые файлы для удаления после миграции

- `main.py`
- `logging_setup.py` (из корня)

---

## Разбиение `main.py` по модулям

| Модуль | Функции/классы из `main.py` | Строки |
|--------|-----------------------------|--------|
| `models.py` | `DocPage` | 29–39 |
| `parser.py` | `extract_doc_structure()` | 106–703 |
| `downloader.py` | `download_image()`, `save_all_pages()`, `save_iframe_content()`, `clean_output_directory()` | 41–104, 941–1243 |
| `html.py` | `_generate_html_styles()`, `_generate_toc_entry()`, `post_process_html()`, `clean_img_tags()`, `simplify_image_paths()`, константа `IMG_TAG_PATTERN` | 15, 705–939, 1245–1444 |
| `browser.py` | Настройка `ChromeOptions`, блок авторизации | 1500–1545 (из `main()`) |
| `cli.py` | `main()`, argparse, оркестрация | 1446–1564 |
| `logging_setup.py` | `setup_logging()` | без изменений |

---

## Обновление `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "its-parser"
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

[project.scripts]
its-parser = "its_parser.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/its_parser"]
```

---

## Порядок выполнения

1. Создать `src/its_parser/`
2. Создать `__init__.py` (версия `__version__ = "0.1.0"`)
3. Создать `__main__.py` (`from its_parser.cli import main; main()`)
4. Перенести `logging_setup.py` → `src/its_parser/logging_setup.py`
5. Создать `models.py` (вынести `DocPage`)
6. Создать `html.py` (вынести CSS-генерацию, TOC-генерацию, постобработку HTML)
7. Создать `downloader.py` (вынести `download_image`, `save_iframe_content`, `save_all_pages`, `clean_output_directory`)
8. Создать `parser.py` (вынести `extract_doc_structure`)
9. Создать `browser.py` (вынести настройку Chrome и блок авторизации из `main()`)
10. Создать `cli.py` (argparse + оркестрация в `main()`)
11. Обновить `pyproject.toml`
12. Удалить `main.py` и корневой `logging_setup.py`
13. Проверить: `uv sync` и запуск `python -m its_parser --help`
