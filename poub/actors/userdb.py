import json
import logging
from dataclasses import dataclass, asdict
from typing import Optional

import pykka

USERS_FILE = 'users.json'


@dataclass
class User:
    tid: int
    username: Optional[str]
    password: Optional[str]
    subjects: list[tuple[str, str]]


class UserNotFoundException(Exception):
    pass


class UserDbActor(pykka.ThreadingActor):
    def __init__(self):
        super().__init__()
        self._users_by_tid = {}  # type: dict[int, User]
        self._logger = logging.getLogger('userdb')

    def on_start(self) -> None:
        self._load_users()

    def get_user(self, telegram_id: int) -> User:
        return self._find_user(telegram_id)

    def create_user(self, telegram_id: int) -> User:
        return self._find_user(telegram_id, create=True)

    def delete_user(self, telegram_id: int):
        if telegram_id in self._users_by_tid:
            self._users_by_tid.pop(telegram_id)
            self._save_users()

    def get_bookable_users(self) -> list[User]:
        return [x for x in self._users_by_tid.values() if x.username is not None and len(x.subjects) > 0]

    def user_login(self, telegram_id: int, username: str, password: str) -> User:
        user = self._find_user(telegram_id)
        user.username = username
        user.password = password
        self._save_users()
        return user

    def user_add_subject(self, telegram_id: int, subject: tuple[str, str]) -> User:
        user = self._find_user(telegram_id)
        if subject not in user.subjects:
            user.subjects.append(subject)
            self._save_users()
        return user

    def user_remove_subject(self, telegram_id: int, subject: tuple[str, str]) -> User:
        user = self._find_user(telegram_id)
        if subject in user.subjects:
            user.subjects.remove(subject)
            self._save_users()
        return user

    def _find_user(self, telegram_id: int, create = False) -> User:
        if telegram_id in self._users_by_tid:
            return self._users_by_tid[telegram_id]
        if not create:
            raise UserNotFoundException()
        user = User(
            tid=telegram_id,
            username=None,
            password=None,
            subjects=[]
        )
        self._users_by_tid[telegram_id] = user
        self._save_users()
        return user

    def _save_users(self):
        try:
            with open(USERS_FILE, 'wt') as fd:
                data = [asdict(x) for x in self._users_by_tid.values()]
                json.dump(data, fd)
        except Exception:
            logging.exception('Error saving userdb')

    def _load_users(self):
        try:
            with open(USERS_FILE, 'rt') as fd:
                data = json.load(fd)
            self._users_by_tid = {x.tid: x for x in (User(**x) for x in data)}
        except FileNotFoundError:
            logging.info('userdb not present')
        except Exception:
            logging.exception('Error loading userdb')

