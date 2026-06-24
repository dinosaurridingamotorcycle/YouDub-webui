from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from openai import APIError, OpenAI
from pydantic import BaseModel, Field, ValidationError

from ..sources import SourceConfig
from ._translate_prompts import PREPROCESS_PROMPT, TRANSLATE_RULES
from .openai_client import normalize_openai_base_url

log = logging.getLogger(__name__)

API_SETTING_KEYS = ("base_url", "api_key", "model")
PREPROCESS_RETRY = 2
TRANSLATE_RETRY = 2
DESCRIPTION_LIMIT = 500
DEFAULT_CONCURRENCY = 50
# Batch translation: how many sentences are sent in a single chat completion
# request. Batching is what saves tokens -- the (large) system prompt is sent
# once per batch instead of once per sentence.
BATCH_SIZE = 20
# Exponential backoff for retryable LLM call failures (format errors, rate
# limits, timeouts). Bounded so a long video does not stall for too long.
BASE_BACKOFF = 0.5
MAX_BACKOFF = 8.0


class HotwordItem(BaseModel):
    src: str
    dst: str


class CorrectionItem(BaseModel):
    wrong: str
    correct: str


class PreprocessResponse(BaseModel):
    summary: str = ""
    hotwords: list[HotwordItem] = Field(default_factory=list)
    corrections: list[CorrectionItem] = Field(default_factory=list)


class TranslationItem(BaseModel):
    dst: str


def list_models(*, base_url: str, api_key: str) -> list[str]:
    if not api_key:
        raise ValueError("OpenAI API key is not configured.")
    client = OpenAI(api_key=api_key, base_url=normalize_openai_base_url(base_url))
    response = client.models.list()
    seen: set[str] = set()
    models: list[str] = []
    for item in response.data:
        model_id = getattr(item, "id", "")
        if model_id and model_id not in seen:
            seen.add(model_id)
            models.append(model_id)
    return models


def _client(base_url: str, api_key: str) -> OpenAI:
    if not api_key:
        raise ValueError("OpenAI API key is not configured.")
    return OpenAI(api_key=api_key, base_url=normalize_openai_base_url(base_url))


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(raw)
    if not match:
        raise json.JSONDecodeError(f"no JSON object found; raw[:300]={raw[:300]!r}", raw, 0)
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise json.JSONDecodeError(
            f"{exc.msg}; len={len(raw)}; raw[:300]={raw[:300]!r}; raw[-200:]={raw[-200:]!r}",
            raw,
            exc.pos,
        ) from None


def _call_json(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
) -> dict[str, Any]:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    raw = response.choices[0].message.content or "{}"
    return _extract_json(raw)


# Retryable failure modes: malformed JSON / schema, empty output, and OpenAI
# transport/rate-limit errors. APIError covers RateLimitError, APITimeoutError
# and APIConnectionError.
_RETRYABLE_EXCEPTIONS = (json.JSONDecodeError, ValidationError, ValueError, APIError)


