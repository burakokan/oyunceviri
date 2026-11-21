import os
import re
import sys
from pathlib import Path

# ctranslate2 loads cuBLAS from PATH at first GPU use; the pip wheel keeps it inside the venv.
# (installed app: the same DLLs sit in nvidia/cublas/bin next to the exe)
for _cublas in (Path(sys.prefix) / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin",
                Path(sys.prefix) / "nvidia" / "cublas" / "bin"):
    if _cublas.is_dir():
        os.environ["PATH"] = str(_cublas) + os.pathsep + os.environ.get("PATH", "")
        break

import ctranslate2  # noqa: E402
import sentencepiece as spm  # noqa: E402

from .config import ROOT  # noqa: E402

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _first_existing(path, *names):
    return str(next(path / n for n in names if (path / n).exists()))


class LocalTranslator:
    """EN->TR with a Marian-style model on CTranslate2.

    opus-mt-tc-big-en-tr: ~38 ms per line on the GPU, more natural Turkish.
    quickmt-en-tr: ~15 ms, but more literal and sometimes drops words.
    Both are sentence-level and drop trailing sentences, so each line is split
    into sentences and translated as one batch.
    """

    def __init__(self, model, device="cuda", compute_type="float16", beam_size=2):
        path = Path(model)
        if not path.is_absolute():
            path = ROOT / path
        self.beam_size = beam_size
        # The vocabularies are read by Python and handed over as bytes: SentencePiece cannot open a file whose path
        # has letters outside plain ASCII on Windows (a user name like "Ali Şık" in the install folder), so the
        # translation model did not load at all there.
        self.src = spm.SentencePieceProcessor(
            model_proto=Path(_first_existing(path, "source.spm", "src.spm.model")).read_bytes())
        self.tgt = spm.SentencePieceProcessor(
            model_proto=Path(_first_existing(path, "target.spm", "tgt.spm.model")).read_bytes())
        try:
            self.model = ctranslate2.Translator(str(path), device=device, compute_type=compute_type)
            self.device = device
        except Exception:
            self.model = ctranslate2.Translator(str(path), device="cpu", compute_type="int8")
            self.device = "cpu"
        self.cache = {}
        self.translate("Warm up.")

    def translate(self, text):
        if text in self.cache:
            return self.cache[text]
        sentences = [s for s in _SENTENCE_END.split(text.strip()) if s]
        if not sentences:
            return ""
        batch = [self.src.encode(s, out_type=str) for s in sentences]
        results = self.model.translate_batch(batch, beam_size=self.beam_size, max_decoding_length=160)
        out = " ".join(self.tgt.decode(r.hypotheses[0]) for r in results)
        self.cache[text] = out
        return out
