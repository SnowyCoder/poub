import itertools
import logging
import os.path
import pickle
from datetime import datetime, timedelta
from typing import Optional
from itertools import groupby

import pykka

import building
import timetable

TIMETABLE_FILENAME = os.path.join(os.getcwd(), 'timetable_cache.pkl')
TIMETABLE_FORMAT = '%Y/%m/%d %H:%M'

DAY_NAMES = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']


# Manages the datetime table and the building table
class DataTableActor(pykka.ThreadingActor):
    def __init__(self):
        super().__init__()

        self._logger = logging.getLogger('datetable')
        self._timetable = None  # type: Optional[timetable.OrarioDocenti]
        self._teacher_subjects = None  # type: Optional[dict[str, set[str]]]
        self._last_timetable_update = datetime.fromtimestamp(0)

    def on_start(self) -> None:
        self._load_timetable()
        self.fast_update_timetable()

    def resolve_links(self, lectures: list[tuple[str, str]]) -> set[building.BuildingTurn]:
        self.fast_update_timetable()
        res = set()

        day = DAY_NAMES[datetime.now().weekday()]
        cells = timetable.get_lectures(self._timetable, day, lectures)
        for cell in cells:
            bdata = building.get_link_from_fim_time_table(cell)
            if bdata is None:
                self._logger.error(f"Cannot find lecture building: {cell}")
                continue
            res.add(bdata)

        self._logger.info(f"Links resolved: {res}")
        return res

    def fast_update_timetable(self) -> None:
        now = datetime.now()
        if now - self._last_timetable_update > timedelta(minutes=5):
            self.update_timetable()

    def update_timetable(self) -> None:
        last_time = None
        if self._timetable is not None:
            last_time = self._timetable.date
        res = timetable.update_docenti(last_time)
        if res is not None:
            self._logger.info(f"Updated timetable to {res.date.strftime(TIMETABLE_FORMAT)}")
            self._timetable = res
            self._update_teacher_subjects()
            self._save_timetable()
        else:
            self._logger.info("Time table up to date")
        self._last_timetable_update = datetime.now()

    def _update_teacher_subjects(self):
        teach_subj = itertools.chain(*[((y.teacher, y.name) for y in x) for x in self._timetable.data.values()])
        res = {k: set(vi[1] for vi in v) for k, v in groupby(sorted(set(teach_subj)), lambda x: x[0])}
        self._teacher_subjects = res

    def _load_timetable(self) -> None:
        loaded = False

        try:
            with open(TIMETABLE_FILENAME, 'rb') as fd:
                self._timetable = pickle.load(fd)
            self._update_teacher_subjects()
            loaded = True
        except FileNotFoundError:
            self._logger.info('Time table cache not present')
        except Exception:
            self._logger.exception('Failed to load timetable cache')

        if loaded:
            self._logger.info(f"Loaded timetable {self._timetable.date.strftime(TIMETABLE_FORMAT)}")
        else:
            self.update_timetable()

    def _save_timetable(self) -> None:
        try:
            with open(TIMETABLE_FILENAME, 'wb') as fd:
                pickle.dump(self._timetable, fd)
        except Exception:
            self._logger.exception('Failed to save timetable cache')

    def get_teachers(self) -> set[str]:
        return set(self._teacher_subjects.keys())

    def get_teacher_subjects(self, teach: str) -> set[str]:
        return self._teacher_subjects[timetable.normalize_teacher_name(teach)]



