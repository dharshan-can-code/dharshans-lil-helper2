"""Drop-in replacement for the parts of `ollama.Client` this app uses, powered by
Google's Gemini API free tier (https://aistudio.google.com).

It keeps the same call shape the app already uses, so the rest of the code doesn't change:

    client = Client(api_key=..., timeout=90)
    response = client.chat(model=..., messages=[...], format="json", options={"temperature": 0.3})
    response.message.content                      # the reply text

    for chunk in client.chat(model=..., messages=[...], stream=True):
        chunk.message.content                     # each piece of a streamed reply

Messages use Ollama's format: {"role": "system" | "user" | "assistant", "content": "...",
"images": [<base64 strings>]}.
"""

import base64
from types import SimpleNamespace

from google import genai
from google.genai import errors, types


class ResponseError(Exception):
    """Raised when the Gemini API returns an error (same name the app used with Ollama)."""

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


def _convert(messages):
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
            if isinstance(image, (bytes, bytearray)):
                image = base64.b64encode(image).decode("utf-8")
            parts.append(types.Part.from_bytes(data=base64.b64decode(image), mime_type=_mime_type(image)))
        if not parts:
            continue  # Gemini rejects empty messages (e.g. a blank assistant reply)

        contents.append(types.Content(role="model" if role == "assistant" else "user", parts=parts))

    if not contents:
        contents.append(types.Content(role="user", parts=[types.Part(text="Hello")]))
    return "\n\n".join(system_parts) or None, contents


def _friendly_error(error):
    code = getattr(error, "code", None)
    if code == 429:
        return ResponseError(
            "The free AI limit has been reached for now. Please try again in a few minutes.", 429
        )
    if code in (401, 403):
        return ResponseError("The Gemini API key is missing or invalid. Check GEMINI_API_KEY in your secrets.", code)
    if code == 404:
        return ResponseError(f"That Gemini model isn't available: {error}", 404)
    return ResponseError(str(error), code)


class Client:
    def __init__(self, api_key, timeout=None):
        http_options = types.HttpOptions(timeout=int(timeout * 1000)) if timeout else None
        self._client = genai.Client(api_key=api_key, http_options=http_options)

    def chat(self, model, messages, format=None, options=None, stream=False, think=None, **_ignored):
        # `think` was an Ollama setting. Gemini decides how much to think on its own, so it's ignored.
        system, contents = _convert(messages)
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=(options or {}).get("temperature"),
            response_mime_type="application/json" if format == "json" else None,
        )
        if stream:
            return self._stream(model, contents, config)
        try:
            response = self._client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as error:
            raise _friendly_error(error) from error
        return _wrap(response.text)

    def _stream(self, model, contents, config):
        try:
            for chunk in self._client.models.generate_content_stream(model=model, contents=contents, config=config):
                text = chunk.text
                if text:
                    yield _wrap(text)
        except errors.APIError as error:
            raise _friendly_error(error) from error
