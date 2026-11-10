"""Drop-in replacement for the parts of `ollama.Client` this app uses.

Replies come from Google's Gemini API free tier first. When a Gemini model is busy or out of
free quota, the next model in the chain answers instead, including models on other free APIs:

    1. Gemini 3.8 Flash          (Google, ~20 free a day)
    2. Gemini 3.6 Flash          (Google, ~20 free a day)
    3. Gemma 4 26B               (Cloudflare Workers AI, ~250 free a day, reads images)
    4. Gemini 3.5 Flash-Lite     (Google, ~500 free a day)
    5. gpt-oss-20b               (Groq, text only, last resort)

A backup is skipped when its keys aren't set, so the app works with only GEMINI_API_KEY.

It keeps the same call shape the app already uses, so the rest of the code doesn't change:

    client = Client(api_key=..., timeout=90, cloudflare_account_id=..., cloudflare_api_token=...,
                    groq_api_key=...)
    response = client.chat(model=..., messages=[...], format="json", options={"temperature": 0.3})
    response.message.content                      # the reply text

    for chunk in client.chat(model=..., messages=[...], stream=True):
        chunk.message.content                     # each piece of a streamed reply

Messages use Ollama's format: {"role": "system" | "user" | "assistant", "content": "...",
"images": [<base64 strings>]}.
"""

import base64
import json
import threading
import time
from types import SimpleNamespace

import httpx
from google import genai
from google.genai import errors, types


# ------------------------------------------------------------------------------------------
# Timing report: which model answered each message and how long it took. The app logs it and
# can read it with client.last_report(). Kept per thread (each visitor's request runs on its
# own thread), so two people chatting at once never see each other's report.
# ------------------------------------------------------------------------------------------

_local = threading.local()


def _new_report():
    _local.report = {"started": time.time(), "tries": [], "answered_by": None,
                     "first_words_s": None, "total_s": None, "notes": []}
    return _local.report


def _note(text):
    report = getattr(_local, "report", None)
    if report is not None:
        report["notes"].append(text)


def _report_text(report):
    if not report:
        return "no report"
    parts = [f"answered by {report['answered_by'] or 'nobody (all models failed)'}"]
    if report["first_words_s"] is not None:
        parts.append(f"first words {report['first_words_s']:.1f}s")
    if report["total_s"] is not None:
        parts.append(f"total {report['total_s']:.1f}s")
    failed = [f"{t['model']} {t['outcome']} ({t['seconds']:.1f}s)" for t in report["tries"] if t["outcome"] != "ok"]
    if failed:
        parts.append("skipped/failed first: " + ", ".join(failed))
    if report["notes"]:
        parts.append("notes: " + "; ".join(report["notes"]))
    return " · ".join(parts)


class ResponseError(Exception):
    """Raised when no model could answer (same name the app used with Ollama)."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class _TryNext(Exception):
    """One model couldn't answer (busy, out of quota, timed out); move on to the next."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _wrap(text):
    """Give the reply the same shape as an Ollama response: response.message.content."""
    return SimpleNamespace(message=SimpleNamespace(role="assistant", content=text or ""))


def _mime_type(image_b64):
    """Work out the image type from its first bytes (the apps send PNGs, but be safe)."""
    head = base64.b64decode(image_b64[:32] + "=" * (-len(image_b64[:32]) % 4))
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"GIF8"):
        return "image/gif"
    return "image/png"


def _as_b64(image):
    if isinstance(image, (bytes, bytearray)):
        return base64.b64encode(image).decode("utf-8")
    return image


# ------------------------------------------------------------------------------------------
# The chain
# ------------------------------------------------------------------------------------------

CLOUDFLARE_MODEL = "@cf/google/gemma-4-26b-a4b-it"
GROQ_MODEL = "openai/gpt-oss-20b"

