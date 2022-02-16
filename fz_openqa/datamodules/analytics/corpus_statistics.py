from __future__ import annotations

from typing import Dict
from typing import List
from typing import Optional

from datasets import Dataset
from datasets import Split

from .base import Analytic


class ReportCorpusStatistics(Analytic):
    """Count the number of documents, tokens, and vocab size for a given corpus"""

    requires_columns: List[str] = ["document.text"]
    output_file_name: str = "corpus_statistics.json"

    def process_dataset_split(
        self, dset: Dataset, *, split: Optional[str | Split] = None
    ) -> Dict | List:
        """
        Report on a specific split of the dataset.
        """
        documents = dset["document.text"]
        tokens = [token for doc in documents for token in doc.split()]
        vocab = set(tokens)
        return {
            "paragraphs": len(documents),
            "tokens": len(tokens),
            "vocab": len(vocab),
        }
