from copy import copy
from typing import Any
from typing import Dict

from fz_openqa.datamodules.builders import DatasetBuilder
from fz_openqa.datamodules.pipes.control.condition import HasPrefix
from fz_openqa.datamodules.pipes.nesting import Expand
from fz_openqa.utils.pretty import get_separator
from fz_openqa.utils.pretty import pretty_decode


def format_row_flat_questions(
    row: Dict[str, Any], *, tokenizer, dataset_builder: DatasetBuilder, **kwargs
) -> str:
    decode_kwargs = {
        "skip_special_tokens": False,
        "tokenizer": tokenizer,
    }

    repr = dataset_builder.format_row(row)
    repr += get_separator("-") + "\n"
    repr += f"* Documents: n={len(row['document.text'])}"
    if "document.match_score" in row:
        repr += f", n_positive={sum(row['document.match_score'] > 0)}, "
        f"n_negative={sum(row['document.match_score'] == 0)}\n"
    repr += "\n"
    for j in range(min(len(row["document.text"]), 3)):
        repr += get_separator(".") + "\n"
        match_on = row.get("document.match_on", None)
        match_on = match_on[j] if match_on is not None else None
        match_score = row.get("document.match_score", None)
        match_score = match_score[j] if match_score is not None else None
        repr += (
            f"|-* Document #{1 + j}, "
            f"score={row['document.retrieval_score'][j]:.2f}, "
            f"match_score={match_score}, "
            f"match_on={match_on}\n"
        )

        repr += (
            pretty_decode(
                row["document.input_ids"][j],
                **decode_kwargs,
                style="white",
            )
            + "\n"
        )

    return repr


def format_row_nested_questions(
    row: Dict[str, Any], *, tokenizer, document_nesting_level: int, **kwargs
) -> str:
    decode_kwargs = {
        "skip_special_tokens": False,
        "tokenizer": tokenizer,
    }
    row = copy(row)

    repr = f"* Question #{row.get('question.idx', None)}\n"
    idx = row["answer.target"]

    # for each question-answer pair
    for i, an in enumerate(row["question.input_ids"]):
        locator = f"QA #{i + 1}"
        repr += get_separator("-") + "\n"
        repr += f"|-* {locator}\n"
        # print question-answer pair
        an_style = "green" if idx == i else "cyan"
        line = (
            f"   - ({'x' if idx == i else ' '}) "
            f"{pretty_decode(an, **decode_kwargs, only_text=False, style=an_style)}\n"
        )
        repr += line

        if document_nesting_level == 2:
            # print documents attached to the question-answer pair
            document_row = {k: v[i] for k, v in row.items() if k.startswith("document.")}
            repr += repr_documents(document_row, locator, **decode_kwargs)

    if document_nesting_level == 1:
        repr += repr_documents(row, "", **decode_kwargs)

    return repr


def repr_documents(row, locator, **decode_kwargs) -> str:
    """represent a row of documents"""
    repr = ""
    repr += get_separator(".") + "\n"
    repr += f"|-* {locator} - Documents: n={len(row['document.input_ids'])}"
    if "document.match_score" in row:
        repr += (
            f", n_positive={sum(row['document.match_score'] > 0)}, "
            f"n_negative={sum(row['document.match_score'] == 0)}"
        )
    repr += "\n"
    # for each document
    for j in range(min(len(row["document.input_ids"]), 5)):
        match_on = row.get("document.match_on", None)
        match_on = match_on[j] if match_on is not None else None
        repr += f"|---* {locator} - Document #{1 + j} "
        repr += f"(id={row['document.idx'][j]}, row_idx={row['document.row_idx'][j]}), "
        repr += f"score={row['document.retrieval_score'][j]:.2f}, "
        if "document.match_score" in row:
            repr += f"match_score={row['document.match_score'][j]}, " f"match_on={match_on}"
        if "document.question_idx" in row:
            repr += f", question_idx={row['document.question_idx'][j]}"
        repr += "\n"

        doc_style = "yellow" if match_on else "white"
        repr += (
            pretty_decode(
                row["document.input_ids"][j],
                **decode_kwargs,
                style=doc_style,
            )
            + "\n"
        )
    return repr
