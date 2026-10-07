from dataclasses import dataclass, field

from gisting.model_server.interface import Generation


@dataclass
class FakeModel:
    outputs: list[str]
    backend_id: str = "fake-model"
    prompts: list[list[int]] = field(default_factory=lambda: [])
    limits: list[int] = field(default_factory=lambda: [])

    def generate(self, ids: list[int], max_new_tokens: int) -> Generation:
        assert self.outputs, "fake model has no scripted output left"
        self.prompts.append(list(ids))
        self.limits.append(max_new_tokens)
        return Generation(self.outputs.pop(0), (1, 2, 3), 11.0, 22.0, "stop")

    def count(self, text: str) -> int:
        return len(text.split())
