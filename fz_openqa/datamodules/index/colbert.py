import logging
from collections import defaultdict
from collections import OrderedDict
from copy import deepcopy
from typing import List
from typing import Optional

import faiss
import numpy as np
import rich
import torch
from datasets import Split

from fz_openqa.datamodules.index.dense import FaissIndex
from fz_openqa.datamodules.index.search_result import SearchResult
from fz_openqa.datamodules.pipes.predict import OutputFormat
from fz_openqa.datamodules.pipes.utils.nesting import flatten_nested
from fz_openqa.datamodules.pipes.utils.nesting import nested_list
from fz_openqa.utils.datastruct import Batch
from fz_openqa.utils.functional import cast_to_numpy
from fz_openqa.utils.json_struct import apply_to_json_struct
from fz_openqa.utils.pretty import pprint_batch
from fz_openqa.utils.shape import infer_shape

log = logging.getLogger(__name__)

DEF_LOADER_KWARGS = {"batch_size": 10, "num_workers": 2, "pin_memory": True}
DEFAULT_FAISS_KWARGS = {
    "metric_type": faiss.METRIC_L2,
    "n_list": 32,
    "n_subvectors": 16,
    "n_bits": 8,
}


class ColbertIndex(FaissIndex):
    tok2doc = []

    def _init_index(self, batch):
        """
        Initialize the index and train on first batch of data

        Parameters
        ----------
        vectors
            The dataset to index.
        metric_type
            Distance metric, most common is METRIC.L2
        n_list
            The number of cells (partitions). Typical values is sqrt(N)
        n_subvectors
            The number of sub-vectors. Typically this is 8, 16, 32, etc.
        n_bits
            Bits per subvector. Typically 8, so that each sub-vector is encoded by 1 byte
        dim
            The dimension of the input vectors

        """
        vectors: np.ndarray = batch[self.vectors_column_name]
        vectors = vectors.astype(np.float32)
        assert len(vectors.shape) == 3
        metric_type = self.faiss_args["metric_type"]
        n_list = self.faiss_args["n_list"]
        n_subvectors = self.faiss_args["n_subvectors"]
        n_bits = self.faiss_args["n_bits"]
        dim = vectors.shape[-1]
        assert dim % n_subvectors == 0, "m must be a divisor of dim"

        quantizer = faiss.IndexFlatL2(dim)
        self._index = faiss.IndexIVFPQ(quantizer, dim, n_list, n_subvectors, n_bits, metric_type)
        self._index.train(vectors.reshape(-1, dim))
        assert self._index.is_trained is True, "Index is not trained"
        log.info(f"Index is trained: {self._index.is_trained}")

    def _add_batch_to_index(self, batch: Batch, dtype=np.float32):
        """ Add one batch of data to the index """
        # check indexes
        # self._check_index_consistency(idx)

        # add vector to index
        pprint_batch(batch, "_add_batch_to_index")
        vector = self._get_vector_from_batch(batch)
        assert isinstance(vector, np.ndarray), f"vector {type(vector)} is not a numpy array"
        assert len(vector.shape) == 3, f"{vector} is not a 3D array"
        self._index.add(vector.reshape(-1, vector.shape[-1]))

        # store token index to original document
        for idx in batch["__idx__"]:
            n_tokens = vector.shape[1]
            self.tok2doc += n_tokens * [idx]
        rich.print(f"[red]Total number of indices: {self._index.ntotal}")

    def _search_batch(
        self,
        query: Batch,
        *,
        idx: Optional[List[int]] = None,
        split: Optional[Split] = None,
        k: int = 1,
        **kwargs,
    ) -> SearchResult:
        """
        Search the index using the `query` and
        return the index of the results within the original dataset.
        """
        # 1. get query vector
        query = self.predict_queries(query, format=OutputFormat.TORCH, idx=idx, split=split)
        query = self.postprocess(query)
        q_vectors = query[self.vectors_column_name]
        bs, q_tokens, dim = q_vectors.shape

        # 2. query the token index
        np_q_vectors = cast_to_numpy(q_vectors, as_contiguous=True)
        np_q_vectors = np_q_vectors.reshape(-1, dim)
        distances, tok_indices = self._index.search(np_q_vectors, k)

        # 3. retrieve the document indices for each token idx
        # @idariis: excellent idea with the set of indices
        # here a create a dictionary with the document_id as key and
        # the token ids as values, it allows to
        #    1. get the set of documents
        #    2. get the list of token ids attached to each document
        tok_indices_flat = tok_indices.flatten("C")
        doc_indices = defaultdict(list)
        for i in tok_indices_flat:
            doc_indices[self.tok2doc[i]] += [i]
        doc_indices = OrderedDict(doc_indices)

        # 4. retrieve the vectors for each unique document index
        # the table _vectors (pyarrow) contains the document vectors
        vectors = self._vectors.take(list(doc_indices.keys())).to_pydict()
        vectors = self.postprocess(vectors)[self.vectors_column_name]
        # create a mapping {document_idx : vector}
        doc2vec = {doc_idx: vec for doc_idx, vec in zip(doc_indices.keys(), vectors)}

        # 5.1 get the set of document indices for each batch item
        # we start from a data structure [bs*q_tokens, k], convert it into
        # a structure [bs, q_tokens * k] and keep only the unique values across dim 1
        retrieved_indices = [[self.tok2doc[i] for i in row] for row in tok_indices]
        retrieved_indices = np.array(retrieved_indices).reshape(bs, -1)
        retrieved_indices = [list(set(row.tolist())) for row in retrieved_indices]

        # 5.2 pad the values to the same length `p`
        # @Idariis: I think they use something different in the paper
        max_len = max([len(row) for row in retrieved_indices])
        pad_length = max(k, max_len)

        def pad_row(row, pad_length, pad_symbol=-1):
            return row[:pad_length] + [pad_symbol] * (pad_length - len(row))

        retrieved_indices = [pad_row(row, pad_length) for row in retrieved_indices]
        # set a default vector for the padded values (default to zero)
        eg = vectors[0]
        doc2vec[-1] = apply_to_json_struct(deepcopy(eg), lambda x: 0)

        # 6. dispatch the document vectors to their corresponding token idx
        d_vectors = [[doc2vec[i] for i in row] for row in retrieved_indices]
        d_vectors = torch.tensor(d_vectors, dtype=q_vectors.dtype, device=q_vectors.device)
        _, p, d_tokens, dim = d_vectors.shape

        # 7. apply max sim to the retrieved vectors
        scores = torch.einsum("bqh, bkdh -> bkqd", q_vectors, d_vectors)
        # max. over the documents tokens, for each query token
        scores, _ = scores.max(-1)
        # avg over all query tokens
        scores = scores.mean(-1)

        # 8. take the top-k results given the MaxSim score
        maxsim_scores, maxsim_indices = scores.topk(k, dim=-1)

        # 9. fetch the corresponding document indices and return
        maxsim_doc_indices = torch.tensor(retrieved_indices, device=q_vectors.device)
        maxsim_doc_indices = maxsim_doc_indices.gather(dim=1, index=maxsim_indices)

        return SearchResult(score=maxsim_scores, index=maxsim_doc_indices)
