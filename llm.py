"""Unified LLM interface wrapper supporting Gemini, Anthropic, OpenAI, and OpenRouter (e.g. NVIDIA models)."""

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Ensure environment variables are loaded
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_cache_path(provider: str, model: str, system: str, prompt: str, json_mode: bool) -> Path:
    """Generate cache file path based on hash of request parameters."""
    cache_dir = BASE_DIR / "outputs" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_payload = f"{provider}:{model}:{system}:{prompt}:{json_mode}"
    cache_hash = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()
    return cache_dir / f"{cache_hash}.txt"


def _log_call(provider: str, model: str, duration: float, prompt_len: int, cached: bool = False, error: str = ""):
    """Append execution metrics to outputs/run_log.txt."""
    log_dir = BASE_DIR / "outputs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "run_log.txt"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "CACHED" if cached else ("ERROR" if error else "OK")
    message = (
        f"[{timestamp}] Status: {status} | Provider: {provider} | Model: {model} | "
        f"Time: {duration:.2f}s | Prompt Length: {prompt_len} chars"
    )
    if error:
        message += f" | Error: {error}"
    message += "\n"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(message)


def _is_rate_limit_error(error: Exception) -> bool:
    """Determine if an exception is related to rate limiting or quota exhaustion."""
    msg = str(error).lower()
    error_class = error.__class__.__name__.lower()
    rate_limit_indicators = [
        "429",
        "rate limit",
        "ratelimit",
        "quota",
        "resource exhausted",
        "resourceexhausted",
        "too many requests",
        "overloaded",
    ]
    return any(ind in msg or ind in error_class for ind in rate_limit_indicators)


def parse_json(text: str) -> Any:
    """Strip markdown json fences and parse text into a Python object."""
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, flags=re.IGNORECASE)
    if match:
        cleaned = match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise ValueError(
            f"Failed to parse model output as JSON:\n{err}\nRaw text:\n{text}"
        ) from err


def _call_gemini(model_name: str, api_key: str, prompt: str, system: str, json_mode: bool) -> str:
    """Execute API call using google.generativeai."""
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise ImportError(
            "google-generativeai package is not installed. Run: pip install google-generativeai"
        ) from e

    genai.configure(api_key=api_key)
    generation_config: dict[str, Any] = {}
    if json_mode:
        generation_config["response_mime_type"] = "application/json"

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system if system else None,
        generation_config=generation_config if generation_config else None,
    )
    response = model.generate_content(prompt)
    return response.text


def _call_anthropic(model_name: str, api_key: str, prompt: str, system: str, json_mode: bool) -> str:
    """Execute API call using anthropic."""
    try:
        import anthropic
    except ImportError as e:
        raise ImportError(
            "anthropic package is not installed. Run: pip install anthropic"
        ) from e

    client = anthropic.Anthropic(api_key=api_key)
    system_text = system or ""
    if json_mode:
        json_instruction = "You must output valid, raw JSON only. Do not include markdown fences or any other text."
        system_text = f"{system_text}\n{json_instruction}".strip() if system_text else json_instruction

    kwargs: dict[str, Any] = {
        "model": model_name,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_text:
        kwargs["system"] = system_text

    response = client.messages.create(**kwargs)
    return response.content[0].text


def _call_openai(model_name: str, api_key: str, prompt: str, system: str, json_mode: bool) -> str:
    """Execute API call using official openai endpoint."""
    try:
        import openai
    except ImportError as e:
        raise ImportError(
            "openai package is not installed. Run: pip install openai"
        ) from e

    client = openai.OpenAI(api_key=api_key)
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def _call_openrouter(model_name: str, api_key: str, prompt: str, system: str, json_mode: bool) -> str:
    """Execute API call via OpenRouter (supporting NVIDIA, Meta, Mistral, etc.)."""
    try:
        import openai
    except ImportError as e:
        raise ImportError(
            "openai package is required for OpenRouter. Run: pip install openai"
        ) from e

    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers={
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": "Continuity Checker",
        },
    )

    messages: list[dict[str, str]] = []
    system_text = system or ""
    if json_mode:
        json_prompt = "You must output valid JSON only. Do not include explanatory text."
        system_text = f"{system_text}\n{json_prompt}".strip() if system_text else json_prompt

    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def call_model(prompt: str, system: str = "", json_mode: bool = False) -> str:
    """Call the configured LLM provider with caching, retries, and optional JSON mode."""
    provider = os.getenv("PROVIDER", "openrouter").strip().lower()
    model_name = os.getenv("MODEL_NAME", "nvidia/nemotron-3-ultra-550b-a55b:free").strip()

    # Verify matching API key
    key_env_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    if provider not in key_env_map:
        raise ValueError(
            f"Unsupported PROVIDER '{provider}'. Supported providers: 'openrouter', 'gemini', 'anthropic', 'openai'."
        )

    api_key_name = key_env_map[provider]
    api_key = os.getenv(api_key_name)
    if not api_key or not api_key.strip():
        raise ValueError(
            f"API key '{api_key_name}' for provider '{provider}' is not set in environment or .env."
        )

    # Check disk cache
    cache_path = _get_cache_path(provider, model_name, system, prompt, json_mode)
    if cache_path.exists():
        start_time = time.time()
        cached_result = cache_path.read_text(encoding="utf-8")
        _log_call(provider, model_name, time.time() - start_time, len(prompt), cached=True)
        return cached_result

    # Retry loop with exponential backoff (3 attempts: 2s, 4s, 8s)
    max_retries = 3
    base_delay = 2.0
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        start_time = time.time()
        try:
            if provider == "openrouter":
                result = _call_openrouter(model_name, api_key, prompt, system, json_mode)
            elif provider == "gemini":
                result = _call_gemini(model_name, api_key, prompt, system, json_mode)
            elif provider == "anthropic":
                result = _call_anthropic(model_name, api_key, prompt, system, json_mode)
            elif provider == "openai":
                result = _call_openai(model_name, api_key, prompt, system, json_mode)
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            duration = time.time() - start_time
            # Save to disk cache
            cache_path.write_text(result, encoding="utf-8")
            _log_call(provider, model_name, duration, len(prompt), cached=False)
            return result

        except Exception as e:
            duration = time.time() - start_time
            last_error = e
            is_rate_limit = _is_rate_limit_error(e)
            _log_call(provider, model_name, duration, len(prompt), error=str(e))

            if attempt < max_retries and is_rate_limit:
                sleep_seconds = base_delay * (2 ** (attempt - 1))
                print(f"[Rate Limit] Provider '{provider}' rate-limited. Retrying in {sleep_seconds:.1f}s (attempt {attempt}/{max_retries})...")
                time.sleep(sleep_seconds)
            else:
                raise last_error

    if last_error:
        raise last_error
    return ""


if __name__ == "__main__":
    active_provider = os.getenv("PROVIDER", "openrouter").strip().lower()
    active_model = os.getenv("MODEL_NAME", "nvidia/nemotron-3-ultra-550b-a55b:free").strip()
    print(f"Testing call_model with PROVIDER='{active_provider}' MODEL_NAME='{active_model}'...")
    try:
        reply = call_model("Say hello")
        print("Reply received:")
        print(reply)
    except Exception as exc:
        print(f"Test call failed: {exc}")
