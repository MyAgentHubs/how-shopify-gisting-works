from gisting.training.compare import Subject, mode_injection


def injected_vectors(subject: Subject, mode: str):
    injection = mode_injection(subject, mode)
    return None if injection is None else injection.vectors
