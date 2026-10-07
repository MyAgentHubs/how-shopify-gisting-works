from gisting.prompt.files import PROMPTS_DIR
from gisting.tools.mock import MockSpec, ReferenceTool

TOOL_NAME = "handoff_to_human"
HANDED_OFF = "handed_off"
SPEC = MockSpec(
    name=TOOL_NAME,
    status=HANDED_OFF,
    field="ticket",
    result_type="HandedOff",
    policy_file=PROMPTS_DIR / "handoff_to_human.policy.json",
    detail_argument="reason",
)


class HandoffToHuman(ReferenceTool):
    def __init__(self) -> None:
        super().__init__(SPEC)
