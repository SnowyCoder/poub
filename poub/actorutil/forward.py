import logging
from typing import Optional, Callable, Union

from pykka import Future, ActorRef
# noinspection PyProtectedMember
from pykka._envelope import Envelope
from pykka.messages import ProxyCall


class _ForwardingFuture(Future):
    def __init__(self, then: Optional[Callable], on_error: Optional[Callable]):
        self._then = then
        self._on_error = on_error

    def set(self, value=None):
        if self._then is not None:
            self._then(value)

    def set_exception(self, exc_info=None):
        if self._on_error is not None:
            self._on_error(exc_info)
        else:
            logging.error('Error while futuring!', exc_info=exc_info)


def ask_forwarding(actor_ref: ActorRef, path: Union[str, tuple], *args,
                   then: Optional[Callable] = None, on_error: Optional[Callable] = None, **kwargs):
    if type(path) == str:
        path = (path,)
    message = ProxyCall(path, args, kwargs)
    false_future = _ForwardingFuture(then, on_error)

    actor_ref.actor_inbox.put(Envelope(message, reply_to=false_future))
