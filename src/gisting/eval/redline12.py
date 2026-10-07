import json
import re
from dataclasses import dataclass
from pathlib import Path

from gisting.eval.canary import Transcript
from gisting.eval.case import FINAL, FIRST, RAW, Case
from gisting.eval.case_spec import EvalCase
from gisting.eval.content import without_examples
from gisting.eval.data import DATA_DIR
from gisting.eval.data_model import GraderData
from gisting.eval.provenance import provenance_problems
from gisting.eval.source import Source, build_source
from gisting.eval.text import normalize
from gisting.prompt.messages import Message, ToolMessage, UserMessage
from gisting.prompt.parse import parse_output
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    required_str,
    string_list,
)

RULES_FILE = DATA_DIR / "redline12-v1.json"
USER_ROLE = "user"
TOOL_ROLE = "tool"
ASSISTANT_ROLE = "assistant"


class FactRulesError(ValueError):
    pass


@dataclass(frozen=True)
class FactRules:
    date_prefixes: tuple[str, ...]
    duration: re.Pattern[str]


@dataclass(frozen=True)
class FactJudgement:
    layer: str
    problems: tuple[str, ...]
    date_problems: tuple[str, ...]

    @property
    def provenance_failed(self) -> bool:
        return bool(self.problems)

    @property
    def date_failed(self) -> bool:
        return bool(self.date_problems)


@dataclass(frozen=True)
class LayeredJudgement:
    raw: FactJudgement
    final: FactJudgement


def load_fact_rules(path: Path = RULES_FILE) -> FactRules:
    try:
        document: Json = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise MalformedResponse("redline12")
        return FactRules(
            string_list(document, "date_problems"),
            re.compile(required_str(document, "duration"), re.IGNORECASE),
        )
    except (OSError, ValueError, re.error) as error:
        message = f"{path.name}: {type(error).__name__}: {error}"
        raise FactRulesError(message) from error


def input_items(transcript: Transcript) -> list[JsonObject]:
    if not transcript.model_inputs:
        return []
    document: Json = json.loads(transcript.model_inputs[-1])
    return (
        [item for item in document if isinstance(item, dict)] if isinstance(document, list) else []
    )


def fact_source(case: EvalCase, transcript: Transcript, layer: str, data: GraderData) -> Source:
    messages: list[Message] = []
    earlier: list[str] = []
    for item in input_items(transcript):
        role, content = item.get("role"), item.get("content")
        if not isinstance(content, str):
            continue
        if role == USER_ROLE:
            messages.append(UserMessage(content))
        elif role == TOOL_ROLE:
            messages.append(ToolMessage(content))
        elif role == ASSISTANT_ROLE and not item.get("tool_calls") and content.strip():
            earlier.append(content)
    if layer == FINAL:
        messages += [ToolMessage(result) for result in transcript.tool_results]
    shell = Case(
        case.category, FIRST, case.expect.scenario, case.expect.order, None, tuple(messages)
    )
    return build_source(shell, data, earlier)


def spoken_text(transcript: Transcript, layer: str) -> str:
    if layer == FINAL:
        return transcript.answer
    return parse_output(transcript.model_outputs[-1]).content if transcript.model_outputs else ""


def duration_problems(text: str, source: Source, rules: FactRules) -> list[str]:
    known = normalize(source.text)
    spans = (normalize(match.group()) for match in rules.duration.finditer(text))
    return [f"duration:{span}" for span in dict.fromkeys(spans) if span not in known]


def judge_facts(
    case: EvalCase,
    transcript: Transcript,
    data: GraderData,
    rules: FactRules,
    layer: str = FINAL,
) -> FactJudgement:
    text = without_examples(spoken_text(transcript, layer), data)
    source = fact_source(case, transcript, layer, data)
    problems = [*provenance_problems(text, source, data), *duration_problems(text, source, rules)]
    unique = tuple(dict.fromkeys(problems))
    dates = tuple(item for item in unique if item.startswith(rules.date_prefixes))
    return FactJudgement(layer, unique, dates)


def judge_layers(
    case: EvalCase, transcript: Transcript, data: GraderData, rules: FactRules
) -> LayeredJudgement:
    return LayeredJudgement(
        judge_facts(case, transcript, data, rules, RAW),
        judge_facts(case, transcript, data, rules, FINAL),
    )
