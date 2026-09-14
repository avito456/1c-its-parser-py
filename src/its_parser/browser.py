from __future__ import annotations

import time

from loguru import logger
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def create_browser(headless: bool = False) -> webdriver.Chrome:
    """Создает и настраивает браузер Chrome"""
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')

    # Оптимизация загрузки браузера
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-popup-blocking')
    options.add_argument('--blink-settings=imagesEnabled=true')
    options.page_load_strategy = 'eager'

    # Дополнительные настройки для ускорения
    prefs = {
        'profile.default_content_setting_values.notifications': 2,
        'profile.managed_default_content_settings.images': 1,
        'disk-cache-size': 4096,
    }
    options.add_experimental_option('prefs', prefs)

    browser = webdriver.Chrome(options=options)
    browser.maximize_window()
    return browser


def login(browser: webdriver.Chrome, login_url: str, username: str, password: str) -> None:
    """Авторизация на странице 1С ИТС"""
    logger.info("Авторизация...")
    browser.get(login_url)

    username_input = WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.NAME, "username"))
    )
    password_input = browser.find_element(By.NAME, "password")

    username_input.send_keys(username)
    password_input.send_keys(password)

    login_button = browser.find_element(By.CSS_SELECTOR, "input[type='submit']")
    login_button.click()

    time.sleep(2)