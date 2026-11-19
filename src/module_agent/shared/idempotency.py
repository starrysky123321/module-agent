from enum import StrEnum


IDEMPOTENCY_KEY_HEADER = "idempotency-key"


class IdempotencyOperation(StrEnum):
    LITERATURE_DISPATCH = "literature.dispatch"
    LITERATURE_CONSUME = "literature.consume"
    PAPER_SELECT = "paper.select"
    CODE_EXECUTE = "code.execute"
    VALIDATION_EXECUTE = "validation.execute"


def idempotency_key(
    operation: IdempotencyOperation, run_id: int, *identity: int | str
) -> str:
    """Render an operation's existing business identity as a stable key."""
    return ":".join((operation.value, str(run_id), *(str(part) for part in identity)))
