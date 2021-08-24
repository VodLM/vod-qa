from collections import defaultdict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

import torch
from transformers import PreTrainedTokenizerFast

from .utils import nested_list
from fz_openqa.utils.datastruct import Batch

ENCODING_ATTRIBUTES = ["input_ids", "attention_mask"]
DEFAULT_ANSWER_COLUMNS = ["answer_0", "answer_1", "answer_2", "answer_3"]


def collate_simple_attributes_by_key(examples, *, key: str):
    """collate simple attributes such as the index"""
    return torch.tensor([ex[key] for ex in examples])


def collate_and_pad_attributes(
    examples: List[Batch],
    *,
    tokenizer: PreTrainedTokenizerFast,
    key: Optional[str],
    exclude: Optional[Union[str, List[str]]] = None,
) -> Batch:
    """
    Collate the input encodings for a given key (e.g. "document", "question", ...)
    using `PreTrainedTokenizerFast.pad`. Check the original documentation to see what types are
    compatible. Return a Batch {'key.x' : ...., 'key.y': ....}
    """
    if isinstance(exclude, str):
        exclude = [exclude]
    if exclude is None:
        exclude = []

    # remove the key, so the tokenizer receives the attributes without the key prefix
    tokenizer_inputs = [
        {
            k.replace(f"{key}.", ""): v
            for k, v in ex.items()
            if (key is not None and f"{key}." in k)
            and (len(exclude) == 0 or all(ex not in k for ex in exclude))
        }
        for ex in examples
    ]

    # collate using the tokenizer
    output = tokenizer.pad(tokenizer_inputs)

    # re-append the key prefix
    return {f"{key}.{k}": v for k, v in output.items()}


def extract_and_collate_attributes_as_list(
    examples: List[Batch],
    *,
    attribute: str,
    key: Optional[str] = None,
) -> Tuple[List[Batch], Batch]:
    """
    Extract the attribute fields (e.g. `document.text`) from a list of Examples
    and return all fields as a Batch `{'document.{attribute}': ["...", "..."]}`.
    The target attributes are removed from the original examples
    """

    text_keys = [
        k
        for k in examples[0].keys()
        if f".{attribute}" in k and f"{key}." in k
    ]

    text_outputs = defaultdict(list)
    for ex in examples:
        for key in text_keys:
            text_outputs[key] += [ex.pop(key)]

    return examples, text_outputs


def collate_nested_examples(
    examples: List[List[Batch]],
    *,
    key: str,
    tokenizer: PreTrainedTokenizerFast,
):
    """
    Collate a list of list of examples, typically used when one
    example features multiple documents.
    """
    # infer batch_size and leaf size
    n_options = len(examples[0])
    batch_size = len(examples)

    # flatten examples
    flattened_examples = [sub_ex for ex in examples for sub_ex in ex]

    # get the raw text inputs, extract and collate
    (
        flattened_examples,
        document_output,
    ) = extract_and_collate_attributes_as_list(
        flattened_examples, attribute="text", key=key
    )

    # collate the tensor attributes: input_ids, idx, ...
    document_output.update(
        **collate_and_pad_attributes(
            flattened_examples, tokenizer=tokenizer, key=key, exclude="text"
        )
    )

    # reshape document data as shape [batch_size, n_docs, ...]
    return {
        k: v.view(batch_size, n_options, *v.shape[1:])
        if isinstance(v, torch.Tensor)
        else nested_list(v, stride=n_options)
        for k, v in document_output.items()
    }


def collate_answer_options(
    examples: List[Batch],
    *,
    tokenizer: PreTrainedTokenizerFast,
    answer_columns: Optional[List] = None,
    input_attributes: Optional[List[str]] = None,
) -> Batch:
    """
    Collate the answer options, registered as separate fields ["answer_0.x", "answer_1.x", ...].
    The return `answer_choices` tensor is of shape [batch_size, n_options, ...]"""
    ans_cols = answer_columns or DEFAULT_ANSWER_COLUMNS
    input_attributes = input_attributes or ENCODING_ATTRIBUTES
    batch_size = len(examples)
    n_ans = len(ans_cols)
    ans_encoding = tokenizer.pad(
        {
            attr: [ex[f"{ans}.{attr}"] for ans in ans_cols for ex in examples]
            for attr in input_attributes
        }
    )
    output = {}
    for k, v in ans_encoding.items():
        output[f"answer_choices.{k}"] = (
            v.view(n_ans, batch_size, -1).permute(1, 0, 2).contiguous()
        )

    return output
