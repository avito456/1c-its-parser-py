from __future__ import annotations

import re
import time
from typing import List

from loguru import logger
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from its_parser.models import DocPage


def extract_doc_structure(browser: WebDriver) -> List[DocPage]:
    """Извлекает структуру документации из оглавления"""
    logger.info("Извлекаем структуру документации...")

    # Ждем загрузки дерева
    tree = WebDriverWait(browser, 15).until(
        EC.presence_of_element_located((By.CLASS_NAME, "tree"))
    )

    # Разворачиваем все узлы дерева
    browser.execute_script("""
        function expandAllManually(element) {
            // Находим все свернутые узлы
            const collapsedNodes = element.querySelectorAll('.collapsed');
            console.log('Найдено свернутых узлов:', collapsedNodes.length);
            
            let changed = 0;
            
            // Вместо клика просто изменяем классы напрямую
            for (let i = 0; i < collapsedNodes.length; i++) {
                try {
                    const node = collapsedNodes[i];
                    
                    // Прокручиваем к узлу для уверенности
                    node.scrollIntoView({behavior: 'auto', block: 'center'});
                    
                    // Непосредственное изменение классов
                    node.classList.remove('collapsed');
                    node.classList.add('expanded');
                    
                    // Делаем дочерние элементы видимыми
                    const childUls = node.querySelectorAll('ul');
                    childUls.forEach(ul => {
                        ul.style.display = 'block';
                        ul.style.visibility = 'visible';
                    });
                    
                    changed++;
                } catch (e) {
                    console.error('Ошибка при развертывании узла:', e);
                }
            }
            
            console.log('Изменено узлов:', changed);
            return changed;
        }
        
        function waitAndExpandManually() {
            const tree = document.querySelector('.tree');
            if (!tree) {
                console.error('Дерево не найдено!');
                return;
            }
            
            // Подготовка дерева - делаем все элементы видимыми
            // Сначала убираем ограничения высоты
            tree.style.maxHeight = 'none';
            tree.style.overflow = 'visible';
            
            let attempts = 0;
            
            // Запускаем функцию разворачивания каждые 500мс
            let interval = setInterval(() => {
                const count = expandAllManually(tree);
                console.log('Попытка', attempts, 'изменено:', count);
                attempts++;
                
                // Продолжаем до 15 попыток или пока не останется свернутых узлов
                if (count === 0 || attempts >= 15) {
                    clearInterval(interval);
                    
                    // Финальный проход по всем элементам дерева
                    // Показываем все ul элементы
                    const allULs = tree.querySelectorAll('ul');
                    allULs.forEach(ul => {
                        ul.style.display = 'block';
                        ul.style.visibility = 'visible';
                    });
                    
                    // Показываем все li элементы
                    const allLIs = tree.querySelectorAll('li');
                    allLIs.forEach(li => {
                        li.style.visibility = 'visible';
                        li.style.display = 'block';
                        
                        // Иногда в li есть скрытые div с контентом
                        const divs = li.querySelectorAll('div');
                        divs.forEach(div => {
                            div.style.display = 'block';
                            div.style.visibility = 'visible';
                        });
                    });
                    
                    // Удаляем все обработчики событий на кнопках expand
                    // (чтобы предотвратить случайное сворачивание)
                    const expandButtons = tree.querySelectorAll('.expand');
                    expandButtons.forEach(button => {
                        const clone = button.cloneNode(true);
                        if (button.parentNode) {
                            button.parentNode.replaceChild(clone, button);
                        }
                    });
                    
                    console.log('Финальная обработка дерева завершена');
                }
            }, 500);
        }
        
        waitAndExpandManually();
    """)

    # Увеличиваем время ожидания для разворачивания сложного дерева
    time.sleep(10)

    # Проверяем, что дерево правильно развернуто
    collapsed_nodes = browser.execute_script("""
        return document.querySelectorAll('.tree .collapsed').length;
    """)

    if collapsed_nodes > 0:
        logger.warning("После разворачивания остались свернутые узлы: {n}", n=collapsed_nodes)

        # Принудительно разворачиваем оставшиеся узлы через DOM-манипуляции
        browser.execute_script("""
            // Принудительно разворачиваем все оставшиеся узлы
            document.querySelectorAll('.tree .collapsed').forEach(node => {
                node.classList.remove('collapsed');
                node.classList.add('expanded');
                
                // Показываем все подэлементы
                const childElements = node.querySelectorAll('*');
                childElements.forEach(el => {
                    el.style.display = 'block';
                    el.style.visibility = 'visible';
                });
            });
            
            // Также находим все скрытые ul и показываем их
            document.querySelectorAll('.tree ul[style*="display: none"]').forEach(ul => {
                ul.style.display = 'block';
                ul.style.visibility = 'visible';
            });
        """)
        time.sleep(3)

        # Проверяем снова
        collapsed_nodes = browser.execute_script("""
            return document.querySelectorAll('.tree .collapsed').length;
        """)
        if collapsed_nodes > 0:
            logger.warning("Всё ещё остались свернутые узлы: {n}", n=collapsed_nodes)

            # Если узлы все еще свернуты, используем глубокое преобразование HTML
            browser.execute_script("""
                // Создаем глубокую копию дерева
                const tree = document.querySelector('.tree');
                if (tree) {
                    // Рекурсивно разворачиваем все узлы через модификацию DOM
                    function unfoldRecursive(element) {
                        // Разворачиваем текущий элемент
                        if (element.classList && element.classList.contains('collapsed')) {
                            element.classList.remove('collapsed');
                            element.classList.add('expanded');
                        }
                        
                        // Делаем элемент видимым
                        element.style.display = 'block';
                        element.style.visibility = 'visible';
                        
                        // Рекурсивно обрабатываем дочерние элементы
                        for (let i = 0; i < element.children.length; i++) {
                            unfoldRecursive(element.children[i]);
                        }
                    }
                    
                    // Запускаем рекурсивную обработку дерева
                    unfoldRecursive(tree);
                }
            """)
            time.sleep(2)

    pages: List[DocPage] = []
    processed_urls = set()
    current_section = [0]

    def clean_title(title: str) -> str:
        """Очищает заголовок от лишних символов и пробелов"""
        title = re.sub(r'\s+', ' ', title)
        title = title.replace('__', ' — ')
        return title.strip()

    def get_section_number(level: int, index: int) -> str:
        """Формирует номер раздела с учетом уровня вложенности"""
        while len(current_section) <= level:
            current_section.append(0)
        current_section[level] = index
        return '.'.join(str(num) for num in current_section[:level + 1]) + '.'

    def process_list_items(ul_element: WebElement, level: int = 0) -> None:
        # Сначала пробуем получить все ссылки и заголовки непосредственно через JavaScript
        if level == 0:
            try:
                # Запускаем JavaScript для извлечения всех ссылок независимо от структуры DOM
                js_results = browser.execute_script("""
                    function getAllLinksAndTexts() {
                        // Получаем все ссылки из DOM
                        const allLinks = Array.from(document.querySelectorAll('.tree a'));
                        
                        // Фильтруем и преобразуем
                        return allLinks
                            .filter(link => link.href && link.textContent.trim())
                            .map(link => {
                                // Определяем уровень вложенности на основе позиции в DOM
                                let level = 0;
                                let parent = link.parentElement;
                                
                                // Точнее определяем уровень вложенности
                                while (parent && parent.tagName !== 'BODY' && parent.className !== 'tree') {
                                    if (parent.tagName === 'UL') level++;
                                    parent = parent.parentElement;
                                }
                                
                                // Дополнительно проверяем количество родительских ul до элемента tree
                                const countParentULs = (elem) => {
                                    let count = 0;
                                    let current = elem;
                                    
                                    while (current && !current.classList.contains('tree')) {
                                        if (current.tagName === 'UL') count++;
                                        current = current.parentElement;
                                    }
                                    
                                    return count;
                                };
                                
                                const ulCount = countParentULs(link);
                                
                                // Корректируем уровень на основе нескольких признаков
                                // 1. Глубина вложенности ul
                                // 2. Отступ элемента (если доступен)
                                const computedStyle = window.getComputedStyle(link);
                                const paddingLeft = parseInt(computedStyle.paddingLeft) || 
                                                  parseInt(computedStyle.marginLeft) || 0;
                                
                                // Если есть большой отступ, учитываем его при определении уровня
                                const paddingLevel = Math.floor(paddingLeft / 20);
                                
                                // Выбираем наиболее правдоподобное значение уровня
                                const estimatedLevel = Math.max(level, ulCount, paddingLevel);
                                
                                // Проверяем, есть ли у ссылки особые классы, указывающие на уровень
                                const hasLevelClass = (link) => {
                                    for (let i = 0; i <= 10; i++) {
                                        if (link.classList.contains(`level-${i}`)) return i;
                                    }
                                    return -1;
                                };
                                
                                const classLevel = hasLevelClass(link);
                                if (classLevel >= 0) level = classLevel;
                                
                                return {
                                    url: link.href,
                                    title: link.textContent.trim(),
                                    level: estimatedLevel, 
                                    originalLevel: level,
                                    ulCount: ulCount,
                                    paddingLevel: paddingLevel
                                };
                            });
                    }
                    
                    return getAllLinksAndTexts();
                """)

                # Преобразуем результаты из JavaScript в объекты DocPage
                if js_results:
                    logger.debug("JavaScript метод нашёл {n} ссылок", n=len(js_results))

                    # Обрабатываем каждую ссылку
                    item_index = [0] * 10  # Поддерживаем счетчики для каждого уровня (до 10 уровней глубины)

                    for item in js_results:
                        try:
                            url = item.get('url')
                            title = item.get('title')
                            level = item.get('level', 0)

                            if url and title and url not in processed_urls and any(keyword in url for keyword in ["content", "bookmark", "browse"]):
                                item_index[level] += 1
                                # Сбрасываем счетчики для всех более глубоких уровней
                                for i in range(level + 1, len(item_index)):
                                    item_index[i] = 0

                                # Формируем номер раздела
                                section_number = '.'.join(str(num) for num in item_index[:level + 1] if num > 0) + '.'

                                page = DocPage(url, title, level, section_number)
                                pages.append(page)
                                processed_urls.add(url)
                                logger.debug("Добавлена страница через JS: {page}", page=page)
                        except Exception as e:
                            logger.error("Ошибка при обработке JS результата: {e}", e=e)

            except Exception as e:
                logger.error("Ошибка при JavaScript обходе дерева: {e}", e=e)

            # Если JavaScript метод не дал результатов, используем стандартный метод
            if not pages:
                logger.debug("JavaScript метод не дал результатов, используем стандартный обход")

        # Стандартный обход дерева через Selenium
        items = ul_element.find_elements(By.CSS_SELECTOR, "li")
        item_index = 0

        for item in items:
            try:
                # Проверяем, является ли элемент видимым или свернутым
                is_collapsed = False
                try:
                    is_collapsed = 'collapsed' in item.get_attribute('class')
                except Exception as e:
                    pass

                # Если элемент свернут, попробуем его развернуть
                if is_collapsed:
                    try:
                        # Используем JavaScript для разворачивания вместо поиска кнопки
                        # Это позволит избежать ошибки "no such element: .expand"
                        browser.execute_script("""
                            arguments[0].classList.remove('collapsed');
                            arguments[0].classList.add('expanded');
                            // Делаем дочерние элементы видимыми
                            const childUls = arguments[0].querySelectorAll('ul');
                            childUls.forEach(ul => {
                                ul.style.display = 'block';
                                ul.style.visibility = 'visible';
                            });
                        """, item)

                        time.sleep(0.3)  # Даем время на разворачивание
                        logger.debug("Развернут элемент через JavaScript")
                    except Exception as e:
                        logger.warning("Не удалось развернуть элемент через JavaScript: {e}", e=e)

                        # Запасной вариант - пробуем найти кнопку expand
                        try:
                            expand_buttons = item.find_elements(By.CSS_SELECTOR, ".expand")
                            if expand_buttons:
                                # Прокручиваем страницу к кнопке, чтобы она была видна
                                browser.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", expand_buttons[0])
                                expand_buttons[0].click()
                                time.sleep(0.3)  # Даем время на разворачивание
                                logger.debug("Развернут элемент через клик")
                        except Exception as e2:
                            logger.warning("Не удалось развернуть элемент: {e}", e=e2)

                # Проверяем, является ли элемент видимым
                if not item.is_displayed():
                    # Попробуем прокрутить к элементу, чтобы сделать его видимым
                    try:
                        browser.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", item)
                        time.sleep(0.2)
                    except Exception as e:
                        pass

                    # Если после прокрутки элемент всё ещё не виден, пропускаем его
                    if not item.is_displayed():
                        continue

                # Получаем ссылку и заголовок
                try:
                    link = item.find_element(By.CSS_SELECTOR, "a")
                    url = link.get_attribute("href")
                    title = clean_title(link.text)
                except Exception as e:
                    logger.debug("Пропущен элемент без ссылки или заголовка")
                    continue

                if not url or not title or url in processed_urls:
                    continue

                if any(keyword in url for keyword in ["content", "bookmark", "browse"]):
                    item_index += 1
                    section_number = get_section_number(level, item_index)
                    page = DocPage(url, title, level, section_number)
                    pages.append(page)
                    processed_urls.add(url)
                    logger.debug("Добавлена страница: {page}", page=page)

                # Обрабатываем вложенные элементы
                nested_lists = item.find_elements(By.CSS_SELECTOR, "ul")
                if nested_lists:
                    # Сбрасываем счетчики для следующего уровня
                    if len(current_section) > level + 1:
                        current_section[level + 1:] = [0] * (len(current_section) - level - 1)
                    for nested_list in nested_lists:
                        if nested_list.is_displayed():
                            process_list_items(nested_list, level + 1)

            except Exception as e:
                logger.error("Ошибка при обработке элемента: {e}", e=e)
                continue

    # Начинаем обработку с корневого элемента
    process_list_items(tree)

    # Если стандартный обход дал мало результатов, попробуем JavaScript метод
    if len(pages) < 10:
        try:
            logger.debug("Стандартный обход дал мало результатов, пробуем JavaScript метод")

            # Запускаем JavaScript для извлечения всех ссылок независимо от структуры DOM
            js_results = browser.execute_script("""
                function getAllLinksAndTexts() {
                    // Получаем все ссылки из DOM
                    const allLinks = Array.from(document.querySelectorAll('.tree a'));
                    
                    // Фильтруем и преобразуем
                    return allLinks
                        .filter(link => link.href && link.textContent.trim())
                        .map(link => {
                            // Определяем уровень вложенности на основе позиции в DOM
                            let level = 0;
                            let parent = link.parentElement;
                            
                            // Точнее определяем уровень вложенности
                            while (parent && parent.tagName !== 'BODY' && parent.className !== 'tree') {
                                if (parent.tagName === 'UL') level++;
                                parent = parent.parentElement;
                            }
                            
                            // Дополнительно проверяем количество родительских ul до элемента tree
                            const countParentULs = (elem) => {
                                let count = 0;
                                let current = elem;
                                
                                while (current && !current.classList.contains('tree')) {
                                    if (current.tagName === 'UL') count++;
                                    current = current.parentElement;
                                }
                                
                                return count;
                            };
                            
                            const ulCount = countParentULs(link);
                            
                            // Корректируем уровень на основе нескольких признаков
                            // 1. Глубина вложенности ul
                            // 2. Отступ элемента (если доступен)
                            const computedStyle = window.getComputedStyle(link);
                            const paddingLeft = parseInt(computedStyle.paddingLeft) || 
                                              parseInt(computedStyle.marginLeft) || 0;
                            
                            // Если есть большой отступ, учитываем его при определении уровня
                            const paddingLevel = Math.floor(paddingLeft / 20);
                            
                            // Выбираем наиболее правдоподобное значение уровня
                            const estimatedLevel = Math.max(level, ulCount, paddingLevel);
                            
                            // Проверяем, есть ли у ссылки особые классы, указывающие на уровень
                            const hasLevelClass = (link) => {
                                for (let i = 0; i <= 10; i++) {
                                    if (link.classList.contains(`level-${i}`)) return i;
                                }
                                return -1;
                            };
                            
                            const classLevel = hasLevelClass(link);
                            if (classLevel >= 0) level = classLevel;
                            
                            return {
                                url: link.href,
                                title: link.textContent.trim(),
                                level: estimatedLevel, 
                                originalLevel: level,
                                ulCount: ulCount,
                                paddingLevel: paddingLevel
                            };
                        });
                }
                
                return getAllLinksAndTexts();
            """)

            if js_results and len(js_results) > 0 and len(pages) < len(js_results):
                logger.debug("JavaScript извлёк {n} ссылок", n=len(js_results))

            # Очищаем текущие страницы
            pages = []
            processed_urls = set()

            # Анализируем уровни, чтобы определить правильную структуру
            min_level = min([item.get('level', 0) for item in js_results if 'level' in item], default=0)

            # Нормализуем уровни, чтобы минимальный был 0
            for item in js_results:
                if 'level' in item:
                    item['level'] = max(0, item['level'] - min_level)

            # Сортируем ссылки, чтобы они шли в правильном порядке
            # Сначала по уровню, потом по заголовку
            js_results.sort(key=lambda x: (x.get('level', 0), x.get('title', '')))

            # Сначала определим максимальный уровень для корректной нумерации
            max_level = max([item.get('level', 0) for item in js_results if 'level' in item], default=0)

            # Создаем счетчики для каждого уровня
            level_counters = {i: 0 for i in range(max_level + 1)}

            # Текущий контекст уровней для определения правильной нумерации
            current_level_context = [-1] * (max_level + 1)

            logger.debug("Обработка ссылок, уровней от {min} до {max}", min=min_level, max=max_level)

            for item in js_results:
                try:
                    url = item.get('url')
                    title = item.get('title')
                    level = item.get('level', 0)

                    if not url or not title or url in processed_urls:
                        continue

                    if any(keyword in url for keyword in ["content", "bookmark", "browse"]):
                        # Если мы переходим на новый уровень или возвращаемся на предыдущий
                        # Сбрасываем счетчики для всех более глубоких уровней
                        if level <= max_level:
                            # Обновляем счетчик текущего уровня
                            level_counters[level] += 1

                            # Обновляем контекст для текущего уровня
                            current_level_context[level] = level_counters[level]

                            # Сбрасываем все более глубокие уровни
                            for l in range(level + 1, max_level + 1):
                                level_counters[l] = 0
                                current_level_context[l] = -1

                    # Формируем номер раздела на основе контекста
                    section_parts = []
                    for l in range(level + 1):
                        if current_level_context[l] > 0:
                            section_parts.append(str(current_level_context[l]))

                    section_number = '.'.join(section_parts) + '.'

                    # Создаем объект страницы
                    page = DocPage(url, title, level, section_number)
                    pages.append(page)
                    processed_urls.add(url)

                    debug_info = f"(исходные данные: level={item.get('originalLevel', 'N/A')}, " + \
                                f"ulCount={item.get('ulCount', 'N/A')}, " + \
                                f"paddingLevel={item.get('paddingLevel', 'N/A')})"
                    logger.debug("Добавлена страница через JavaScript: {page} {info}", page=page, info=debug_info)
                except Exception as e:
                    logger.error("Ошибка при обработке JS результата: {e}", e=e)
        except Exception as e:
            logger.error("Ошибка при JavaScript извлечении ссылок: {e}", e=e)

    logger.debug("Структура документации:")
    for page in pages:
        logger.debug("  {number} {title}", number=page.number, title=page.title)

    if not pages:
        logger.warning("Не найдено ни одной страницы в дереве")
        logger.debug("Содержимое дерева: {html}", html=tree.get_attribute('innerHTML'))

        # Крайний случай - используем любые ссылки со страницы
        try:
            logger.info("Пробуем получить ссылки напрямую со страницы...")
            all_links = browser.find_elements(By.TAG_NAME, "a")

            # Фильтруем только уникальные ссылки, относящиеся к документации
            for link in all_links:
                try:
                    url = link.get_attribute("href")
                    title = link.text.strip()

                    if not url or not title or url in processed_urls:
                        continue

                    if any(keyword in url for keyword in ["content", "bookmark", "browse"]):
                        page = DocPage(url, title, 0, f"{len(pages)+1}.")
                        pages.append(page)
                        processed_urls.add(url)
                except Exception:
                    continue

            if pages:
                logger.info("Удалось получить {n} ссылок напрямую со страницы", n=len(pages))
        except Exception as e:
            logger.error("Не удалось получить ссылки напрямую: {e}", e=e)
    else:
        logger.info("Найдено {n} страниц", n=len(pages))

    return pages