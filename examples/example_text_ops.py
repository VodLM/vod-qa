import numpy as np
import rich, json, os, sys

current_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from fz_openqa.datamodules.corpus_dm import MedQaCorpusDataModule, FzCorpusDataModule
from fz_openqa.datamodules.meqa_dm import MedQaDataModule
from fz_openqa.tokenizers.pretrained import init_pretrained_tokenizer

tokenizer = init_pretrained_tokenizer(pretrained_model_name_or_path='bert-base-cased')

# load the corpus object
corpus = MedQaCorpusDataModule(tokenizer=tokenizer,
                               passage_length=200,
                               passage_stride=100,
                               append_document_title=False,
                               num_proc=4,
                               use_subset=True,
                               verbose=False)
corpus.prepare_data()
corpus.setup()
rich.print(corpus.dataset['document.text'])
