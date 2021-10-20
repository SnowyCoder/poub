import logging
import time
import uuid
import base64
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, NamedTuple

import pykka
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, ElementNotInteractableException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from building import BuildingTurn


LOGIN_URL = 'https://idp.unimore.it'


class LoginException(Exception):
    pass


class AlreadyBooked(Exception):
    pass


class BrowserInteractor:
    def __init__(self):
        self.current_user = None  # type: Optional[str]

        options = webdriver.FirefoxOptions()
        options.headless = True
        profile = webdriver.FirefoxProfile()

        self.driver = webdriver.Firefox(options=options, firefox_profile=profile)
        self.driver.set_page_load_timeout(30)

    def logout(self):
        self.driver.delete_all_cookies()

    def _handle_login(self, username: str, password: str):
        if not self.driver.current_url.startswith(LOGIN_URL):
            return
        self.driver.find_element_by_id('username').send_keys(username)
        self.driver.find_element_by_id('password').send_keys(password)
        self.driver.find_element_by_css_selector('.content button[type="submit"]').click()

        time.sleep(1.0)

        if self.driver.current_url.startswith(LOGIN_URL):
            raise LoginException('Login failed')

        self.current_user = username

    def book_one(self, username: str, password: str, url: str) -> Path:
        if username != self.current_user:
            self.logout()
        self.driver.get(url)

        WebDriverWait(self.driver, 60).until(lambda d: d.current_url.startswith(LOGIN_URL) or
                                             d.find_element_by_xpath('//a[contains(., "Le mie presenze di oggi")]'))

        self._handle_login(username, password)

        time.sleep(0.1)
        try:
            submit_button = self.driver.find_element_by_xpath('//button[contains(., "Inserisci")]')
            submit_button.click()
            clicked = True
        except Exception:
            clicked = False

        if not clicked:
            if self.driver.find_element_by_xpath(
                    '//span[text() = "Attenzione"]/..[contains(., "altre prenotazioni")]') is not None:
                raise AlreadyBooked()
            if self.driver.find_element_by_xpath(
                    '//span[text() = "Attenzione"]/..[contains(., "Non e\' possibile inserire la presenza")]'
            ) is not None:
                raise Exception('Cannot insert booking (??)')
            raise Exception('Cannot find booking button (??)')

        # Wait for badge loading

        elem = WebDriverWait(self.driver, 60)\
                .until(EC.any_of(
                EC.visibility_of_element_located((By.XPATH, '//div[contains(text(), "Posto: ")]')),
                EC.visibility_of_element_located((By.XPATH, '//div[contains(text(), "no permission")]'))
                ))

        text = elem.text
        if 'no permission' in text:
            if 'insert_multiple_time' in text:
                raise AlreadyBooked()
            else:
                raise Exception(text)

        time.sleep(0.1)  # Don't know if it's necessary
        # Print!
        ret = self.driver.print_page()
        return base64.b64decode(ret)

    def save_debug_page(self):
        tstamp = int(time.time() * 1000)
        url = self.driver.current_url
        body = self.driver.execute_script("return document.body.innerHTML;")
        try:
            with open(f'{tstamp}.html', 'wt') as fd:
                fd.write(url + '\n' * 3)
                fd.write(body)
        except:
            pass

    def stop(self):
        self.driver.quit()


class BookResultType(Enum):
    OK = 1
    TIMEOUT = 2
    LOGIN_FAILED = 3
    UNKNOWN_ERR = 9


class BookTurnResultType(Enum):
    OK = 1
    ALREADY_BOOKED = 2
    UNKNOWN_ERR = 3


class BookTurnResult(NamedTuple):
    info: BuildingTurn
    res: BookTurnResultType
    pdf: Optional[bytes]


@dataclass
class BookResult:
    booked: list[BookTurnResult]
    remaining: list[BuildingTurn]
    type: BookResultType


class BrowserActor(pykka.ThreadingActor):
    def __init__(self):
        super().__init__()
        self._browser = BrowserInteractor()
        self._logger = logging.getLogger('browser')

    def process_bookings(self, username: str, password: str, turns: set[BuildingTurn]) -> BookResult:
        turns = list(turns)
        booked = []  # type: list[BookTurnResult]

        for i, turn in enumerate(turns):
            retry = 3
            while retry > 0:
                retry -= 1
                try:
                    self._logger.info(f"Booking {i}: {turn.room} {turn.trange} {turn.book_link}")
                    data = self._browser.book_one(username, password, turn.book_link)
                    booked.append(BookTurnResult(turn, BookTurnResultType.OK, data))
                    retry = 0
                except LoginException:
                    self._logger.exception('Wrong login for user ' + username)
                    return BookResult(booked, turns[i:], BookResultType.LOGIN_FAILED)
                except TimeoutException:
                    if retry > 0:
                        self._logger.exception(f'Timeout, retries: {retry}')
                    else:
                        self._logger.exception(f'Timeout exception ({i}/{len(turns)})')
                        return BookResult(booked, turns[i:], BookResultType.TIMEOUT)
                except AlreadyBooked:
                    self._logger.warning(f"Already booked ({i}/{len(turns)})")
                    booked.append(BookTurnResult(turn, BookTurnResultType.ALREADY_BOOKED, None))
                    retry = 0
                except Exception:
                    self._browser.save_debug_page()
                    self._logger.exception(f'Unknown exception ({i}/{len(turns)})')
                    return BookResult(booked, turns[i:], BookResultType.UNKNOWN_ERR)

        return BookResult(booked, [], BookResultType.OK)

    def on_stop(self) -> None:
        self._browser.stop()
