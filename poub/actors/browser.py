import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import pykka
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, ElementNotInteractableException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

from building import BuildingTurn

from selenium.webdriver.support import expected_conditions as EC

LOGIN_URL = 'https://idp.unimore.it'


class LoginException(Exception):
    pass


class AlreadyBooked(Exception):
    pass


class BrowserInteractor:
    def __init__(self):
        self.print_dir = Path('prints').resolve()
        self.print_file = self.print_dir / 'print.pdf'

        self.current_user = None  # type: Optional[str]

        options = webdriver.FirefoxOptions()
        options.headless = True
        profile = webdriver.FirefoxProfile()
        self.setup_profile(profile)

        self.driver = webdriver.Firefox(options=options, firefox_profile=profile)
        self.driver.set_page_load_timeout(30)
        self.set_aboutcheck()

    def setup_profile(self, profile: webdriver.FirefoxProfile):
        profile.set_preference('services.sync.prefs.sync.browser.download.manager.showWhenStarting', False)
        profile.set_preference('pdfjs.disabled', True)
        profile.set_preference('print.always_print_silent', True)
        profile.set_preference('print.show_print_progress', False)
        profile.set_preference('browser.download.show_plugins_in_list', False)

        profile.set_preference('browser.download.folderList', 2)
        profile.set_preference('browser.download.dir', '')
        profile.set_preference('browser.download.manager.showWhenStarting', False)
        profile.set_preference('browser.aboutConfig.showWarning', False)

        profile.set_preference('print.print_headerright', '')
        profile.set_preference('print.print_headercenter', '')
        profile.set_preference('print.print_headerleft', '')
        profile.set_preference('print.print_footerright', '')
        profile.set_preference('print.print_footercenter', '')
        profile.set_preference('print.print_footerleft', '')
        profile.set_preference('browser.helperApps.neverAsk.saveToDisk',
                               'application/octet-stream;application/vnd.ms-excel;text/html')

    def set_aboutcheck(self):
        self.driver.get('about:config')
        time.sleep(1)

        # Define Configurations
        script = """
                var prefs = Components.classes['@mozilla.org/preferences-service;1'].getService(Components.interfaces.nsIPrefBranch);
                prefs.setBoolPref('print.always_print_silent', true);
                prefs.setCharPref('print_printer', 'Print to File');
                prefs.setBoolPref('print.printer_Print_to_File.print_to_file', true);
                prefs.setCharPref('print.printer_Print_to_File.print_to_filename', '{}');
                prefs.setBoolPref('print.printer_Print_to_File.show_print_progress', true);
                """.format(self.print_file)

        # Set Configurations
        self.driver.execute_script(script)

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

        submit_button = self.driver.find_element_by_xpath('//button[contains(., "Inserisci")]')
        try:
            submit_button.click()
            clicked = True
        except ElementNotInteractableException:
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
        WebDriverWait(self.driver, 60)\
            .until(EC.visibility_of_element_located((By.XPATH, '//div[contains(text(), "Posto: ")]')))
        time.sleep(0.1)  # Don't know if it's necessary
        # Print!
        self.print_dir.mkdir(parents=True, exist_ok=True)
        self.driver.execute_script('window.print(); setTimeout(() => {window.seldone = true;}, 100);')
        WebDriverWait(self.driver, 60)\
            .until(lambda d: d.execute_script('return !!window.seldone') and self.print_file.is_file())
        new_file = self.print_file.parent / (uuid.uuid4().hex + '.pdf')

        return self.print_file.rename(new_file)

    def stop(self):
        self.driver.quit()


class BookResultType(Enum):
    OK = 1
    TIMEOUT = 2
    LOGIN_FAILED = 3
    UNKNOWN_ERR = 9


@dataclass
class BookResult:
    booked: list[tuple[BuildingTurn, Path]]
    remaining: list[BuildingTurn]
    type: BookResultType


class BrowserActor(pykka.ThreadingActor):
    def __init__(self):
        super().__init__()
        self._browser = BrowserInteractor()
        self._logger = logging.getLogger('browser')

    def process_bookings(self, username: str, password: str, turns: set[BuildingTurn]) -> BookResult:
        turns = list(turns)
        booked = []

        for i, turn in enumerate(turns):
            retry = 3
            while retry > 0:
                retry -= 1
                try:
                    self._logger.info(f"Booking {i}: {turn.room} {turn.trange} {turn.book_link}")
                    link = self._browser.book_one(username, password, turn.book_link)
                    booked.append((turn, link))
                    retry = 0
                except LoginException:
                    self._logger.exception('Wrong login for user ' + username)
                    return BookResult(booked, turns[i:], BookResultType.LOGIN_FAILED)
                except TimeoutException:
                    if retry > 0:
                        self._logger.warning(f'Timeout, retries: {retry}')
                    else:
                        self._logger.exception(f'Timeout exception ({i}/{len(turns)})')
                        return BookResult(booked, turns[i:], BookResultType.TIMEOUT)
                except AlreadyBooked:
                    self._logger.warning(f"Already booked ({i}/{len(turns)})")
                    retry = 0
                except Exception:
                    self._logger.exception(f'Unknown exception ({i}/{len(turns)})')
                    return BookResult(booked, turns[i:], BookResultType.UNKNOWN_ERR)

        return BookResult(booked, [], BookResultType.OK)

    def on_stop(self) -> None:
        self._browser.stop()
