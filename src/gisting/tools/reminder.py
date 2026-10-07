from gisting.prompt.files import PROMPTS_DIR
from gisting.tools.mock import MockSpec, ReferenceTool

TOOL_NAME = "send_shipping_reminder"
REQUESTED = "requested"
SPEC = MockSpec(
    name=TOOL_NAME,
    status=REQUESTED,
    field="reference",
    result_type="ShippingReminderSent",
    policy_file=PROMPTS_DIR / "send_shipping_reminder.policy.json",
    order_argument="order_number",
)


class SendShippingReminder(ReferenceTool):
    def __init__(self) -> None:
        super().__init__(SPEC)