# (provider, model). The model the app asks for goes first, then the rest of this list in order.
CHAIN = (
    ("gemini", "gemini-3.8-flash"),
    ("gemini", "gemini-3.6-flash"),
    ("cloudflare", CLOUDFLARE_MODEL),
    ("gemini", "gemini-3.5-flash-lite"),
    ("groq", GROQ_MODEL),
)
# After a model fails, skip it for a while so later messages don't wait on it again. These
# timers are shared by everyone using the app (the client is created once per server).
REST_SECONDS_OUT_OF_QUOTA = 300   # 429: free limit used up, check again in 5 minutes
REST_SECONDS_OTHER = 30           # busy, timed out, or another error

# Gemini thinks before it answers; "low" keeps that short so replies start sooner.
# ("minimal" would be faster, but Gemini 3.8 Flash rejects it.)
GEMINI_THINKING_LEVEL = "low"

# How long to wait for a model before trying the next one. A full detailed reply rarely takes
# more than about 40 seconds, and a stuck model shouldn't hold the user for minutes.
BACKUP_TIMEOUT_SECONDS = 60


def _gemini_error(error):
    """Any Gemini failure (busy, out of quota, retired model, bad key) moves on to the next
    model; the reason is printed to the app's logs."""
    return _TryNext(str(error), getattr(error, "code", None))


def _final_error(last):
    code = getattr(last, "status_code", None)
    if code == 429:
        return ResponseError("The free AI limit has been reached for now. Please try again in a few minutes.", 429)
    return ResponseError("The AI is very busy right now. Please try again in a moment.", code)


