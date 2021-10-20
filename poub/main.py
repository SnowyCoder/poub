#!/usr/bin/env python
# coding:utf-8
import logging

import pykka

from actors.bookactor import BookActor
from actors.browser import BrowserActor
from actors.dtactor import DataTableActor
from actors.tbot import TelegramBotActor
from actors.userdb import UserDbActor
from waiter import waiter

logging.basicConfig(level=logging.INFO)

userdb = UserDbActor.start()
dtactor = DataTableActor.start()
browser = BrowserActor.start()
booker = BookActor.start(dtactor, browser, userdb)
tbot = TelegramBotActor.start(dtactor, userdb, booker)


def update_timetable():
    dtactor.proxy().update_timetable()


def shutdown_actors():
    reg = pykka.ActorRegistry()
    for act in reg.get_all():
        act.stop(block=True)


def main():
    logging.info("Poub started, waiting until midnight")
    # Used to test:
    # booker.proxy().book()
    try:
        waiter.run_sync()
    except KeyboardInterrupt:
        shutdown_actors()


if __name__ == '__main__':
    main()

