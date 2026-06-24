from __future__ import annotations

import json

import pytest

from backend.app.adapters import openai_translate
from backend.app.adapters.openai_translate import (
    HotwordItem,
    PreprocessResponse,
    CorrectionItem,
)
from backend.app.sources import detect_source


YT_SOURCE = detect_source("https://www.youtube.com/watch?v=abcdefghijk")
BB_SOURCE = detect_source("https://www.bilibili.com/video/BV1xx411c7mD")


def _write_asr(path, n: int, full_text: str | None = None) -> None:
    utterances = [
        {"text": f"S{i}.", "start_time": i * 1000, "end_time": (i + 1) * 1000}
        for i in range(n)
    ]
    payload = {"result": {"utterances": utterances, "text": full_text or " ".join(u["text"] for u in utterances)}}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _settings() -> dict[str, str]:
    return {"base_url": "https://example.com/v1", "api_key": "sk-test", "model": "model-x"}


def _no_sleep(monkeypatch):
    # Backoff retries must not actually sleep in tests.
    monkeypatch.setattr(openai_translate.time, "sleep", lambda *a, **kw: None)


def _stub_preprocess(monkeypatch, response: PreprocessResponse | None = None):
    seen: list[dict] = []

    def fake(full_text, meta, source, **kw):
        seen.append({"full_text": full_text, "meta": meta, "source": source, **kw})
        return response or PreprocessResponse()

    monkeypatch.setattr(openai_translate, "preprocess", fake)
    return seen


