from copy import deepcopy
from dataclasses import dataclass
from typing import List
from typing import Optional

import dill
from datasets import Dataset

from fz_openqa.datamodules.index.base import Index
from fz_openqa.datamodules.index.base import IndexMode
from fz_openqa.datamodules.pipes import ApplyAsFlatten
from fz_openqa.datamodules.pipes.base import Pipe
from fz_openqa.datamodules.pipes.collate import Collate
from fz_openqa.datamodules.pipes.control.condition import In
from fz_openqa.utils.datastruct import Batch
from fz_openqa.utils.datastruct import Eg
from fz_openqa.utils.pretty import pprint_batch


@dataclass
class SearchResult:
    score: List[List[float]]
    index: List[List[int]]
    tokens: List[List[str]]


class FakeIndex:
    """A small class to test Search corpus without using a proper index"""

    index_name = "<name>"

    def search(self, *, query: Batch, k: int, **kwargs) -> SearchResult:
        values = query["question.text"]
        return SearchResult(
            index=[[0 for _ in range(k)] for _ in values],
            score=[[1.0 for _ in range(k)] for _ in values],
        )

    def dill_inspect(self) -> bool:
        """check if the module can be pickled."""
        return dill.pickles(self)


class FakeDataset:
    """A small class to test Search corpus without using a proper index"""

    def __init__(self):
        self.data = {"document.text": "<text>", "document.row_idx": 0}

    def __getitem__(self, idx):
        """check if the module can be pickled."""
        if isinstance(idx, str):
            return [deepcopy(self.data)]
        else:
            return deepcopy(self.data)


class SearchCorpus(ApplyAsFlatten):
    def __init__(
        self,
        index: Index,
        *,
        level: int = 0,
        **kwargs,
    ):
        assert "input_filter" not in kwargs
        self.index = index
        input_filter = In(index.input_keys(IndexMode.QUERY))
        pipe = SearchCorpusFlat(index, **kwargs)
        super().__init__(pipe, level=level, input_filter=input_filter, update_idx=True)


class SearchCorpusFlat(Pipe):
    """Search a Corpus object given a query"""

    def __init__(
        self,
        index: Index,
        *,
        k: Optional[int] = None,
        index_output_key: str = "document.row_idx",
        score_output_key: str = "document.retrieval_score",
        analyzed_output_key: str = "document.analyzed_tokens",
        **kwargs,
    ):
        super(SearchCorpusFlat, self).__init__(**kwargs)
        self.index = index
        self.index_output_key = index_output_key
        self.score_output_key = score_output_key
        self.analyzed_output_key = analyzed_output_key
        self.k = k

    def _call_batch(
        self,
        query: Batch,
        *,
        k: Optional[int] = None,
        **kwargs,
    ):
        # update args
        k = k or self.k

        # query the index
        search_result = self.index.search(query, k=k, **kwargs)

        # store as a dictionary and return
        output = {
            self.index_output_key: search_result.index,
            self.score_output_key: search_result.score,
        }

        if search_result.tokens is not None:
            output[self.analyzed_output_key] = search_result.tokens

        return output


class FetchDocuments(Pipe):
    def __init__(
        self,
        *,
        corpus_dataset: Dataset,
        keys: Optional[List[str]] = None,
        collate_pipe: Pipe = None,
        index_key: str = "document.row_idx",
        output_format: str = "dict",
        id: str = "fetch-documents-pipe",
        **kwargs,
    ):
        super(FetchDocuments, self).__init__(id=id)
        if keys is not None:
            keys.append(index_key)
            # make sure to sort the keys to ensure deterministic fingerprinting
            cols_to_drop = [c for c in corpus_dataset.column_names if c not in keys]
            corpus_dataset = corpus_dataset.remove_columns(cols_to_drop)

        self.corpus_dataset = corpus_dataset
        self.keys = keys
        self.collate_pipe = collate_pipe or Collate()
        self.index_key = index_key
        self.output_format = output_format

    def output_keys(self, input_keys: List[str]) -> List[str]:
        return self.corpus_dataset.column_names

    def _call_batch(self, batch: Batch, **kwargs) -> Batch:
        # todo: check dataset fingerprint (checking 1st index for now)

        # get the `dataset` indexes
        # todo: query dataset for unique indexes only {i: idx for i, idx in enumerate(indexes)}
        indexes = [int(idx) for idx in batch[self.index_key]]

        # fetch documents
        table = self.corpus_dataset.select(indexes, keep_in_memory=True)
        if table.num_rows != len(indexes):
            raise ValueError(
                f"The returned table does not match with the length "
                f"of the input index. Retrieved {table.num_rows} rows, "
                f"expected {len(indexes)} rows."
                f"corpus_size={len(self.corpus_dataset)}"
            )

        # convert as dicts or list of egs
        err_msg = (
            "There is a mismatch between the query indexes and the retrieved indexes, "
            "make sure you are using the same dataset."
        )
        if self.output_format == "list":
            rows: List[Eg] = [dict(row) for row in table]
            assert indexes[0] == rows[0][self.index_key], err_msg
        elif self.output_format == "dict":
            rows: Batch = table[None:None]
            assert indexes[0] == rows[self.index_key][0], err_msg
        else:
            raise ValueError(f"Unknown output format: {self.output_format}")

        # collate and return
        return self.collate_pipe(rows)


class FetchNestedDocuments(ApplyAsFlatten):
    """Retrieve the full document rows (text, input_ids, ...) from
    the corpus object given the input `index_key` for nested documents ([[input_ids]])"""

    def __init__(
        self,
        corpus_dataset: Dataset,
        collate_pipe: Pipe,
        update: bool = True,
        index_key: str = "document.row_idx",
        level: int = 1,
    ):
        pipe = FetchDocuments(
            corpus_dataset=corpus_dataset,
            collate_pipe=collate_pipe,
        )

        super().__init__(pipe=pipe, input_filter=In([index_key]), update=update, level=level)
