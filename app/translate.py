"""Armenian → English translation with NLLB-200-distilled-600M (CTranslate2).

Input:  Armenian text (any casing/punctuation).
Output: MtResult(text, seconds, output_tokens).

Runs fully offline from local folders:
  model_dir     : a CTranslate2 conversion (models/nllb-600m-ct2-int8 or -float32)
  tokenizer_dir : Meta's original files (models/facebook__nllb-200-distilled-600M)
"""

import time
from dataclasses import dataclass
from pathlib import Path

SRC_LANG = "hye_Armn"
TGT_LANG = "eng_Latn"


@dataclass
class MtResult:
    text: str
    seconds: float
    output_tokens: int


class NllbTranslator:
    def __init__(self, model_dir: Path, tokenizer_dir: Path, compute_type: str = "int8", threads: int = 4) -> None:
        import ctranslate2
        from transformers import AutoTokenizer

        self.translator = ctranslate2.Translator(str(model_dir), device="cpu", compute_type=compute_type,
                                                 intra_threads=threads, inter_threads=1)
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_dir, local_files_only=True, src_lang=SRC_LANG)
        self.compute_type = compute_type

    def translate(self, text: str, beam_size: int = 4) -> MtResult:
        if not text.strip():
            raise ValueError("empty input text")
        t0 = time.perf_counter()
        source = self.tokenizer.convert_ids_to_tokens(self.tokenizer.encode(text))
        result = self.translator.translate_batch([source], target_prefix=[[TGT_LANG]], beam_size=beam_size)
        tokens = result[0].hypotheses[0]
        if tokens and tokens[0] == TGT_LANG:
            tokens = tokens[1:]
        english = self.tokenizer.decode(self.tokenizer.convert_tokens_to_ids(tokens), skip_special_tokens=True)
        return MtResult(text=english, seconds=time.perf_counter() - t0, output_tokens=len(tokens))
