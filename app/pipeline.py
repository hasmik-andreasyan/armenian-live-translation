"""Live pipeline: audio chunks → segments → ASR → MT → printed result.

Threads:
  capture (PortAudio callbacks, app/audio.py)  → chunk_queue
  segment_loop: one Segmenter per source       → segment_queue
  process_loop: ONE worker (4 CPU cores are shared, so models never run in
                parallel): ASR → label → MT → print → log

Latency is measured per segment from the end of speech (Segment.t_end) to
the moment the English line is printed, using the shared session clock.
"""

import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from app.audio import AudioChunk
from app.translate import MtResult
from app.vad import Segment, Segmenter

UNCLEAR_EN = "[unclear speech, not translated]"


@dataclass
class Result:
    label: str
    t_start: float
    hy: str
    en: str
    latency_s: float
    timings: dict


def format_clock(seconds: float) -> str:
    s = int(max(seconds, 0.0))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def format_result(r: Result, show_latency: bool = True) -> str:
    head = f"[{format_clock(r.t_start)}] {r.label}"
    if show_latency:
        head += f"   ({r.latency_s:.1f} s)"
    return f"{head}\n  HY: {r.hy}\n  EN: {r.en}\n"


def segment_loop(chunk_q: queue.Queue, seg_q: queue.Queue, segmenters: dict[str, Segmenter],
                 clock: Callable[[], float], stop: threading.Event, done: threading.Event,
                 recorder=None) -> None:
    """Runs until `stop`, then drains the chunk queue, flushes open phrases and sets `done`."""
    while not (stop.is_set() and chunk_q.empty()):
        try:
            chunk: AudioChunk = chunk_q.get(timeout=0.1)
        except queue.Empty:
            continue
        if recorder is not None:
            recorder.write(chunk.source, chunk.t_start, chunk.samples)
        for seg in segmenters[chunk.source].push(chunk.t_start, chunk.samples):
            seg.meta["t_emitted"] = clock()
            seg_q.put(seg)
    for segmenter in segmenters.values():        # end of session: emit open phrases
        for seg in segmenter.flush():
            seg.meta["t_emitted"] = clock()
            seg_q.put(seg)
    done.set()


def process_loop(seg_q: queue.Queue, asr, mt, label_for: Callable[[Segment], str], clock: Callable[[], float],
                 segments_done: threading.Event, out: TextIO, log_file: Path | None, beam_size: int = 1,
                 show_latency: bool = True, results: list | None = None,
                 abort: threading.Event | None = None, min_confidence: float = 0.0) -> None:
    """Processes segments until the segmenter has finished and the queue is empty
    (or immediately when `abort` is set: a second Ctrl+C)."""
    while not (segments_done.is_set() and seg_q.empty()):
        if abort is not None and abort.is_set():
            break
        try:
            seg: Segment = seg_q.get(timeout=0.1)
        except queue.Empty:
            continue
        t_begin = clock()
        hy = asr.transcribe(seg.audio)
        base = {"source": seg.source, "t_start": round(seg.t_start, 3), "t_end": round(seg.t_end, 3),
                "segment_s": round(len(seg.audio) / 16000, 2), "speech_s": seg.speech_s, "forced_cut": seg.forced_cut,
                "vad_floor_db": seg.meta.get("vad_floor_db"), "peak": seg.meta.get("peak"),
                "vad_wait_s": round(seg.meta["t_emitted"] - seg.t_end, 3),
                "queue_wait_s": round(t_begin - seg.meta["t_emitted"], 3),
                "asr_s": round(hy.seconds, 3), "asr_confidence": hy.confidence, "hy": hy.text}
        if len(hy.text.strip()) < 2:             # noise or a breath: nothing to show, but log it
            _log(log_file, {"status": "skipped", "reason": "asr text < 2 chars", **base})
            continue
        label = label_for(seg)
        unclear = hy.confidence < min_confidence
        if unclear:
            # D-030: don't let MT invent fluent English from garbled recognition.
            en = MtResult(text=UNCLEAR_EN, seconds=0.0, output_tokens=0)
        else:
            en = mt.translate(hy.text, beam_size=beam_size)
        t_done = clock()
        timings = {k: base[k] for k in ("vad_wait_s", "queue_wait_s", "asr_s", "segment_s", "forced_cut")}
        timings.update({"mt_s": round(en.seconds, 3), "mt_tokens": en.output_tokens,
                        "queue_left": seg_q.qsize(), "speaker": seg.meta.get("speaker")})
        hy_display = f"{hy.text}   (unclear)" if unclear else hy.text
        result = Result(label, seg.t_start, hy_display, en.text, t_done - seg.t_end, timings)
        out.write(format_result(result, show_latency))
        out.flush()
        if results is not None:
            results.append(result)
        _log(log_file, {"status": "unclear" if unclear else "shown", "label": label,
                        "latency_s": round(result.latency_s, 3), **base,
                        "mt_s": round(en.seconds, 3), "mt_tokens": en.output_tokens, "queue_left": seg_q.qsize(),
                        "speaker": seg.meta.get("speaker"), "en": en.text})


def _log(log_file: Path | None, record: dict) -> None:
    if log_file is not None:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_threads(targets: list[tuple[Callable, tuple]], failed: threading.Event) -> list[threading.Thread]:
    """Start worker threads. If one raises, its traceback is printed in a banner and
    `failed` is set, so the main thread stops the app instead of silently "listening"."""

    def guarded(fn: Callable, args: tuple) -> None:
        try:
            fn(*args)
        except BaseException:  # noqa: BLE001  (reported loudly, then the app stops)
            import traceback
            sys.stderr.write("\n" + "!" * 70 + f"\nFATAL: worker thread '{fn.__name__}' crashed:\n")
            traceback.print_exc()
            sys.stderr.write("!" * 70 + "\n")
            failed.set()

    threads = [threading.Thread(target=guarded, args=(fn, a), daemon=True, name=fn.__name__) for fn, a in targets]
    for t in threads:
        t.start()
    return threads


def wait_forever(failed: threading.Event) -> None:
    """Block until Ctrl+C (KeyboardInterrupt) or until a worker thread has failed."""
    while not failed.is_set():
        time.sleep(0.2)
