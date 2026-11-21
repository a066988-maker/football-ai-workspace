"""Gemini Developer API client with free-tier model fallback and bounded requests.

Avoids a retired/ineligible model's 404 without asking users for a new key.
Never logs the API key. A model lookup/list success alone does not imply
generateContent permission; only a successful response is trusted.
"""
import json
import os
import re
import urllib.error
import urllib.request

FREE_MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash")
LAST_WORKING = None


def candidate_models():
    configured = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    # Do not call retired Gemini 2.5 even if the workflow still configures it.
    if configured in FREE_MODELS:
        values = (configured,) + tuple(name for name in FREE_MODELS if name != configured)
    else:
        values = FREE_MODELS
    if LAST_WORKING and LAST_WORKING in values:
        values = (LAST_WORKING,) + tuple(name for name in values if name != LAST_WORKING)
    return values


def call(prompt, temperature=0.2):
    global LAST_WORKING
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError("Gemini API key secret missing")
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": temperature,
        },
    }, ensure_ascii=False).encode("utf-8")
    failures = []
    for model in candidate_models():
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent",
            data=payload, method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                data = json.load(response)
            choices = data.get("candidates", [])
            parts = choices[0].get("content", {}).get("parts", []) if choices else []
            content = "".join(p.get("text", "") for p in parts)
            if not content:
                raise ValueError("Gemini returned empty or blocked content")
            LAST_WORKING = model
            return json.loads(content), model
        except urllib.error.HTTPError as exc:
            failures.append(model + ": HTTP " + str(exc.code))
            # Authentication invalid/blocked -> retrying another model will not help.
            if exc.code in (400, 401, 403):
                raise ValueError("Gemini HTTP " + str(exc.code) + " (request/credentials/access)") from exc
            # Model may be retired / no provisioning. Free-tier 429 may be
            # model-specific; try the other explicitly free-tier model.
            if exc.code in (404, 429, 503):
                continue
            raise ValueError("Gemini HTTP " + str(exc.code)) from exc
        except (OSError, TimeoutError) as exc:
            failures.append(model + ": network error " + type(exc).__name__)
            continue
    # Gemini 3.8 primarily supports the Interactions API. When generateContent
    # returns 503, try this separate endpoint once before a rules fallback.
    interaction_payload = json.dumps({
        "model": "gemini-3.8-flash",
        "store": False,
        "input": [{"type": "user_input", "content": prompt}],
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=interaction_payload, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=65) as response:
            data = json.load(response)
        outputs = []
        for step in data.get("steps", []):
            if step.get("type") != "model_output":
                continue
            for part in step.get("content", []):
                if part.get("type") == "text":
                    outputs.append(part.get("text", ""))
        content = "".join(outputs) or data.get("output_text", "")
        if not content:
            raise ValueError("Interactions produced no model text")
        content = content.strip()
        fence = chr(96) * 3
        if content.startswith(fence):
            content = content.removeprefix(fence + "json").removeprefix(fence)
            content = content.rsplit(fence, 1)[0].strip()
        parsed = json.loads(content)
        LAST_WORKING = "gemini-3.8-flash-interactions"
        return parsed, LAST_WORKING
    except urllib.error.HTTPError as exc:
        failures.append("interactions: HTTP " + str(exc.code))
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        failures.append("interactions: " + type(exc).__name__)
    raise ValueError("Gemini model fallback exhausted: " + "; ".join(failures))
