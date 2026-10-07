import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from gisting.prompt.schema import ToolSchema, load_tool_schemas, validate_arguments
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    required_int,
    required_str,
    string_list,
)
from gisting.tools.lookup_order import ToolResponse
from gisting.tools.policy import PolicyError
from gisting.tools.trace import InternalTrace, PublicOutcome, PublicTrace, Trace


class InvalidMockCall(ValueError):
    pass


@dataclass(frozen=True)
class ReferencePolicy:
    prefix: str
    digits: int
    derived_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class MockSpec:
    name: str
    status: str
    field: str
    result_type: str
    policy_file: Path
    order_argument: str | None = None
    detail_argument: str | None = None


def parse_policy(document: Json) -> ReferencePolicy:
    if not isinstance(document, dict):
        raise MalformedResponse("policy")
    policy = ReferencePolicy(
        prefix=required_str(document, "prefix"),
        digits=required_int(document, "digits"),
        derived_values=string_list(document, "reasons") if "reasons" in document else (),
    )
    if not policy.prefix or policy.digits < 1:
        raise MalformedResponse("reference")
    return policy


def load_reference_policy(path: Path) -> ReferencePolicy:
    try:
        return parse_policy(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        message = f"{type(error).__name__}: {error}"
        raise PolicyError(message) from error


def reference_for(session_id: str, policy: ReferencePolicy) -> str:
    digest = int(hashlib.sha256(session_id.encode("utf-8")).hexdigest(), 16)
    return f"{policy.prefix}{digest % 10**policy.digits:0{policy.digits}d}"


def optional_text(arguments: JsonObject, key: str | None) -> str | None:
    value = arguments.get(key) if key else None
    return value if isinstance(value, str) else None


class ReferenceTool:
    def __init__(
        self,
        spec: MockSpec,
        policy: ReferencePolicy | None = None,
        schema: ToolSchema | None = None,
    ) -> None:
        self._spec = spec
        self._policy = policy or load_reference_policy(spec.policy_file)
        self._schema = schema or load_tool_schemas()[spec.name]

    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        derived = self._spec.detail_argument
        given = {key: value for key, value in arguments.items() if key != derived}
        problem = validate_arguments(self._schema, given)
        if derived and arguments.get(derived) not in self._policy.derived_values:
            problem = f"argument {derived} must be one of: {', '.join(self._policy.derived_values)}"
        if problem:
            raise InvalidMockCall(problem)
        internal = InternalTrace(
            tool=self._spec.name,
            session_id=session_id,
            order_number=optional_text(arguments, self._spec.order_argument),
            result_type=self._spec.result_type,
            cache_hit=None,
            detail=optional_text(arguments, self._spec.detail_argument),
            failures_before=0,
        )
        public = PublicTrace(self._spec.name, None, PublicOutcome.COMPLETED)
        result: JsonObject = {
            "status": self._spec.status,
            self._spec.field: reference_for(session_id, self._policy),
        }
        return ToolResponse(result, Trace(internal, public))
