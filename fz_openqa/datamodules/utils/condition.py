from typing import Callable

from fz_openqa.utils.datastruct import Batch


class Condition:
    def __call__(self, batch: Batch) -> bool:
        raise NotImplementedError


class Reduce(Condition):
    def __init__(self, *conditions: Condition, reduce_op: Callable = all):
        self.reduce_op = reduce_op
        self.conditions = list(conditions)

    def __call__(self, batch: Batch) -> bool:
        return self.reduce_op(c(batch) for c in self.conditions)


class HasKeyWithPrefix(Condition):
    def __init__(self, prefix: str):
        self.prefix = prefix

    def __call__(self, batch: Batch) -> bool:
        return any(str(k).startswith(self.prefix) for k in batch.keys())


class Not(Condition):
    def __init__(self, condition: Condition):
        self.condition = condition

    def __call__(self, batch: Batch) -> bool:
        return not self.condition(batch)


class Static(Condition):
    """check if the key is in the allowed_keys"""

    def __init__(self, cond: bool):
        self.cond = cond

    def __call__(self, batch: Batch) -> bool:
        return self.cond
