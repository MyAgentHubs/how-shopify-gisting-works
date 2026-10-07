from dataclasses import dataclass

from gisting.serve.deadline import Deadline
from gisting.tools.attempts import FailureCounter
from gisting.tools.reads import LookupSink


@dataclass(frozen=True)
class TurnScope:
    deadline: Deadline
    failures: FailureCounter
    reads: LookupSink
