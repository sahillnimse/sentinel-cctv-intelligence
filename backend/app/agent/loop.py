"""OpenRouter agentic loop for the SENTINEL copilot.

Streams the model's reasoning/answer and executes tool calls against the live
database. OpenRouter is OpenAI-compatible, so this uses the plain chat
completions API with function calling. No SDK dependency — httpx only.
"""

import json
from collections.abc import AsyncGenerator

import httpx

from ..config import settings
from ..db import SessionLocal
from .tools import TOOL_IMPL, TOOL_SCHEMAS

SYSTEM_PROMPT = """You are the SENTINEL copilot — an investigative assistant embedded in \
Gujarat Police's unified CCTV intelligence platform. You help officers query a live network \
of ANPR cameras that read vehicle number plates across the state.

Capabilities (via tools): overall system status, camera inventory, vehicle route \
reconstruction from a plate number, recent detections, fuzzy plate search, watchlist \
management, and alert review.

Style: terse, factual, operational — you are talking to a control-room operator, not a \
customer. Lead with the answer. When you trace a vehicle, summarize the route as a short \
ordered list of camera + time, and note the first/last seen. Indian plates look like \
GJ01AB1234; OCR is noisy, so prefer fuzzy matching and say when a match is approximate. \
Never invent sightings or plates — only report what the tools return. Before adding to the \
watchlist, restate the exact plate and reason you are about to add. If a query is ambiguous, \
ask one sharp clarifying question rather than guessing."""


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.openrouter_base_url,
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "HTTP-Referer": "https://sentinel.gujarat.gov.in",
            "X-Title": "SENTINEL Copilot",
        },
        timeout=60.0,
    )


def configured() -> bool:
    return bool(settings.openrouter_api_key)


async def run(messages: list[dict], max_rounds: int = 6) -> AsyncGenerator[dict, None]:
    """Yield SSE-style events: {type: 'tool', ...}, {type: 'token', ...},
    {type: 'final', ...}, {type: 'error', ...}."""
    if not configured():
        yield {"type": "error", "message": "OpenRouter API key not set. Add OPENROUTER_API_KEY to backend/.env."}
        return

    convo = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]

    async with _client() as client:
        for _ in range(max_rounds):
            try:
                resp = await client.post("/chat/completions", json={
                    "model": settings.openrouter_model,
                    "messages": convo,
                    "tools": TOOL_SCHEMAS,
                    "tool_choice": "auto",
                    "temperature": 0.2,
                })
            except httpx.HTTPError as exc:
                yield {"type": "error", "message": f"OpenRouter request failed: {exc}"}
                return

            if resp.status_code != 200:
                yield {"type": "error", "message": f"OpenRouter {resp.status_code}: {resp.text[:300]}"}
                return

            choice = resp.json()["choices"][0]["message"]
            tool_calls = choice.get("tool_calls")

            if not tool_calls:
                yield {"type": "final", "content": choice.get("content", "")}
                return

            convo.append({"role": "assistant", "content": choice.get("content"),
                          "tool_calls": tool_calls})

            db = SessionLocal()
            try:
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield {"type": "tool", "name": name, "args": args}
                    impl = TOOL_IMPL.get(name)
                    if impl is None:
                        result = {"error": f"unknown tool {name}"}
                    else:
                        try:
                            result = impl(db, **args)
                        except Exception as exc:  # surface tool errors to the model
                            result = {"error": f"{type(exc).__name__}: {exc}"}
                    convo.append({"role": "tool", "tool_call_id": tc["id"],
                                  "name": name, "content": json.dumps(result, default=str)})
            finally:
                db.close()

        yield {"type": "final", "content": "Reached the tool-call limit without a final answer."}
