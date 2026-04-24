from __future__ import annotations

import io
import re
import struct
import wave
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------

VOICE_MODELS: dict[str, str] = {
    "male":   "mpit/ru_RU-ruslan-medium.onnx",
    "female": "mpit/ru_RU-irina-medium.onnx",
}

_LOADED_VOICES: dict[str, object] = {}   # кэш загруженных моделей


def _get_voice(gender: str = "male"):
    """Загружает модель Piper (с кэшированием)."""
    from piper import PiperVoice  # type: ignore

    gender = gender if gender in VOICE_MODELS else "male"
    if gender not in _LOADED_VOICES:
        model_path = VOICE_MODELS[gender]
        _LOADED_VOICES[gender] = PiperVoice.load(model_path)
    return _LOADED_VOICES[gender]


# ---------------------------------------------------------------------------
# Разбивка текста на предложения
# ---------------------------------------------------------------------------

_SENTENCE_END = re.compile(
    r'[.!?…]+',
    re.UNICODE,
)


def split_sentences(text: str) -> list[str]:
    """Разбивает текст на предложения по знакам препинания."""
    text = text.strip()
    if not text:
        return []

    # Вставляем маркер после каждого знака конца предложения
    marked = re.sub(r'([.!?…]+)\s+', r'\1\n', text)
    parts = [s.strip() for s in marked.splitlines() if s.strip()]
    return parts if parts else [text]


# ---------------------------------------------------------------------------
# Вспомогательная функция: raw PCM → WAV-байты
# ---------------------------------------------------------------------------

def _pcm_to_wav_bytes(pcm_frames: bytes, sample_rate: int, channels: int = 1, sampwidth: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_frames)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Синтез одного предложения → WAV-байты
# ---------------------------------------------------------------------------

def synthesize_sentence(text: str, gender: str = "male") -> bytes:
    """
    Синтезирует одно предложение и возвращает WAV-байты в памяти.
    Не пишет ничего на диск.
    """
    voice = _get_voice(gender)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text, wf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Потоковый синтез: генератор WAV-чанков
# ---------------------------------------------------------------------------

def synthesize_stream(text: str, gender: str = "male") -> Iterator[bytes]:
    """
    Генератор: разбивает текст на предложения, синтезирует каждое
    и по очереди выдаёт WAV-байты чанков.

    Пример использования:
        for chunk in synthesize_stream(long_text, gender="female"):
            player.feed(chunk)   # воспроизводим сразу, не ждём конца
    """
    sentences = split_sentences(text)
    voice = _get_voice(gender)

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(sentence, wf)
        yield buf.getvalue()


# ---------------------------------------------------------------------------
# Сохранение в файл (для локального использования / тестов)
# ---------------------------------------------------------------------------

def synthesize_to_file(text: str, output_path: str | Path, gender: str = "male") -> Path:
    """
    Синтезирует весь текст по предложениям и склеивает в один WAV-файл.
    Возвращает путь к готовому файлу.
    """
    output_path = Path(output_path)
    sentences = split_sentences(text)
    voice = _get_voice(gender)

    all_frames = bytearray()
    sample_rate: int | None = None
    channels: int | None = None
    sampwidth: int | None = None

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(sentence, wf)

        buf.seek(0)
        with wave.open(buf, "rb") as wf:
            if sample_rate is None:
                sample_rate = wf.getframerate()
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
            all_frames.extend(wf.readframes(wf.getnframes()))

    if not all_frames or sample_rate is None:
        raise ValueError("Текст пуст или синтез не дал результата")

    with wave.open(str(output_path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(sampwidth)
        out.setframerate(sample_rate)
        out.writeframes(bytes(all_frames))

    return output_path


# ---------------------------------------------------------------------------
# API-хелпер: синтез → WAV-байты в памяти (для HTTP-стриминга)
# ---------------------------------------------------------------------------

def synthesize_to_bytes(text: str, gender: str = "male") -> bytes:
    """
    Синтезирует весь текст и возвращает итоговый WAV как bytes.
    Используется в HTTP-эндпоинте /api/tts.
    """
    sentences = split_sentences(text)
    voice = _get_voice(gender)

    all_frames = bytearray()
    sample_rate = channels = sampwidth = None

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(sentence, wf)
        buf.seek(0)
        with wave.open(buf, "rb") as wf:
            if sample_rate is None:
                sample_rate = wf.getframerate()
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
            all_frames.extend(wf.readframes(wf.getnframes()))

    if not all_frames:
        raise ValueError("Нечего синтезировать")

    return _pcm_to_wav_bytes(bytes(all_frames), sample_rate, channels, sampwidth)


# ---------------------------------------------------------------------------
# CLI для быстрого теста
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or (
        "Радуга — это атмосферное, оптическое и метеорологическое явление. "
        "Она возникает, когда солнечный свет преломляется в каплях воды. "
        "Каждая капля действует как маленькая призма."
    )
    gender = "male"
    if "--female" in sys.argv:
        gender = "female"
        text = text.replace("--female", "").strip()

    out = synthesize_to_file(text, "output.wav", gender=gender)
    print(f"Готово! Файл {out} создан. Голос: {gender}")
    sentences = split_sentences(text)
    print(f"Разбито на {len(sentences)} предложени(й):")
    for i, s in enumerate(sentences, 1):
        print(f"  {i}. {s}")
