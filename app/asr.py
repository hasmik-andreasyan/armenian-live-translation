"""Armenian speech recognition with omniASR-CTC-300M-v2 (Hugging Face conversion).

Input:  float32 mono audio at 16 kHz (1-D numpy array).
Output: AsrResult(text, seconds, unknown_tokens).

Decoding is greedy CTC done by hand, exactly as the converter's parity check
does: take the most likely token per frame, merge repeats, drop the blank.
The vocabulary is character-level and uses a plain space between words.

Loads only from a local folder (local_files_only=True): no network at runtime.
"""

import gc
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


@dataclass
class AsrResult:
    text: str
    seconds: float
    unknown_tokens: int


def greedy_ctc_decode(ids: list[int], id_to_token: dict[int, str], blank_id: int,
                      drop_ids: set[int], unk_id: int) -> tuple[str, int]:
    """Merge repeated ids, remove blank/special ids, join the characters."""
    pieces, unknown, prev = [], 0, None
    for i in ids:
        if i != prev and i != blank_id and i not in drop_ids:
            if i == unk_id:
                unknown += 1
            else:
                pieces.append(id_to_token[i])
        prev = i
    text = " ".join("".join(pieces).split())  # collapse repeated spaces
    return text, unknown


class OmniCtcAsr:
    def __init__(self, model_dir: Path, threads: int = 4, precision: str = "int8") -> None:
        import torch
        from transformers import Wav2Vec2ForCTC

        if precision not in ("fp32", "int8"):
            raise ValueError(f"precision must be 'fp32' or 'int8', got {precision!r}")
        torch.set_num_threads(threads)
        self._torch = torch
        model = Wav2Vec2ForCTC.from_pretrained(model_dir, local_files_only=True).eval()
        if precision == "int8":
            model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
            gc.collect()  # free the float32 copy
        self.model = model
        self.precision = precision

        vocab = json.loads((Path(model_dir) / "vocab.json").read_text(encoding="utf-8"))
        self.id_to_token = {i: t for t, i in vocab.items()}
        self.blank_id = vocab["<s>"]
        self.unk_id = vocab["<unk>"]
        self.drop_ids = {vocab["<pad>"], vocab["</s>"]}

    def transcribe(self, audio: np.ndarray) -> AsrResult:
        if audio.ndim != 1 or audio.dtype != np.float32:
            raise ValueError(f"expected 1-D float32 audio, got shape {audio.shape} dtype {audio.dtype}")
        if len(audio) < SAMPLE_RATE // 10:
            raise ValueError("audio shorter than 0.1 s")
        t0 = time.perf_counter()
        # Same per-utterance normalisation as Wav2Vec2FeatureExtractor(do_normalize=True)
        x = (audio - audio.mean()) / np.sqrt(audio.var() + 1e-7)
        with self._torch.inference_mode():
            logits = self.model(self._torch.from_numpy(x)[None]).logits[0]
        ids = logits.argmax(dim=-1).tolist()
        text, unknown = greedy_ctc_decode(ids, self.id_to_token, self.blank_id, self.drop_ids, self.unk_id)
        return AsrResult(text=text, seconds=time.perf_counter() - t0, unknown_tokens=unknown)
