from abc import ABCMeta
from abc import abstractmethod
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from datasets import Dataset
from rich.progress import track

from fz_openqa.datamodules.component import Component
from fz_openqa.datamodules.index.search_result import SearchResult
from fz_openqa.utils.datastruct import Batch


class Index(Component):
    """Keep an index of a Dataset and search u
    sing queries."""

    __metaclass__ = ABCMeta
    index_name: Optional[str] = None
    is_indexed: bool = False

    def __init__(self, dataset: Dataset, *, verbose: bool = False, **kwargs):
        super(Index, self).__init__(**kwargs)
        self.verbose = verbose
        self.dataset_size = len(dataset)
        self.build(dataset=dataset, **kwargs)

    def __repr__(self):
        params = {"is_indexed": self.is_indexed, "index_name": self.index_name}
        params = [f"{k}={v}" for k, v in params.items()]
        return f"{self.__class__.__name__}({', '.join(params)})"

    @abstractmethod
    def build(self, dataset: Dataset, **kwargs):
        """Index a dataset."""
        raise NotImplementedError

    def search_one(
        self, query: Dict[str, Any], *, k: int = 1, **kwargs
    ) -> Tuple[List[float], List[int], Optional[List[int]]]:
        """Search the index using one `query`"""
        raise NotImplementedError

    def search(self, query: Batch, *, k: int = 1, **kwargs) -> SearchResult:
        """Batch search the index using the `query` and
        return the scores and the indexes of the results
        within the original dataset.

        The default method search for each example sequentially.
        """
        batch_size = len(next(iter(query.values())))
        scores, indexes, tokens = [], [], []
        _iter = range(batch_size)
        if self.verbose:
            _iter = track(
                _iter,
                description=f"Searching {self.__name__} for batch..",
            )
        for i in _iter:
            eg = self.get_example(query, i)
            scores_i, indexes_i, tokens_i = self.search_one(eg, k=k, **kwargs)
            scores += [scores_i]
            indexes += [indexes_i]
            if tokens_i is not None:
                tokens += [tokens_i]
        tokens = None if len(tokens) == 0 else tokens
        return SearchResult(
            index=indexes, score=scores, tokens=tokens, dataset_size=self.dataset_size
        )

    def get_example(self, query: Batch, index: int) -> Dict[str, Any]:
        return {k: v[index] for k, v in query.items()}