def _stub_translate_batch(monkeypatch, transform):
    seen: list[dict] = []

    def fake(texts, source, meta, pre, **kw):
        seen.append({"texts": list(texts), "source": source, "meta": meta, "pre": pre, **kw})
        results = [transform(t) for t in texts]
        on_batch_done = kw.get("on_batch_done")
        if on_batch_done is not None:
            # Mirror translate_batch's real batching so the caller's checkpoint
            # mapping (batch_index * BATCH_SIZE) stays correct.
            size = openai_translate.BATCH_SIZE
            for idx in range(0, len(texts), size):
                on_batch_done(idx // size, results[idx:idx + size])
        return results

    monkeypatch.setattr(openai_translate, "translate_batch", fake)
    return seen


def test_translate_asr_writes_preprocess_artifact(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    asr_file = metadata / "asr_fixed.json"
    _write_asr(asr_file, 1)

    pre = PreprocessResponse(
        summary="Video recap",
        hotwords=[HotwordItem(src="Fable 5", dst="Fable 5")],
        corrections=[CorrectionItem(wrong="java script", correct="JavaScript")],
    )
    monkeypatch.setattr(openai_translate, "preprocess", lambda *a, **kw: pre)
    _stub_translate_batch(monkeypatch, lambda t: f"zh:{t}")

    openai_translate.translate_asr(asr_file, tmp_path, _settings(), YT_SOURCE)
    artifact = metadata / "translation_preprocess.json"
    assert artifact.exists()
    saved = json.loads(artifact.read_text(encoding="utf-8"))
    assert saved["summary"] == "Video recap"
    assert saved["hotwords"][0]["src"] == "Fable 5"
    assert saved["corrections"][0]["correct"] == "JavaScript"


def test_translate_asr_reuses_preprocess_artifact_without_calling_api(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    asr_file = metadata / "asr_fixed.json"
    _write_asr(asr_file, 1)
    (metadata / "translation_preprocess.json").write_text(
        json.dumps(
            {
                "summary": "cached",
                "hotwords": [{"src": "GPU", "dst": "GPU"}],
                "corrections": [],
            }
        ),
        encoding="utf-8",
    )

    def fail_preprocess(*args, **kwargs):
        raise AssertionError("preprocess should not run when artifact exists")

    monkeypatch.setattr(openai_translate, "preprocess", fail_preprocess)
    seen = _stub_translate_batch(monkeypatch, lambda t: f"zh:{t}")

    openai_translate.translate_asr(asr_file, tmp_path, _settings(), YT_SOURCE)
    assert len(seen) == 1
    assert seen[0]["pre"].summary == "cached"


def test_translate_asr_writes_schema_with_speaker_and_lang(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    asr_file = metadata / "asr.json"
    _write_asr(asr_file, 2)

    _stub_preprocess(monkeypatch)
    _stub_translate_batch(monkeypatch, lambda t: f"zh:{t}")

    out = openai_translate.translate_asr(asr_file, tmp_path, _settings(), YT_SOURCE)
    items = json.loads(out.read_text(encoding="utf-8"))["translation"]
    assert [i["dst"] for i in items] == ["zh:S0.", "zh:S1."]
    assert {i["src_lang"] for i in items} == {"en"}
    assert {i["dst_lang"] for i in items} == {"zh"}
    assert {i["speaker"] for i in items} == {"1"}
    assert items[0]["start_time"] == 0


def test_translate_asr_output_filename_uses_target_lang(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    asr_file = metadata / "asr.json"
    _write_asr(asr_file, 1)

    _stub_preprocess(monkeypatch)
    _stub_translate_batch(monkeypatch, lambda _t: "x")

    out = openai_translate.translate_asr(asr_file, tmp_path, _settings(), BB_SOURCE)
    assert out.name == "translation.en.json"


def test_translate_asr_passes_meta_and_full_text_to_preprocess(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    asr_file = metadata / "asr.json"
    _write_asr(asr_file, 1, full_text="hello world")
    (metadata / "ytdlp_info.json").write_text(
        json.dumps({"title": "T", "uploader": "U", "description": "D"}),
        encoding="utf-8",
    )

    seen = _stub_preprocess(monkeypatch)
    _stub_translate_batch(monkeypatch, lambda t: t)

    openai_translate.translate_asr(asr_file, tmp_path, _settings(), YT_SOURCE)
    assert seen[0]["full_text"] == "hello world"
    assert seen[0]["meta"] == {"title": "T", "uploader": "U", "description": "D"}


def test_translate_asr_invokes_translate_batch_with_all_texts_at_once(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    asr_file = metadata / "asr.json"
    _write_asr(asr_file, 5)

    _stub_preprocess(monkeypatch, PreprocessResponse(hotwords=[HotwordItem(src="x", dst="y")]))
    seen = _stub_translate_batch(monkeypatch, lambda t: f"zh:{t}")

    openai_translate.translate_asr(asr_file, tmp_path, _settings(), YT_SOURCE)
    assert len(seen) == 1
    assert seen[0]["texts"] == ["S0.", "S1.", "S2.", "S3.", "S4."]
    assert seen[0]["pre"].hotwords[0].src == "x"


def test_translate_batch_replaces_em_dash_for_zh_target(monkeypatch):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(
        openai_translate, "_call_json",
        lambda *a, **kw: {"items": [{"dst": "你好——世界"}]},
    )
    monkeypatch.setattr(openai_translate, "_client", lambda *a, **kw: object())

    out = openai_translate.translate_batch(
        ["Hello world."], YT_SOURCE, {}, PreprocessResponse(),
        base_url="u", api_key="k", model="m",
    )
    assert out == ["你好，世界"]


def test_translate_batch_does_not_replace_em_dash_for_en_target(monkeypatch):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(
        openai_translate, "_call_json",
        lambda *a, **kw: {"items": [{"dst": "He said—wait—and left."}]},
    )
    monkeypatch.setattr(openai_translate, "_client", lambda *a, **kw: object())

    out = openai_translate.translate_batch(
        ["他说——等等——就走了。"], BB_SOURCE, {}, PreprocessResponse(),
        base_url="u", api_key="k", model="m",
    )
    assert out == ["He said—wait—and left."]


def test_translate_batch_uses_one_system_prompt_per_batch(monkeypatch):
    """Batching means the system prompt is sent once per batch, not once per
    sentence -- this is the core token-saving behavior."""
    _no_sleep(monkeypatch)
    captured: list[str] = []
    lock = __import__("threading").Lock()

    def fake_call_json(client, model, system, user, **kw):
        with lock:
            captured.append(system)
        payload = json.loads(user)
        return {"items": [{"dst": f"dst:{s}"} for s in payload["items"]]}

    monkeypatch.setattr(openai_translate, "_call_json", fake_call_json)
    monkeypatch.setattr(openai_translate, "_client", lambda *a, **kw: object())

    texts = [f"s{i}" for i in range(5)]
    out = openai_translate.translate_batch(
        texts, BB_SOURCE, {}, PreprocessResponse(),
        base_url="u", api_key="k", model="m", concurrency=4,
    )
    assert out == [f"dst:s{i}" for i in range(5)]
    # 5 sentences / batch_size 20 = exactly 1 batch -> exactly 1 LLM call
    assert len(captured) == 1
    assert len(set(captured)) == 1


def test_translate_batch_groups_sentences_into_batches(monkeypatch):
    """25 sentences with batch_size 20 must produce 2 LLM calls (20 + 5)."""
    _no_sleep(monkeypatch)
    calls: list[int] = []

    def fake_call_json(client, model, system, user, **kw):
        payload = json.loads(user)
        srcs = payload["items"]
        calls.append(len(srcs))
        return {"items": [{"dst": f"zh:{s}"} for s in srcs]}

    monkeypatch.setattr(openai_translate, "_call_json", fake_call_json)
    monkeypatch.setattr(openai_translate, "_client", lambda *a, **kw: object())

    texts = [f"s{i}" for i in range(25)]
    out = openai_translate.translate_batch(
        texts, YT_SOURCE, {}, PreprocessResponse(),
        base_url="u", api_key="k", model="m", concurrency=2,
    )
    assert out == [f"zh:s{i}" for i in range(25)]
    assert sorted(calls) == [5, 20]


def test_translate_batch_falls_back_to_per_sentence_on_malformed_response(monkeypatch):
    """A batch whose response is unusable must fall back to per-sentence
    translation rather than failing the whole run."""
    _no_sleep(monkeypatch)
    sentence_calls: list[str] = []

    def fake_call_json(client, model, system, user, **kw):
        # Batch request always returns a malformed payload (no 'items').
        return {"not_items": []}

    def fake_translate_sentence(text, target_language, client, model, system):
        sentence_calls.append(text)
        return f"single:{text}"

    monkeypatch.setattr(openai_translate, "_call_json", fake_call_json)
    monkeypatch.setattr(openai_translate, "_client", lambda *a, **kw: object())
    monkeypatch.setattr(openai_translate, "translate_sentence", fake_translate_sentence)

    out = openai_translate.translate_batch(
        ["a", "b"], YT_SOURCE, {}, PreprocessResponse(),
        base_url="u", api_key="k", model="m",
    )
    assert out == ["single:a", "single:b"]
    assert sentence_calls == ["a", "b"]


def test_call_with_retry_backs_off(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(openai_translate.time, "sleep", lambda d: sleeps.append(d))
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    result = openai_translate._call_with_retry(flaky, attempts=3, label="t")
    assert result == "ok"
    assert calls["n"] == 3
    # Exponential backoff before the 2nd (0.5s) and 3rd (1.0s) attempts.
    assert sleeps == [0.5, 1.0]


@pytest.mark.parametrize("value", ["abc", "1.5", "0", "-1", "201", ""])
def test_concurrency_from_bad_saved_values_falls_back_to_default(value):
    assert openai_translate._concurrency_from({"translate_concurrency": value}) == 50


def test_translate_sentence_retries_on_empty_dst(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def fake_call_json(client, model, system, user, **kw):
        calls["n"] += 1
        return {"dst": ""} if calls["n"] == 1 else {"dst": "ok"}

    monkeypatch.setattr(openai_translate, "_call_json", fake_call_json)

    out = openai_translate.translate_sentence("hello", "en", object(), "m", "sys")
    assert out == "ok"
    assert calls["n"] == 2


def test_translate_sentence_raises_after_retries(monkeypatch):
    _no_sleep(monkeypatch)

    def fake_call_json(client, model, system, user, **kw):
        raise ValueError("boom")

    monkeypatch.setattr(openai_translate, "_call_json", fake_call_json)

    with pytest.raises(RuntimeError, match="translate_sentence failed"):
        openai_translate.translate_sentence("x", "en", object(), "m", "sys")


def test_preprocess_returns_empty_when_repeatedly_invalid(monkeypatch):
    _no_sleep(monkeypatch)

    def fake_call_json(client, model, system, user, **kw):
        return {"summary": 123, "hotwords": "bad"}

    monkeypatch.setattr(openai_translate, "_call_json", fake_call_json)
    monkeypatch.setattr(openai_translate, "_client", lambda *a, **kw: object())

    pre = openai_translate.preprocess(
        "text", {"title": "t"}, YT_SOURCE,
        base_url="u", api_key="k", model="m",
    )
    assert pre.summary == ""
    assert pre.hotwords == []
    assert pre.corrections == []


def test_translate_system_prompt_contains_meta_summary_hotwords(monkeypatch):
    pre = PreprocessResponse(
        summary="Recap of the talk.",
        hotwords=[HotwordItem(src="LEGO", dst="乐高")],
    )
    meta = {"title": "Demo", "uploader": "Alice", "description": "Long description"}
    system = openai_translate._translate_system(YT_SOURCE, meta, pre)
    assert "Demo" in system
    assert "Alice" in system
    assert "Long description" in system
    assert "Recap of the talk." in system
    assert "LEGO -> 乐高" in system


def test_save_and_load_partial_roundtrip(tmp_path):
    openai_translate._save_partial(tmp_path, "zh", {0: "a", 2: "c"})
    loaded = openai_translate._load_partial(tmp_path, "zh", 5)
    assert loaded == {0: "a", 2: "c"}


def test_translate_asr_resumes_from_partial(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    asr_file = metadata / "asr.json"
    _write_asr(asr_file, 5)
    # Pretend the first two sentences were already translated in a prior run.
    openai_translate._save_partial(tmp_path, "zh", {0: "done0", 1: "done1"})

    _stub_preprocess(monkeypatch)
    seen = _stub_translate_batch(monkeypatch, lambda t: f"zh:{t}")

    openai_translate.translate_asr(asr_file, tmp_path, _settings(), YT_SOURCE)
    # Only the 3 unfinished sentences should be sent to translate_batch.
    assert seen[0]["texts"] == ["S2.", "S3.", "S4."]
    out = json.loads((metadata / "translation.zh.json").read_text(encoding="utf-8"))
    assert [i["dst"] for i in out["translation"]] == [
        "done0", "done1", "zh:S2.", "zh:S3.", "zh:S4.",
    ]
    # Final file written -> checkpoint must be cleaned up.
    assert not (metadata / "translation.zh.partial.json").exists()


def test_translate_asr_writes_final_file_and_clears_partial(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    asr_file = metadata / "asr.json"
    _write_asr(asr_file, 3)
    _stub_preprocess(monkeypatch)

    _no_sleep(monkeypatch)

    def fake_call_json(client, model, system, user, **kw):
        payload = json.loads(user)
        return {"items": [{"dst": f"zh:{s}"} for s in payload["items"]]}

    monkeypatch.setattr(openai_translate, "_call_json", fake_call_json)
    monkeypatch.setattr(openai_translate, "_client", lambda *a, **kw: object())

    out = openai_translate.translate_asr(asr_file, tmp_path, _settings(), YT_SOURCE)
    items = json.loads(out.read_text(encoding="utf-8"))["translation"]
    assert [i["dst"] for i in items] == ["zh:S0.", "zh:S1.", "zh:S2."]
    assert not (metadata / "translation.zh.partial.json").exists()