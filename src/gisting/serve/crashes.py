import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from gisting.serve.logs import LogRecord, RequestLog, failure_site

WATCHED = frozenset({"serve-loader", "serve-gate", "serve-listener"})


@dataclass
class Watch:
    stop: threading.Event = field(default_factory=threading.Event)
    crashed: threading.Event = field(default_factory=threading.Event)


def crash_hook(logs: RequestLog, watch: Watch) -> Callable[[threading.ExceptHookArgs], None]:
    def hook(args: threading.ExceptHookArgs) -> None:
        name = args.thread.name if args.thread is not None else None
        if name in WATCHED:
            watch.crashed.set()
            watch.stop.set()
        logs.emit(
            LogRecord(
                "thread_crashed",
                error_type=args.exc_type.__name__,
                thread=name,
                where=failure_site(args.exc_value),
            )
        )

    return hook
