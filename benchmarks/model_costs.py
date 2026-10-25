"""Back-of-envelope compute cost of the ASR candidates.

Counts multiply-accumulate operations (MACs) from each model's architecture
for one phrase of a given length. 1 MAC = 2 FLOPs.

These numbers are for *ranking* candidates and for turning a measured CPU
throughput into a rough time prediction. They are not a substitute for timing
the real model (see DECISIONS.md, D-007).

Assumptions are written next to the code so they can be challenged.
"""

from dataclasses import dataclass

# Whisper always pads its input to a 30 s window = 1500 encoder positions.
WHISPER_ENCODER_POSITIONS = 1500
WHISPER_MEL_FRAMES = 3000
# ASSUMPTION: ~12 output tokens per second of Armenian speech. Whisper's
# byte-level vocabulary has few Armenian merges, so Armenian needs many tokens.
WHISPER_TOKENS_PER_SECOND = 12

# wav2vec2-style CTC models (MMS, Omnilingual) produce one frame per 20 ms.
CTC_FRAMES_PER_SECOND = 50
# The 7-layer convolutional feature extractor costs ~2.45 GMAC per second of
# 16 kHz audio (computed from its layer shapes: 512 channels, strides 5,2,2,2,2,2,2).
CTC_CNN_MACS_PER_SECOND = 2.45e9


@dataclass(frozen=True)
class WhisperArch:
    name: str
    d_model: int
    encoder_layers: int
    decoder_layers: int
    n_mels: int = 128
    vocab: int = 51866


@dataclass(frozen=True)
class CtcArch:
    name: str
    d_model: int
    layers: int
    vocab: int
    ffn_mult: int = 4


WHISPER_MODELS = [
    WhisperArch("Whisper large-v3 / BuzzASR", 1280, 32, 32),
    WhisperArch("Whisper large-v3-turbo", 1280, 32, 4),
    WhisperArch("Whisper medium", 1024, 24, 24, n_mels=80),
    WhisperArch("Whisper small", 768, 12, 12, n_mels=80),
]

CTC_MODELS = [
    CtcArch("omniASR-CTC-1B / MMS-1b-all", 1280, 48, vocab=10288),
    CtcArch("omniASR-CTC-300M", 1024, 24, vocab=10288),
]


def _transformer_layer_macs(d: int, positions: int, ffn_mult: int = 4) -> float:
    """One transformer layer: Q/K/V/O projections + feed-forward + attention."""
    projections = 4 * d * d * positions
    feed_forward = 2 * ffn_mult * d * d * positions
    attention = 2 * positions * positions * d
    return projections + feed_forward + attention


def whisper_costs(arch: WhisperArch, phrase_seconds: float) -> dict:
    """Return encoder MACs, decoder MACs and bytes read per token (int8 weights).

    The encoder cost does NOT depend on phrase length (fixed 30 s window).
    """
    d, t = arch.d_model, WHISPER_ENCODER_POSITIONS
    conv_stem = arch.n_mels * d * 3 * WHISPER_MEL_FRAMES + d * d * 3 * t
    encoder = arch.encoder_layers * _transformer_layer_macs(d, t) + conv_stem

    tokens = WHISPER_TOKENS_PER_SECOND * phrase_seconds
    cross_attention_kv = arch.decoder_layers * 2 * d * d * t  # once per call
    per_token = arch.decoder_layers * 14 * d * d + d * arch.vocab
    decoder = cross_attention_kv + per_token * tokens

    return {
        "encoder_macs": encoder,
        "decoder_macs": decoder,
        "tokens": tokens,
        # Greedy decoding at batch size 1 reads (roughly) every decoder weight
        # once per token, so it is limited by memory bandwidth, not compute.
        "decoder_bytes_per_token_int8": per_token,
    }


def ctc_costs(arch: CtcArch, phrase_seconds: float) -> dict:
    """Return total MACs for a CTC model. Cost grows with phrase length."""
    d = arch.d_model
    frames = int(CTC_FRAMES_PER_SECOND * phrase_seconds)
    cnn = CTC_CNN_MACS_PER_SECOND * phrase_seconds
    transformer = arch.layers * _transformer_layer_macs(d, frames, arch.ffn_mult)
    positional_conv = d * (d / 16) * 128 * frames  # grouped conv, kernel 128, 16 groups
    output_head = d * arch.vocab * frames
    return {"total_macs": cnn + transformer + positional_conv + output_head}


def predict_seconds(macs_per_second: float, bytes_per_second: float, phrase_seconds: float) -> list[dict]:
    """Predict ASR time per phrase from a measured throughput and memory bandwidth."""
    rows = []
    for arch in WHISPER_MODELS:
        c = whisper_costs(arch, phrase_seconds)
        compute_s = (c["encoder_macs"] + c["decoder_macs"]) / macs_per_second
        memory_s = c["decoder_bytes_per_token_int8"] * c["tokens"] / bytes_per_second
        rows.append({
            "model": arch.name,
            "gmacs": round((c["encoder_macs"] + c["decoder_macs"]) / 1e9),
            "seconds": round(compute_s + memory_s, 2),
            "scales_with_length": False,
        })
    for arch in CTC_MODELS:
        c = ctc_costs(arch, phrase_seconds)
        rows.append({
            "model": arch.name,
            "gmacs": round(c["total_macs"] / 1e9),
            "seconds": round(c["total_macs"] / macs_per_second, 2),
            "scales_with_length": True,
        })
    return rows
