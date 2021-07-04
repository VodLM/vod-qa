import re
from typing import Any
from typing import List
from typing import Optional
from typing import Union

from datasets import Split
from hydra.utils import instantiate
from omegaconf import DictConfig
from torch import nn
from transformers import AdamW
from transformers import BertPreTrainedModel
from transformers import PreTrainedTokenizerFast

from ...utils.functional import only_trainable
from .base import BaseModel
from fz_openqa.utils.datastruct import Batch


class MultipleChoiceQA(BaseModel):
    """A Multiple Choice model """

    _required_infer_feature_names = [
        "question.input_ids",
        "question.attention_mask",
        "question.input_ids",
        "document.attention_mask",
        "question.input_ids",
        "question.attention_mask",
        "answer_choices.input_ids",
        "answer_choices.attention_mask",
    ]
    _prog_bar_metrics = [
        "train/loss",
        "validation/loss",
        "validation/reader/Accuracy",
        "validation/retriever/Accuracy",
    ]  # metrics that will be display in the progress bar

    def __init__(
        self,
        *,
        tokenizer: PreTrainedTokenizerFast,
        bert: Union[BertPreTrainedModel, DictConfig],
        reader: Union[DictConfig, BaseModel],
        retriever: Union[DictConfig, BaseModel],
        **kwargs,
    ):
        super().__init__(**kwargs, evaluator=None)

        # instantiate the pretrained model
        self.instantiate_bert(bert=bert, tokenizer=tokenizer)

        # instantiate the reader
        self.reader: BaseModel = instantiate(
            reader, bert=self.bert, tokenizer=tokenizer
        )

        # instantiate the retriever
        self.retriever: BaseModel = instantiate(
            retriever, bert=self.bert, tokenizer=tokenizer
        )

    def _step(
        self,
        batch: Any,
        batch_idx: int,
        dataloader_idx: Optional[int],
        *,
        split: Split,
        **kwargs,
    ) -> Batch:

        # prepare the output and args
        output = {}
        kwargs = {"log_data": False, "split": split}

        # forward pass for the reader model
        reader_data = self.reader._step(
            batch, batch_idx, dataloader_idx, **kwargs
        )
        output.update({f"reader/{k}": v for k, v in reader_data.items()})

        # forward pass for the retriever model
        retriever_data = self.retriever._step(
            batch, batch_idx, dataloader_idx, **kwargs
        )
        output.update({f"retriever/{k}": v for k, v in retriever_data.items()})

        # compute the loss and return the full output
        return {
            "loss": output["reader/loss"] + output["retriever/loss"],
            **output,
        }

    def _step_end(self, output: Batch, split, log_data=True) -> Batch:

        assert "loss" in output.keys()
        output["loss"] = output["loss"].mean()

        # log the data for both the reader and the retriever
        if log_data:
            self.log_data(output, prefix=f"{split}/")

        # update the metrics for both the reader and retriever
        kwargs = {"log_data": False, "split": split}
        self.reader._step_end(
            {k.replace("reader/", ""): v for k, v in output.items()}, **kwargs
        )
        self.retriever._step_end(
            {k.replace("retriever/", ""): v for k, v in output.items()},
            **kwargs,
        )
        return output

    def _epoch_end(self, outputs: List[Any], split: Split, log_data=True):
        kwargs = {"log_data": False, "split": split}
        reader_data = self.reader._epoch_end(outputs, **kwargs)
        if log_data:
            self.log_data(reader_data, prefix=f"{split}/reader/")
        retriever_data = self.retriever._epoch_end(outputs, **kwargs)
        if log_data:
            self.log_data(retriever_data, prefix=f"{split}/retriever/")

    def configure_optimizers(self):
        """Choose what optimizers and learning-rate schedulers to use in your optimization.
        Normally you'd need one. But in the case of GANs or similar you might have multiple.
        See examples here:
            https://pytorch-lightning.readthedocs.io/en/latest/common/lightning_module.html#configure-optimizers
        """

        def filtered_params(model: nn.Module, pattern="^bert."):
            return (
                p
                for k, p in model.named_parameters()
                if not re.findall(pattern, k)
            )

        return AdamW(
            [
                {
                    "params": only_trainable(self.bert.parameters()),
                    "lr": float(self.hparams.lr),
                    "weight_decay": self.hparams.weight_decay,
                },
                {
                    "params": only_trainable(filtered_params(self.retriever)),
                    "lr": float(self.retriever.hparams.lr),
                    "weight_decay": self.retriever.hparams.weight_decay,
                },
                {
                    "params": only_trainable(filtered_params(self.reader)),
                    "lr": float(self.reader.hparams.lr),
                    "weight_decay": self.reader.hparams.weight_decay,
                },
            ],
        )