def _call_with_retry(func: Callable[[], Any], *, attempts: int, label: str) -> Any:
    """Run ``func`` up to ``attempts`` times with exponential backoff between
    retries. Raises the last error if all attempts fail."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return func()
        except _RETRYABLE_EXCEPTIONS as exc:
            last_error = exc
            if attempt < attempts - 1:
                delay = min(BASE_BACKOFF * (2 ** attempt), MAX_BACKOFF)
                log.warning(
                    "%s attempt %d failed: %s; retrying in %.1fs",
                    label, attempt + 1, exc, delay,
                )
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def _format_terms(items: list, fmt: str, empty: str) -> str:
    if not items:
        return empty
    return "\n".join(fmt.format(**item.model_dump()) for item in items)


def _meta_view(meta: dict[str, Any]) -> dict[str, str]:
    description = (meta.get("description") or "").strip()
    if len(description) > DESCRIPTION_LIMIT:
        description = description[:DESCRIPTION_LIMIT] + "..."
    return {
        "title": str(meta.get("title") or "").strip() or "(unknown)",
        "uploader": str(meta.get("uploader") or "").strip() or "(unknown)",
        "description": description or "(none)",
    }


def preprocess(
    full_text: str,
    meta: dict[str, Any],
    source: SourceConfig,
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> PreprocessResponse:
    user = PREPROCESS_PROMPT.format(
        src_language_name=source.asr_language_name,
        dst_language_name=source.target_language_name,
        full_text=full_text,
        **_meta_view(meta),
    )
    client = _client(base_url, api_key)

    def attempt() -> PreprocessResponse:
        data = _call_json(client, model, "You output strict JSON only.", user)
        return PreprocessResponse.model_validate(data)

    try:
        return _call_with_retry(
            attempt, attempts=PREPROCESS_RETRY + 1, label="preprocess"
        )
    except Exception as exc:
        log.error("preprocess gave up, returning empty: %s", exc)
        return PreprocessResponse()


def _translate_system(source: SourceConfig, meta: dict[str, Any], pre: PreprocessResponse) -> str:
    rules = TRANSLATE_RULES[source.target_language]
    return rules.format(
        summary=pre.summary or "(none)",
        hotwords=_format_terms(pre.hotwords, "{src} -> {dst}", "(none)"),
        corrections=_format_terms(pre.corrections, "{wrong} -> {correct}", "(none)"),
        **_meta_view(meta),
    )


def _post_process(text: str, target_language: str) -> str:
    cleaned = text.strip()
    if target_language == "zh":
        cleaned = cleaned.replace("——", "，")
    return cleaned


def translate_sentence(
    text: str,
    target_language: str,
    client: OpenAI,
    model: str,
    system: str,
) -> str:
    """Translate a single sentence. Used directly as a per-sentence fallback
    when a batch fails, and kept for backward compatibility."""

    def attempt() -> str:
        data = _call_json(client, model, system, text)
        item = TranslationItem.model_validate(data)
        if not item.dst.strip():
            raise ValueError("empty dst")
        return _post_process(item.dst, target_language)

    try:
        return _call_with_retry(
            attempt, attempts=TRANSLATE_RETRY, label=f"translate {text[:60]!r}"
        )
    except Exception as exc:
        raise RuntimeError(
            f"translate_sentence failed after {TRANSLATE_RETRY} attempts: {exc}"
        ) from exc


def _coerce_dst(item: Any) -> str:
    """Tolerantly extract a destination string from a batch response item.
    Accepts both {"dst": "..."} objects and bare strings."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("dst") or item.get("text") or "")
    return ""


def _translate_batch(
    batch: list[str],
    target_language: str,
    client: OpenAI,
    model: str,
    system: str,
) -> list[str]:
    """Translate a batch of sentences in a single request. If the batch
    response is unusable after retries, fall back to per-sentence translation
    so one bad batch does not sink the whole run."""
    if not batch:
        return []

    def attempt() -> list[str]:
        user = json.dumps({"items": batch}, ensure_ascii=False)
        data = _call_json(client, model, system, user)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError("response missing 'items' list")
        if len(items) != len(batch):
            raise ValueError(
                f"item count mismatch: sent {len(batch)}, got {len(items)}"
            )
        cleaned: list[str] = []
        for raw in items:
            dst = _coerce_dst(raw)
            if not dst.strip():
                raise ValueError("empty dst in batch")
            cleaned.append(_post_process(dst, target_language))
        return cleaned

    try:
        return _call_with_retry(
            attempt, attempts=TRANSLATE_RETRY, label=f"translate batch x{len(batch)}"
        )
    except Exception as exc:
        log.warning(
            "batch translation failed after retries, falling back to per-sentence: %s",
            exc,
        )
        return [
            translate_sentence(t, target_language, client, model, system) for t in batch
        ]


