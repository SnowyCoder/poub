from typing import Callable, Optional

from pykka import ActorRef
from pykka.messages import ProxyCall

from actorutil.forward import ask_forwarding


class EventEmitter:
    def __init__(self):
        self.__data = {}  # type: dict[str, tuple[object, list[ActorRef]]]
        self._pykka_traversable = True

    def has_listeners(self, event_name) -> bool:
        data = self.__data.get(event_name, None)

        return data is not None and len(data[1]) != 0

    def emit(self, event_name, *args, then: Optional[Callable] = None, **kwargs) -> None:
        data = self.__data.get(event_name, None)
        if data is None:
            return

        eid, listeners = data
        argdata = (eid, args, kwargs)
        if then is not None:
            remaining = len(listeners)

            def x_then(_info=None):
                nonlocal remaining
                remaining -= 1
                if remaining == 0:
                    then()

            for listener in listeners:
                ask_forwarding(listener, ('on_event',), *argdata, then=x_then, on_error=x_then)
        else:
            for listener in listeners:
                listener.tell(ProxyCall(('on_event',), argdata, {}))

    def _get_eid(self, name: str, create=True) -> object:
        data = self.__data.get(name, None)
        if data is None:
            if not create:
                return None
            data = (object(), [])
            self.__data[name] = data
        return data[0]

    def on_subscribe(self, name: str, act_ref: ActorRef) -> object:
        eid = self._get_eid(name)
        self.__data[name][1].append(act_ref)
        return eid


class EventListener:
    def __init__(self):
        super().__init__()
        self._subscribed = {}  # type: dict[object, Callable]

    def on_event(self, eid: object, args, kwargs):
        callab = self._subscribed[eid]
        if callab is None:
            return
        callab(*args, **kwargs)

    def event_subscribe(self, self_ref: ActorRef, emitter: EventEmitter, event_name: str, run: Callable):
        eid = emitter.on_subscribe(event_name, self_ref).get()
        self._subscribed[eid] = run