class Client:
    def __init__(self, api_key, timeout=None, cloudflare_account_id=None, cloudflare_api_token=None,
                 groq_api_key=None):
        seconds = min(timeout or BACKUP_TIMEOUT_SECONDS, BACKUP_TIMEOUT_SECONDS)
        self._timeout = seconds
        self._gemini = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(seconds * 1000))
        )
        self._cloudflare = (cloudflare_account_id, cloudflare_api_token) if (
            cloudflare_account_id and cloudflare_api_token) else None
        self._groq_key = groq_api_key or None
        self._resting = {}  # (provider, model) -> time.time() until which it is skipped

    # ---------- which models to try ----------

    def _chain(self, model, messages):
        newest_has_images = bool(messages and messages[-1].get("images"))
        first = [("gemini", model)] if not any(model == m for _, m in CHAIN) else \
            [entry for entry in CHAIN if entry[1] == model]
        rest = [entry for entry in CHAIN if entry not in first]
        steps = []
        for provider, name in first + rest:
            if provider == "cloudflare" and not self._cloudflare:
                continue
            if provider == "groq" and (not self._groq_key or newest_has_images):
                continue  # Groq's free model can't see images
            steps.append((provider, name))
        # Skip models that failed a moment ago, unless every model is resting (then try them all).
        now = time.time()
        awake = [step for step in steps if self._resting.get(step, 0) <= now]
        return awake or steps

    def _rest(self, provider, name, reason):
        seconds = REST_SECONDS_OUT_OF_QUOTA if reason.status_code == 429 else REST_SECONDS_OTHER
        self._resting[(provider, name)] = time.time() + seconds
        print(f"AI {provider}/{name} unavailable ({reason.status_code or reason}); "
              f"skipping it for {seconds}s and trying the next model")

    def _awake(self, provider, name):
        self._resting.pop((provider, name), None)

    def chat(self, model, messages, format=None, options=None, stream=False, think=None, **_ignored):
        # `think` was an Ollama setting; these models decide how much to think on their own.
        temperature = (options or {}).get("temperature")
        steps = self._chain(model, messages)
        if stream:
            return self._stream(steps, messages, format, temperature)

        report = _new_report()
        last = None
        for provider, name in steps:
            tried = time.time()
            try:
                text = self._ask(provider, name, messages, format, temperature)
                self._awake(provider, name)
                self._finish(report, provider, name, tried, ok=True)
                return _wrap(text)
            except _TryNext as reason:
                self._finish(report, provider, name, tried, ok=False, reason=reason)
                self._rest(provider, name, reason)
                last = reason
        self._finish(report, None, None, None, ok=False)
        raise _final_error(last)

    def last_report(self):
        """A one-line summary of the most recent reply on this thread (for logs and debugging)."""
        return _report_text(getattr(_local, "report", None))

    def _finish(self, report, provider, name, tried, ok, reason=None):
        now = time.time()
        if provider:
            outcome = "ok" if ok else str(getattr(reason, "status_code", None) or "error")
            report["tries"].append({"model": f"{provider}/{name}", "outcome": outcome,
                                    "seconds": now - tried})
            if ok:
                report["answered_by"] = f"{provider}/{name}"
        if ok or provider is None:
            report["total_s"] = now - report["started"]
            print("AI timing:", _report_text(report))

    def _stream(self, steps, messages, format, temperature):
        report = _new_report()
        last = None
        for provider, name in steps:
            started = False
            tried = time.time()
            try:
                for text in self._ask_stream(provider, name, messages, format, temperature):
                    if text:
                        if not started:
                            started = True
                            self._awake(provider, name)
                            report["first_words_s"] = time.time() - report["started"]
                        yield _wrap(text)
                self._finish(report, provider, name, tried, ok=True)
                return
            except _TryNext as reason:
                # Once part of a reply has been shown, switching models would mix two answers.
                if started:
                    self._finish(report, provider, name, tried, ok=False, reason=reason)
                    self._finish(report, None, None, None, ok=False)
                    raise _final_error(reason) from reason
                self._finish(report, provider, name, tried, ok=False, reason=reason)
                self._rest(provider, name, reason)
                last = reason
        self._finish(report, None, None, None, ok=False)
        raise _final_error(last)

    # ---------- one attempt ----------

    def _ask(self, provider, name, messages, format, temperature):
        if provider == "gemini":
            system, contents = _gemini_messages(messages)
            try:
                try:
                    config = _gemini_config(system, format, temperature, think_low=True)
                    return self._gemini.models.generate_content(model=name, contents=contents, config=config).text
                except errors.APIError as error:
                    if not _rejected_thinking(error):
                        raise
                    _note(f"{name} rejected thinking setting, asked again without it")
                    config = _gemini_config(system, format, temperature, think_low=False)
                    return self._gemini.models.generate_content(model=name, contents=contents, config=config).text
            except errors.APIError as error:
                raise _gemini_error(error) from error
            except Exception as error:  # timeouts, dropped connections, odd replies
                raise _TryNext(f"gemini failed: {type(error).__name__}: {error}") from error
        return "".join(self._openai_style(provider, name, messages, format, temperature, stream=False))

    def _ask_stream(self, provider, name, messages, format, temperature):
        if provider == "gemini":
            system, contents = _gemini_messages(messages)
            try:
                think_low = True
                while True:
                    started = False
                    try:
                        config = _gemini_config(system, format, temperature, think_low=think_low)
                        for chunk in self._gemini.models.generate_content_stream(
                            model=name, contents=contents, config=config
                        ):
                            started = True
                            yield chunk.text
                        break
                    except errors.APIError as error:
                        if started or not think_low or not _rejected_thinking(error):
                            raise
                        think_low = False  # this model won't take the thinking setting; ask again without it
                        _note(f"{name} rejected thinking setting, asked again without it")
            except errors.APIError as error:
                raise _gemini_error(error) from error
            except Exception as error:  # timeouts, dropped connections, odd replies
                raise _TryNext(f"gemini failed: {type(error).__name__}: {error}") from error
            return
        yield from self._openai_style(provider, name, messages, format, temperature, stream=True)

    def _openai_style(self, provider, name, messages, format, temperature, stream):
        """Cloudflare and Groq both speak the OpenAI chat format."""
        if provider == "cloudflare":
            account_id, token = self._cloudflare
            url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
            images_ok = True
        else:
            url, token = "https://api.groq.com/openai/v1/chat/completions", self._groq_key
            images_ok = False

        body = {"model": name, "messages": _openai_messages(messages, images_ok), "stream": stream}
        if temperature is not None:
            body["temperature"] = temperature
        if format == "json":
            body["response_format"] = {"type": "json_object"}
        if provider == "groq":
            body["reasoning_effort"] = "low"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            with httpx.Client(timeout=self._timeout) as http:
                if not stream:
                    response = http.post(url, json=body, headers=headers)
                    _check(provider, response)
                    data = response.json()
                    yield (data["choices"][0]["message"].get("content") or "")
                    return
                with http.stream("POST", url, json=body, headers=headers) as response:
                    if response.status_code >= 400:
                        response.read()
                    _check(provider, response)
                    reasoning_chars = 0
                    reasoning_started = None
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        choices = json.loads(payload).get("choices") or [{}]
                        delta = choices[0].get("delta") or {}
                        # Some models "think" silently first; that text isn't shown, but count it.
                        thought = delta.get("reasoning_content") or delta.get("reasoning") or ""
                        if thought:
                            reasoning_started = reasoning_started or time.time()
                            reasoning_chars += len(thought)
                        content = delta.get("content") or ""
                        if content and reasoning_chars and reasoning_started:
                            _note(f"{provider} thought silently for {time.time() - reasoning_started:.1f}s "
                                  f"({reasoning_chars} chars) before writing")
                            reasoning_started = None
                        yield content
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise _TryNext(f"{provider} timed out or couldn't connect: {type(error).__name__}") from error
        except (KeyError, IndexError, ValueError) as error:
            raise _TryNext(f"{provider} sent a reply this app couldn't read: {error}") from error


