import logging
from functools import partial

from pykka import ThreadingActor, ActorRef

from actorutil.event import EventEmitter
from actorutil.forward import ask_forwarding
from .browser import BookResult
from .userdb import User
from building import BuildingTurn
from waiter import waiter


class BookActor(ThreadingActor):
    def __init__(self, dtactor: ActorRef, browser: ActorRef, userdb: ActorRef):
        super().__init__()
        self.events = EventEmitter()
        self.dtactor = dtactor
        self.browser = browser
        self.userdb = userdb

        self._waiter_midnight = None
        self._waiter_pre_midnight = None

    def on_start(self) -> None:
        self._waiter_midnight = waiter.add(lambda: self.actor_ref.proxy().book(), hour=0, minute=0, second=0, microsecond=10)
        # Pre-Update timetables at 23:50 to be faster
        self._waiter_pre_midnight = waiter.add(lambda: self.dtactor.proxy().update_timetable(), hour=23, minute=50, second=0, microsecond=0)

    def on_stop(self) -> None:
        waiter.remove(self._waiter_midnight)
        waiter.remove(self._waiter_pre_midnight)

    def on_booked(self, user: User, book_res: BookResult):
        logging.info(f"Booking result {book_res}")

        def remove_file():
            for _, x in book_res.booked:
                x.unlink(missing_ok=True)

        self.events.emit('booked', user, book_res, then=remove_file)

    def _on_links(self, user: User, bookings: set[BuildingTurn]):
        logging.info(f"Booking: {', '.join(f'{x.room} ({x.trange})' for x in bookings)} for {user.username}")
        ask_forwarding(self.browser, 'process_bookings', user.username, user.password, bookings,
                       then=lambda booking_res: self.actor_ref.proxy().on_booked(user, booking_res))

    def book(self):
        logging.info(f"Booking started...")

        users = self.userdb.proxy().get_bookable_users().get()  # type: list[User]
        logging.info(f'Booking {len(users)} users')
        for user in users:
            ask_forwarding(self.dtactor, 'resolve_links', user.subjects, then=partial(self._on_links, user))


