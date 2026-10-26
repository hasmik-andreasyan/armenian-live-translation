"""Speaker identification for the call side (system audio).

SpeakerEmbedder: audio segment → L2-normalised voice embedding (sherpa-onnx,
                 WeSpeaker ResNet34-LM trained on VoxCeleb).
SpeakerTracker:  online clustering with stable labels "Speaker 1", "Speaker 2", ...

Why centring (CAL-01): through one call channel, raw embeddings of DIFFERENT
people are very similar (pairwise cosine 0.46–0.94, median 0.77). The shared
codec/room/recording chain dominates. Subtracting a mean embedding removes
that shared part, and the speaker differences become visible. The mean starts
from a prior (estimated offline from other recordings, so it's stable from
the first phrase) and is updated with every phrase of the session:
    m = (prior_weight * prior_mean + sum(session embeddings)) / (prior_weight + n)
With prior_mean=None the tracker works on raw embeddings (no centring).

Decision rule per phrase (cosine in the centred space):
  best similarity ≥ threshold          → that speaker
  else, ≥ min_new_speech_s of speech   → a new speaker (up to max_speakers)
  else                                 → closest speaker, marked uncertain
"""

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


def unit(x: np.ndarray) -> np.ndarray:
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9)


@dataclass
class SpeakerMatch:
    label: str
    similarity: float     # cosine (centred space) to the chosen speaker; 1.0 for a new one
    new: bool
    uncertain: bool


class SpeakerEmbedder:
    def __init__(self, model_path: Path, threads: int = 4) -> None:
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model_path), num_threads=threads,
                                                            debug=False, provider="cpu")
        if not config.validate():
            raise ValueError(f"invalid speaker model config: {config}")
        self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.dim = self.extractor.dim

    def embed(self, audio: np.ndarray) -> tuple[np.ndarray, float]:
        """Return (normalised embedding, seconds taken). Raises ValueError if too short."""
        t0 = time.perf_counter()
        stream = self.extractor.create_stream()
        stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=audio)
        stream.input_finished()
        if not self.extractor.is_ready(stream):
            raise ValueError("segment too short for a speaker embedding")
        e = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        return unit(e), time.perf_counter() - t0


class CallSpeakerLabeler:
    """Label for a segment: mic → "Me"; loopback → embedding + tracker → "Speaker N".

    Details (similarity, new/uncertain, embedding time) go into segment.meta["speaker"]
    so the pipeline can log them. A segment too short to embed gets "Speaker ?".
    """

    def __init__(self, embedder: "SpeakerEmbedder", tracker: "SpeakerTracker") -> None:
        self.embedder = embedder
        self.tracker = tracker

    def __call__(self, segment) -> str:
        if segment.source == "mic":
            return "Me"
        try:
            emb, seconds = self.embedder.embed(segment.audio)
        except ValueError:
            segment.meta["speaker"] = {"error": "too short"}
            return "Speaker ?"
        m = self.tracker.assign(emb, segment.speech_s)
        segment.meta["speaker"] = {"similarity": round(m.similarity, 3), "new": m.new, "uncertain": m.uncertain,
                                   "embed_s": round(seconds, 3)}
        return m.label


class SpeakerTracker:
    def __init__(self, threshold: float, min_new_speech_s: float = 1.0, max_speakers: int = 8,
                 prior_mean: np.ndarray | None = None, prior_weight: float = 30.0, prefix: str = "Speaker",
                 confirm_new: bool = False, pending_ttl: int = 5) -> None:
        """confirm_new (D-033): an unmatched phrase only becomes a *candidate*. A new speaker is
        created when a later unmatched phrase (within `pending_ttl` phrases) matches a candidate.
        One-off outliers then never become speakers."""
        self.threshold = threshold
        self.min_new_speech_s = min_new_speech_s
        self.max_speakers = max_speakers
        self.prior_mean = None if prior_mean is None else np.asarray(prior_mean, dtype=np.float64)
        self.prior_weight = prior_weight
        self.prefix = prefix
        self.confirm_new = confirm_new
        self.pending_ttl = pending_ttl
        self._all: list[np.ndarray] = []          # every embedding seen (for the session mean)
        self._members: list[list[np.ndarray]] = []  # confident embeddings per speaker
        self._pending: list[tuple[int, np.ndarray]] = []  # (phrase index, embedding) awaiting confirmation

    @property
    def counts(self) -> list[int]:
        return [len(m) for m in self._members]

    def _label(self, i: int) -> str:
        return f"{self.prefix} {i + 1}"

    def _mean(self) -> np.ndarray:
        if self.prior_mean is None:
            return np.zeros_like(self._all[0])
        return (self.prior_weight * self.prior_mean + np.sum(self._all, axis=0)) / (self.prior_weight + len(self._all))

    def assign(self, emb: np.ndarray, speech_s: float) -> SpeakerMatch:
        emb = unit(np.asarray(emb, dtype=np.float64))
        self._all.append(emb)
        if not self._members:
            self._members.append([emb])
            return SpeakerMatch(self._label(0), 1.0, new=True, uncertain=False)
        m = self._mean()
        x = unit(emb - m)
        centroids = np.stack([unit(unit(np.stack(mem) - m).mean(axis=0)) for mem in self._members])
        sims = centroids @ x
        best = int(np.argmax(sims))
        if sims[best] >= self.threshold:
            self._members[best].append(emb)
            return SpeakerMatch(self._label(best), float(sims[best]), new=False, uncertain=False)
        can_create = speech_s >= self.min_new_speech_s and len(self._members) < self.max_speakers
        if can_create and not self.confirm_new:
            self._members.append([emb])
            return SpeakerMatch(self._label(len(self._members) - 1), 1.0, new=True, uncertain=False)
        if can_create:
            now = len(self._all)
            self._pending = [(i, e) for i, e in self._pending if now - i <= self.pending_ttl]
            for j, (_, cand) in enumerate(self._pending):
                if float(unit(cand - m) @ x) >= self.threshold:      # a second, similar unmatched phrase
                    self._pending.pop(j)
                    self._members.append([cand, emb])
                    return SpeakerMatch(self._label(len(self._members) - 1), 1.0, new=True, uncertain=False)
            self._pending.append((now, emb))
        return SpeakerMatch(self._label(best), float(sims[best]), new=False, uncertain=True)
