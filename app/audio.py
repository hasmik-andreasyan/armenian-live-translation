"""Audio capture: microphone + system output (WASAPI loopback), Windows.

Each AudioSource opens one PyAudioWPatch input stream at the device's native
rate and channel count. In the callback, the audio is converted to float32
mono, resampled to 16 kHz with soxr, and pushed to a shared queue as
AudioChunk(source, t_start, samples).

t_start is seconds since the session start (one monotonic clock for all
sources), so audio from both sources can be lined up even when WASAPI
loopback delivers nothing during silence.
"""

import queue
import time
from dataclasses import dataclass

import numpy as np

TARGET_RATE = 16000
PA_INPUT_OVERFLOW = 2  # portaudio paInputOverflow flag


@dataclass
class AudioChunk:
    source: str          # "mic" or "loopback"
    t_start: float       # seconds since session start
    samples: np.ndarray  # float32 mono, 16 kHz


def open_pyaudio():
    import pyaudiowpatch as pyaudio
    return pyaudio.PyAudio()


def describe_devices(pa) -> list[dict]:
    """All PortAudio devices with host API name and loopback flag."""
    devices = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        devices.append({
            "index": d["index"], "name": d["name"],
            "host_api": pa.get_host_api_info_by_index(d["hostApi"])["name"],
            "inputs": d["maxInputChannels"], "outputs": d["maxOutputChannels"],
            "rate": int(d["defaultSampleRate"]), "loopback": bool(d.get("isLoopbackDevice", False)),
        })
    return devices


def default_mic(pa) -> dict:
    return pa.get_default_input_device_info()


def default_loopback(pa) -> dict:
    """Loopback device of the current default output (what you hear)."""
    return pa.get_default_wasapi_loopback()


class AudioSource:
    def __init__(self, pa, device: dict, name: str, out_queue: queue.Queue, t0: float, block_s: float = 0.05) -> None:
        import pyaudiowpatch as pyaudio
        import soxr

        if device["maxInputChannels"] < 1:
            raise ValueError(f"device {device['index']} ({device['name']}) has no input channels")
        self.name = name
        self.device_name = device["name"]
        self.index = device["index"]
        self.rate = int(device["defaultSampleRate"])
        self.channels = int(device["maxInputChannels"])
        self._continue = pyaudio.paContinue
        self._resampler = soxr.ResampleStream(self.rate, TARGET_RATE, 1, dtype="float32")
        self._queue = out_queue
        self._t0 = t0
        # statistics, read by the capture test
        self.callbacks = 0
        self.native_frames = 0
        self.status_flags = 0
        self.max_gap_s = 0.0
        self._last_callback = None
        self._stream = pa.open(format=pyaudio.paInt16, channels=self.channels, rate=self.rate, input=True,
                               input_device_index=self.index, frames_per_buffer=int(self.rate * block_s),
                               stream_callback=self._callback, start=False)

    def _callback(self, in_data, frame_count, time_info, status):
        now = time.monotonic()
        if self._last_callback is not None:
            self.max_gap_s = max(self.max_gap_s, now - self._last_callback)
        self._last_callback = now
        self.status_flags |= status
        x = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
        if self.channels > 1:
            x = x.reshape(-1, self.channels).mean(axis=1)
        y = self._resampler.resample_chunk(x)
        self.callbacks += 1
        self.native_frames += frame_count
        if len(y):
            self._queue.put(AudioChunk(self.name, now - self._t0 - frame_count / self.rate, y))
        return (None, self._continue)

    def start(self) -> None:
        self._stream.start_stream()

    def stop(self) -> None:
        self._stream.stop_stream()
        self._stream.close()
