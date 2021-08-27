import shutil
from functools import partial
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import datasets
import rich
import torch
from datasets import DatasetDict
from datasets import load_dataset
from datasets import Split
from hydra.utils import instantiate
from omegaconf import DictConfig
from pytorch_lightning import LightningDataModule
from pytorch_lightning.utilities import rank_zero_only
from torch.utils.data import DataLoader
from torch.utils.data import Dataset
from transformers import BatchEncoding
from transformers import PreTrainedTokenizerFast

from fz_openqa.utils.datastruct import pprint_batch

HgDataset = Union[Dataset, DatasetDict]


class BaseDataModule(LightningDataModule):
    """
    A base LightningDataModule for the PennTreeBank dataset as example.
    A DataModule implements 5 key methods:
        - prepare_data (things to do on 1 GPU/TPU, not on every GPU/TPU in distributed mode)
        - setup (things to do on every accelerator in distributed mode)
        - train_dataloader (the training dataloader)
        - val_dataloader (the validation dataloader(s))
        - test_dataloader (the test dataloader(s))
    This allows you to share a full dataset without explaining how to download,
    split, transform and process the data
    Read the docs:
        https://pytorch-lightning.readthedocs.io/en/latest/extensions/datamodules.html
    """

    dset_script_path_or_id = (
        "ptb_text_only"  # HuggingFace dataset id or local path to script
    )
    text_fields = ["sentence"]  # text fields that should be tokenized
    split_ids = [
        datasets.Split.TRAIN,
        datasets.Split.VALIDATION,
        datasets.Split.TEST,
    ]  # split names
    pt_attributes = [
        "input_ids",
        "attention_mask",
    ]  # attributes to be converted into Tensors

    def __init__(
        self,
        *,
        tokenizer: PreTrainedTokenizerFast,
        add_encoding_tokens: bool = True,
        append_document_title: bool = True,
        cache_dir: str = "cache/",
        train_batch_size: int = 64,
        eval_batch_size: int = 128,
        num_workers: int = 0,
        pin_memory: bool = True,
        persistent_workers: bool = False,
        max_length: Optional[int] = 512,
        use_subset: bool = False,
        num_proc: int = 1,
        verbose: bool = True,
        corpus: Optional["BaseDataModule"] = None,
        train_sampler: Optional[DictConfig] = None,
        eval_sampler: Optional[DictConfig] = None,
        **kwargs,
    ):
        super().__init__()

        self.data_dir = cache_dir
        self.train_batch_size = train_batch_size
        self.eval_batch_size = eval_batch_size
        self.num_workers = num_workers
        self.pin_memory = pin_memory
        self.persistent_workers = persistent_workers
        self.use_subset = use_subset
        self.num_proc = num_proc
        self.verbose = verbose

        # corpus object
        self.corpus = corpus

        # tokenizer and dataset
        self.max_length = max_length
        self.tokenizer = tokenizer
        self.dataset: Optional[HgDataset] = None
        self.text_data: Optional[HgDataset] = None
        self.add_encoding_tokens = add_encoding_tokens
        self.append_document_title = append_document_title

        # sampler
        self.train_sampler_cfg = (
            dict(train_sampler)
            if train_sampler is not None and len(train_sampler)
            else None
        )
        self.eval_sampler_cfg = (
            dict(eval_sampler)
            if eval_sampler is not None and len(eval_sampler)
            else None
        )

    def tokenize_examples(
        self,
        examples: Dict[str, List[Any]],
        *,
        fields: List[str],
        output_key: Optional[str],
        tokenizer: PreTrainedTokenizerFast,
        max_length: Optional[int],
        preprocess_fn: Optional[Callable] = None,
        add_encoding_tokens: bool = True,
        **kwargs,
    ) -> Union[Dict, BatchEncoding]:
        """Tokenize a batch of examples and truncate if `max_length` is provided.
        The input format is:
        examples = {
            attribute_name: list of attribute values
        }
        """
        # preprocess
        examples = {field: examples[field] for field in fields}
        if preprocess_fn is not None:
            examples = {
                field: list(map(preprocess_fn, values))
                for field, values in examples.items()
            }

        if add_encoding_tokens:
            examples = {
                field: list(map(preprocess_fn, values))
                for field, values in examples.items()
            }

        output = tokenizer(
            *examples.values(),
            max_length=max_length,
            truncation=max_length is not None,
            **kwargs,
        )

        if output_key is None:
            return output
        else:
            return {f"{output_key}.{attr}": v for attr, v in output.items()}

    def prepare_data(self):
        """Download data if needed. This method is called only from a single GPU.
        Do not use it to assign state (self.x = y)."""
        self.load_base_dataset()
        if self.corpus is not None:
            self.corpus.prepare_data()

    def load_base_dataset(self) -> DatasetDict:
        """Load the base HuggingFace dataset."""
        return load_dataset(
            self.dset_script_path_or_id, cache_dir=self.data_dir
        )

    def setup(self, stage: Optional[str] = None):
        """Load data. Set variables: self.data_train, self.data_val, self.data_test."""
        self.text_data: HgDataset = self.load_base_dataset()
        self.text_data = self.filter_dataset(self.text_data)
        if self.use_subset:
            self.text_data = self.take_subset(self.text_data)
        self.dataset = self.preprocess_dataset(self.text_data)

        if self.verbose:
            self.pprint()
            self.display_sample()

        if self.corpus is not None:
            self.corpus.setup()

    @staticmethod
    def take_subset(dataset: HgDataset) -> HgDataset:
        """Take a subset of the dataset and return."""
        if isinstance(dataset, DatasetDict):
            return DatasetDict(
                {
                    k: dset.select(range(n))
                    for n, (k, dset) in zip([100, 10, 10], dataset.items())
                }
            )
        elif isinstance(dataset, Dataset):
            return dataset.select(range(100))
        else:
            raise NotImplementedError

    def preprocess_dataset(self, dataset: HgDataset) -> HgDataset:
        """Apply processing steps to the dataset. Tokenization and formatting as PyTorch tensors"""
        fn = partial(
            self.tokenize_examples,
            tokenizer=self.tokenizer,
            max_length=self.max_length,
        )
        dataset = dataset.map(
            fn, batched=True, num_proc=self.num_proc, desc="Tokenizing"
        )
        dataset.set_format(type="torch", columns=self.pt_attributes)
        return dataset

    def filter_dataset(self, dataset: HgDataset) -> HgDataset:
        """Apply filter operation to the dataset and return"""
        return dataset

    def pprint(self):
        """Pretty print the dtaset"""
        rich.print(
            f">> Dataset: [use_subset={self.use_subset}]: \n" f"{self.dataset}"
        )

    def train_dataloader(self):
        dset = self.dataset[Split.TRAIN]
        if self.train_sampler_cfg is not None:
            dset = instantiate(self.train_sampler_cfg, dataset=dset)

        return DataLoader(
            dataset=dset,
            batch_size=self.train_batch_size,
            num_workers=self.num_workers,
            pin_memory=self.pin_memory,
            persistent_workers=self.persistent_workers,
            shuffle=True,
            collate_fn=self.collate_fn,
        )

    def _eval_loader(self, split):
        dset = self.dataset[split]
        if self.eval_sampler_cfg is not None:
            dset = instantiate(self.eval_sampler_cfg, dataset=dset)

        return DataLoader(
            dataset=dset,
            batch_size=self.eval_batch_size,
            num_workers=self.num_workers,
            pin_memory=self.pin_memory,
            persistent_workers=self.persistent_workers,
            shuffle=False,
            collate_fn=self.collate_fn,
        )

    def val_dataloader(self):
        return self._eval_loader(Split.VALIDATION)

    def test_dataloader(self):
        return self._eval_loader(Split.TEST)

    def collate_fn(
        self, batch: Any
    ) -> Union[BatchEncoding, List[Dict[str, torch.Tensor]]]:
        """The function that is used to merge examples into a batch.
        Concatenating sequences with different length requires padding them."""
        return self.tokenizer.pad(batch)

    @staticmethod
    def _append_document_title(example: Dict[str, Any]) -> Dict[str, Any]:
        example[
            "document"
        ] = f"{example['document.title']}. {example['document']}"
        return example

    @rank_zero_only
    def display_sample(self):
        """Sample a batch and pretty print it."""
        batch = next(iter(self.train_dataloader()))
        eval_batch = next(iter(self.val_dataloader()))
        console_width, _ = shutil.get_terminal_size()
        print(console_width * "=")
        print("=== Training Batch ===")
        print(console_width * "-")
        pprint_batch(batch)
        print("=== Validation Batch ===")
        print(console_width * "-")
        pprint_batch(eval_batch)
        print(console_width * "=")
        self.display_one_sample({k: v[0] for k, v in batch.items()})

    def display_one_sample(self, example: Dict[str, torch.Tensor]):
        """Decode and print one example from the batch"""
        console_width, _ = shutil.get_terminal_size()
        print("=== Sample ===")
        print(console_width * "-")
        rich.print(
            self.repr_ex(example, "input_ids", skip_special_tokens=True)
        )
        print(console_width * "=")

    def repr_ex(self, example, key, **kwargs):
        n_pad_tokens = list(example[key]).count(self.tokenizer.pad_token_id)
        txt = self.tokenizer.decode(example[key], **kwargs)
        return (
            f"length={len(example[key])}, padding={n_pad_tokens}, "
            f"text: `{txt.replace('[PAD]', '').strip()}`"
        )