def _check(provider, response):
    """Any failure from a backup moves on to the next model, never stops the chain.

    A bad key or a request this model can't handle shouldn't block the models after it, so
    even 4xx answers move on (the reason is printed to the app's logs).
    """
    if response.status_code < 400:
        return
    detail = response.text[:300].replace("\n", " ")
    raise _TryNext(f"{provider} said {response.status_code}: {detail}", response.status_code)


# ------------------------------------------------------------------------------------------
# Message conversion
# ------------------------------------------------------------------------------------------

def _gemini_config(system, format, temperature, think_low=True):
    return types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json" if format == "json" else None,
        thinking_config=types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL) if think_low else None,
    )


def _rejected_thinking(error):
    """True when a model said no to the thinking setting (then we ask again without it)."""
    return getattr(error, "code", None) == 400 and "think" in str(error).lower()


def _gemini_messages(messages):
    """Ollama-style messages → (system instruction, Gemini contents)."""
    system_parts = []
    contents = []
    for message in messages:
        role = message.get("role")
        text = str(message.get("content") or "")
        if role == "system":
            if text.strip():
                system_parts.append(text)
            continue

        parts = []
        if text.strip():
            parts.append(types.Part(text=text))
        for image in message.get("images") or []:
            image = _as_b64(image)
            parts.append(types.Part.from_bytes(data=base64.b64decode(image), mime_type=_mime_type(image)))
        if not parts:
            continue  # Gemini rejects empty messages (e.g. a blank assistant reply)

        contents.append(types.Content(role="model" if role == "assistant" else "user", parts=parts))

    if not contents:
        contents.append(types.Content(role="user", parts=[types.Part(text="Hello")]))
    return "\n\n".join(system_parts) or None, contents


def _openai_messages(messages, images_ok):
    """Ollama-style messages → OpenAI chat messages (images as data URLs when supported)."""
    converted = []
    for message in messages:
        role = message.get("role") or "user"
        text = str(message.get("content") or "")
        images = [_as_b64(image) for image in (message.get("images") or [])]
        if role == "assistant" and not text.strip():
            continue
        if images and images_ok and role == "user":
            parts = [{"type": "text", "text": text or "(see image)"}]
            for image in images:
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{_mime_type(image)};base64,{image}"},
                })
            converted.append({"role": role, "content": parts})
        else:
            if images:
                text = (text + "\n\n[The user attached an image here.]").strip()
            converted.append({"role": role, "content": text})
    return converted
