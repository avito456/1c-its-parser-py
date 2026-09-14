# Результат: преобразование проекта в пакет `its_parser`

## Структура каталогов

```
src/its_parser/
├── __init__.py        # 5 строк
├── __main__.py        # 4 строки
├── models.py          # 17 строк
├── logging_setup.py   # 43 строки
├── browser.py         # 56 строк
├── html.py            # 358 строк
├── parser.py          # 521 строк
├── downloader.py      # 241 строка
└── cli.py             # 85 строк
```

**Итого: ~1330 строк** (было 1564 + 43 = 1607).

## Назначение модулей

| Модуль | Назначение |
|--------|-----------|
| `models.py` | `DocPage` — модель данных |
| `browser.py` | `create_browser()`, `login()` — Chrome + авторизация |
| `parser.py` | `extract_doc_structure()` — дерево документации |
| `downloader.py` | `download_image()`, `save_all_pages()`, `save_iframe_content()`, `clean_output_directory()` |
| `html.py` | CSS/HTML генерация оглавления, постобработка HTML |
| `cli.py` | argparse + оркестрация |
| `logging_setup.py` | `setup_logging()` |

## Запуск

- `uv run its-parser --url ... --login ...`
- `uv run python -m its_parser --url ... --login ...`
