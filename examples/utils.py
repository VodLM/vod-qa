from typing import Dict

import rich
import torch

from fz_openqa.datamodules.corpus_dm import HgDataset
from fz_openqa.utils.pretty import get_separator
from fz_openqa.utils.pretty import pprint_batch


def gen_example_query(tokenizer):
    query = [
        "What is the symptoms of post polio syndrome?",
        "What are the symptoms of diabetes?",
    ]
    batch_encoding = tokenizer(query)
    query = {
        **tokenizer.pad(
            {
                k: [torch.tensor(vv) for vv in v]
                for k, v in batch_encoding.items()
            }
        ),
        "text": query,
    }
    return {f"question.{k}": v for k, v in query.items()}


def display_search_results(corpus: HgDataset, queries: Dict, results: Dict):
    pprint_batch(results)
    print(get_separator())
    for idx, (qst, row_idxs) in enumerate(
        zip(queries["question.text"], results["document.row_idx"])
    ):
        print(get_separator("-"))
        rich.print(f"#{idx}: [magenta]{qst}")
        for i, row_idx in enumerate(row_idxs):
            rich.print(f"# index={i}")
            print(corpus[row_idx]["document.text"].strip())