def translate_batch(
    texts: list[str],
    source: SourceConfig,
    meta: dict[str, Any],
    pre: PreprocessResponse,
    *,
    base_url: str,
    api_key: str,
    model: str,
    concurrency: int = DEFAULT_CONCURRENCY,
    on_batch_done: Callable[[int, list[str]], None] | None = None,
) -> list[str]:
    """Translate ``texts`` and return translations in the same order.

    Sentences are grouped into batches of ``BATCH_SIZE`` so the system prompt
    is sent once per batch rather than once per sentence (the main token
    saving). Batches run concurrently. ``on_batch_done`` is invoked with the
    batch index and its results as each batch finishes, enabling incremental
    checkpointing by the caller.
    """
    if not texts:
        return []
    system = _translate_system(source, meta, pre)
    client = _client(base_url, api_key)
    batches = [texts[i:i + BATCH_SIZE] for i in range(0, len(texts), BATCH_SIZE)]
    total_batches = len(batches)
    log.info(
        "translate_batch: %d sentences, %d batches (size=%d), concurrency=%d",
        len(texts), total_batches, BATCH_SIZE, concurrency,
    )

    results: list[list[str] | None] = [None] * total_batches
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        future_to_idx = {
            pool.submit(
                _translate_batch, batch, source.target_language, client, model, system
            ): idx
            for idx, batch in enumerate(batches)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            batch_result = future.result()  # raises on failure (fail loud)
            results[idx] = batch_result
            if on_batch_done is not None:
                on_batch_done(idx, batch_result)

    return [dst for batch_result in results for dst in (batch_result or [])]


def _read_meta(session: Path) -> dict[str, Any]:
    info_file = session / "metadata" / "ytdlp_info.json"
    if not info_file.exists():
        return {}
    return json.loads(info_file.read_text(encoding="utf-8"))


def _speaker(utt: dict[str, Any]) -> str:
    additions = utt.get("additions") or {}
    if isinstance(additions, dict):
        return str(additions.get("speaker") or "1")
    return "1"


def _full_text(data: dict[str, Any], texts: list[str]) -> str:
    raw = data.get("result", {}).get("text") or ""
    if raw.strip():
        return raw
    return " ".join(texts)


def preprocess_artifact_path(session: Path) -> Path:
    return session / "metadata" / "translation_preprocess.json"


def write_preprocess_artifact(session: Path, pre: PreprocessResponse) -> Path:
    path = preprocess_artifact_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pre.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_preprocess_artifact(session: Path) -> PreprocessResponse | None:
    path = preprocess_artifact_path(session)
    if not path.exists():
        return None
    return PreprocessResponse.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _partial_path(session: Path, target_language: str) -> Path:
    return session / "metadata" / f"translation.{target_language}.partial.json"


def _load_partial(session: Path, target_language: str, total: int) -> dict[int, str]:
    """Load checkpointed per-sentence translations. Returns a mapping of
    sentence index -> translation for already-completed sentences."""
    path = _partial_path(session, target_language)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    done = data.get("done") if isinstance(data, dict) else None
    result: dict[int, str] = {}
    if isinstance(done, dict):
        for key, value in done.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < total and isinstance(value, str) and value:
                result[idx] = value
    return result


def _save_partial(
    session: Path, target_language: str, done: dict[int, str]
) -> None:
    path = _partial_path(session, target_language)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"done": {str(k): v for k, v in done.items()}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _concurrency_from(settings: dict[str, str]) -> int:
    raw = str(settings.get("translate_concurrency") or "").strip()
    if not raw or not all("0" <= char <= "9" for char in raw):
        return DEFAULT_CONCURRENCY
    concurrency = int(raw)
    if concurrency < 1 or concurrency > 200:
        return DEFAULT_CONCURRENCY
    return concurrency


def translate_asr(
    asr_file: Path,
    session: Path,
    settings: dict[str, str],
    source: SourceConfig,
) -> Path:
    output_file = session / "metadata" / f"translation.{source.target_language}.json"
    if output_file.exists():
        return output_file

    data = json.loads(asr_file.read_text(encoding="utf-8"))
    utterances = data["result"]["utterances"]
    texts = [u["text"].strip() for u in utterances]
    full_text = _full_text(data, texts)
    meta = _read_meta(session)
    total = len(texts)

    api = {key: settings[key] for key in API_SETTING_KEYS if key in settings}
    pre = load_preprocess_artifact(session)
    if pre is None:
        pre = preprocess(full_text, meta, source, **api)
        write_preprocess_artifact(session, pre)
        log.info("Wrote translation preprocess artifact to %s", preprocess_artifact_path(session))
    else:
        log.info("Reusing translation preprocess artifact from %s", preprocess_artifact_path(session))

    # Resume support: reuse sentence-level results checkpointed in a previous
    # interrupted run, so a long video does not have to be fully retranslated.
    done: dict[int, str] = _load_partial(session, source.target_language, total)
    pending_indices = [i for i in range(total) if i not in done]
    pending_texts = [texts[i] for i in pending_indices]
    if done:
        log.info("Resuming translation: %d/%d sentences already done", len(done), total)

    if pending_texts:
        def on_batch_done(batch_index: int, batch_results: list[str]) -> None:
            start = batch_index * BATCH_SIZE
            for offset, dst in enumerate(batch_results):
                global_idx = pending_indices[start + offset]
                done[global_idx] = dst
            _save_partial(session, source.target_language, done)

        translate_batch(
            pending_texts, source, meta, pre, **api,
            concurrency=_concurrency_from(settings), on_batch_done=on_batch_done,
        )

    dst_list = [done.get(i, "") for i in range(total)]

    translation = [
        {
            "src": text,
            "dst": dst_list[i],
            "src_lang": source.asr_language,
            "dst_lang": source.target_language,
            "start_time": utt["start_time"],
            "end_time": utt["end_time"],
            "speaker": _speaker(utt),
        }
        for i, (text, utt) in enumerate(zip(texts, utterances))
    ]
    output_file.write_text(
        json.dumps({"translation": translation}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Clean up the checkpoint now that the final file is written.
    partial = _partial_path(session, source.target_language)
    if partial.exists():
        partial.unlink()
    return output_file
