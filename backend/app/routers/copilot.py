import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent import loop

router = APIRouter(prefix="/copilot", tags=["copilot"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@router.get("/status")
def status():
    from ..config import settings
    return {"configured": loop.configured(), "model": settings.openrouter_model}


@router.post("/chat")
async def chat(req: ChatRequest):
    """Server-sent events stream of agent tool calls and the final answer."""
    history = [{"role": m.role, "content": m.content} for m in req.messages]

    async def gen():
        async for event in loop.run(history):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
