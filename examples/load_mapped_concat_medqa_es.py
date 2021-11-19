from pathlib import Path

import datasets
import hydra
import rich

import fz_openqa
from fz_openqa import configs
from fz_openqa.datamodules.builders import ConcatMedQaBuilder
from fz_openqa.datamodules.builders import ConcatOpenQabuilder
from fz_openqa.datamodules.builders import MedQaCorpusBuilder
from fz_openqa.datamodules.datamodule import DataModule
from fz_openqa.datamodules.index.builder import ElasticSearchIndexBuilder
from fz_openqa.datamodules.pipes import ExactMatch
from fz_openqa.datamodules.pipes import TextFormatter
from fz_openqa.tokenizers.pretrained import init_pretrained_tokenizer


@hydra.main(
    config_path=str(Path(configs.__file__).parent),
    config_name="script_config.yaml",
)
def run(config):
    datasets.set_caching_enabled(True)

    # define the default cache location
    default_cache_dir = Path(fz_openqa.__file__).parent.parent / "cache"

    # tokenizer and text formatter
    tokenizer = init_pretrained_tokenizer(pretrained_model_name_or_path="bert-base-cased")
    text_formatter = TextFormatter(lowercase=True)

    # define the medqa builder
    dataset_builder = ConcatMedQaBuilder(
        tokenizer=tokenizer,
        text_formatter=text_formatter,
        use_subset=config.get("use_subset", True),
        cache_dir=config.get("cache_dir", default_cache_dir),
        num_proc=4,
    )
    dataset_builder.subset_size = [200, 50, 50]

    # define the corpus builder
    corpus_builder = MedQaCorpusBuilder(
        tokenizer=tokenizer,
        text_formatter=text_formatter,
        use_subset=False,
        cache_dir=config.get("cache_dir", default_cache_dir),
        num_proc=4,
    )

    # define the OpenQA builder
    builder = ConcatOpenQabuilder(
        dataset_builder=dataset_builder,
        corpus_builder=corpus_builder,
        index_builder=ElasticSearchIndexBuilder(query_field="qa"),
        relevance_classifier=ExactMatch(interpretable=True),
        n_retrieved_documents=100,
        n_documents=20,
        max_pos_docs=10,
        filter_unmatched=True,
        num_proc=2,
        batch_size=50,
    )

    # define the data module
    dm = DataModule(builder=builder)

    # preprocess the data
    dm.prepare_data()
    dm.setup()
    dm.display_samples(n_samples=3)

    # access dataset
    rich.print(dm.dataset)

    # sample a batch
    # _ = next(iter(dm.train_dataloader()))


if __name__ == "__main__":
    run()
