from dataclasses import dataclass

import torch

from gisting.training.kit import Kit
from gisting.training.teacher import TeacherRecord


@dataclass(frozen=True)
class Example:
    sample_id: str
    teacher_ids: torch.Tensor
    teacher_positions: torch.Tensor
    student_ids: torch.Tensor
    student_positions: torch.Tensor
    verdict_ok: bool
    category: str


def make_example(kit: Kit, record: TeacherRecord, device: str, max_len: int) -> Example | None:
    target = record.target_ids(kit)
    sample = record.sample
    teacher_prefix = kit.prompt(sample.messages, gist=False).ids
    student_prefix = kit.prompt(sample.messages, gist=True).ids
    if len(teacher_prefix) + len(target) > max_len:
        return None
    return Example(
        sample.id,
        torch.tensor([teacher_prefix + target], device=device),
        torch.arange(len(teacher_prefix) - 1, len(teacher_prefix) + len(target) - 1, device=device),
        torch.tensor([student_prefix + target], device=device),
        torch.arange(len(student_prefix) - 1, len(student_prefix) + len(target) - 1, device=device),
        record.verdict.ok,
        sample.category,
    )
