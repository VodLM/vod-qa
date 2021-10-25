from fz_openqa.datamodules.pipes import FilterKeys
from fz_openqa.datamodules.pipes import Nested
from fz_openqa.datamodules.pipes import Sequential
from fz_openqa.datamodules.pipes import Sort
from fz_openqa.datamodules.utils.filter_keys import KeyWithPrefix


class SortDocuments(Sequential):
    # todo: check that this works as expected
    def __init__(self):
        super().__init__(
            FilterKeys(KeyWithPrefix("document.")),
            Nested(
                Sequential(
                    Sort(key="document.retrieval_score", reversed=True),
                    Sort(key="document.match_score", reversed=True),
                )
            ),
            id="sort-documents",
        )
