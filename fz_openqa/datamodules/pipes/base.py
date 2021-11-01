from copy import copy
from copy import deepcopy
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import dill
import rich
from datasets.fingerprint import Hasher

from fz_openqa.utils.datastruct import Batch


def _filter_null_id(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in data.items() if not (k == "id" and v is None)}


def always_true(*args, **kwargs):
    return True


class Pipe(object):
    """
    A pipe is a small unit of computation that ingests,
    modify and returns a batch of data.
    """

    id: Optional[str] = None
    requires_keys: Optional[List[str]] = None

    def __init__(self, *, id: Optional[str] = None):
        self.id = id or self.id

    def output_keys(self, input_keys: List[str]) -> List[str]:
        return input_keys

    @staticmethod
    def get_eg(batch: Batch, idx: int, filter_op: Optional[Callable] = None):
        """Extract example `idx` from a batch, potentially filter the keys"""
        filter_op = filter_op or always_true
        return {k: v[idx] for k, v in batch.items() if filter_op(k)}

    def batch_size(self, batch: Batch) -> int:
        return len(next(iter(batch.values())))

    def __call__(self, batch: Union[List[Batch], Batch], **kwargs) -> Batch:
        """The call of the pipeline process"""
        raise NotImplementedError

    def dill_inspect(self, reduce=True) -> bool:
        """Returns True if the module can be pickled."""
        return dill.pickles(self)

    def fingerprint(self) -> str:
        """return the fingerprint of this object"""
        return self._fingerprint(self)

    def todict(self) -> Dict[str, Any]:
        """Return a dictionary representation of the object"""
        data = {"__type__": type(self).__name__, **vars(self)}
        return _filter_null_id(data)

    def __repr__(self) -> str:
        return type(self).__name__

    @staticmethod
    def _fingerprint(x):
        """Return the fingerprint of an object."""
        hash = Hasher()
        hash.update(x)
        return hash.hexdigest()

    def copy(self, **kwargs):
        """Copy the pipe and replace attributes using kwargs"""
        obj = deepcopy(self)
        for k, v in kwargs.items():
            setattr(obj, k, v)
        return obj


class Identity(Pipe):
    """
    A pipe that passes a batch without modifying it.
    """

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        """The call of the pipeline process"""
        return batch


class Lambda(Pipe):
    """
    Apply a lambda function to the batch.
    """

    def __init__(
        self, op: Callable, output_keys: Optional[List[str]] = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.op = op
        self._output_keys = output_keys

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        """The call of the pipeline process"""
        return self.op(batch)

    def output_keys(self, input_keys: List[str]) -> List[str]:
        return self._output_keys or super().output_keys(input_keys)


class GetKey(Pipe):
    def __init__(self, key: str, **kwargs):
        super().__init__(**kwargs)
        self.key = key

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        """The call of the pipeline process"""
        return {self.key: batch[self.key]}

    def output_keys(self, input_keys: List[str]) -> List[str]:
        return [self.key]


class FilterKeys(Pipe):
    """
    Filter the keys in the batch.
    """

    def __init__(self, condition: Callable, **kwargs):
        super().__init__(**kwargs)
        self.condition = condition

    def __call__(
        self, batch: Union[List[Batch], Batch], **kwargs
    ) -> Union[List[Batch], Batch]:
        """The call of the pipeline process"""
        return self.filter(batch)

    def filter(self, batch):
        return {k: v for k, v in batch.items() if self.condition(k)}

    def output_keys(self, input_keys: List[str]) -> List[str]:
        return [k for k in input_keys if self.condition(k)]


class DropKeys(Pipe):
    """
    Filter the keys in the batch.
    """

    def __init__(self, keys: List[str], **kwargs):
        super().__init__(**kwargs)
        self.keys = keys

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        """The call of the pipeline process"""
        for key in self.keys:
            batch.pop(key)
        return batch

    def output_keys(self, input_keys: List[str]) -> List[str]:
        for key in self.keys:
            input_keys.remove(key)
        return input_keys


class AddPrefix(Pipe):
    """
    Append the keys with a prefix.
    """

    def __init__(self, prefix: str, **kwargs):
        super().__init__(**kwargs)
        self.prefix = prefix

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        """The call of the pipeline process"""
        return {f"{self.prefix}{k}": v for k, v in batch.items()}

    def output_keys(self, input_keys: List[str]) -> List[str]:
        return [f"{self.prefix}{k}" for k in input_keys]


class ReplaceInKeys(Pipe):
    """
    Remove a the prefix in each key.
    """

    def __init__(self, a: str, b: str, **kwargs):
        super().__init__(**kwargs)
        self.a = a
        self.b = b

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        """The call of the pipeline process"""
        return {k.replace(self.a, self.b): v for k, v in batch.items()}

    def output_keys(self, input_keys: List[str]) -> List[str]:
        return [k.replace(self.a, self.b) for k in input_keys]


class RenameKeys(Pipe):
    """
    Rename a set of keys
    """

    def __init__(self, keys: Dict[str, str], **kwargs):
        super().__init__(**kwargs)
        self.keys = keys

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        """The call of the pipeline process"""
        for old_key, new_key in self.keys.items():
            value = batch.pop(old_key)
            batch[new_key] = value

        return batch

    def output_keys(self, input_keys: List[str]) -> List[str]:
        return [self.keys.get(k, k) for k in input_keys]


class Apply(Pipe):
    """
    Transform the values in a batch for all transformations
    registered in `ops`: key, transformation`.
    The argument `element_wise` allows to process each value in the batch element wise.
    """

    def __init__(
        self, ops: Dict[str, Callable], element_wise: bool = False, **kwargs
    ):
        super().__init__(**kwargs)
        self.ops = ops
        self.element_wise = element_wise

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        """The call of the pipeline process"""
        for key, op in self.ops.items():
            values = batch[key]
            if self.element_wise:
                batch[key] = [op(x) for x in values]
            else:
                batch[key] = op(values)

        return batch


class ApplyToAll(Pipe):
    """
    Transform the values in a batch for all transformations
    registered in `ops`: key, transformation`.
    The argument `element_wise` allows to process each value in the batch element wise.
    """

    def __init__(self, op: Callable, element_wise: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.op = op
        self.element_wise = element_wise

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        """The call of the pipeline process"""
        for key, values in batch.items():
            if self.element_wise:
                batch[key] = [self.op(x) for x in values]
            else:
                batch[key] = self.op(values)

        return batch


class CopyBatch(Pipe):
    def __init__(self, *, deep: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.deep = deep

    def __call__(self, batch: Batch, **kwargs) -> Batch:
        if self.deep:
            return deepcopy(batch)
        else:
            return copy(batch)


def check_pickle_capability(pipe: Pipe):
    """check that the pipe can be pickled, which is necessary for multiprocessing"""
    if not pipe.dill_inspect(reduce=True):
        rich.print(pipe.dill_inspect())
        raise TypeError(
            "Couldn't pickle pipe. Code would fail if `num_proc`>1. "
            f"Make sure the pipe {pipe} can be pickled."
        )
