"""Local, single-worker HTTP boundary. Research state lasts only for a request."""
import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.agent.graph import run_research
from app.providers.demo import DemoModel
from app.providers.openrouter import create_model, ModelProviderError, MODEL
from app.providers.sec import SECClient
from app.tools.registry import ToolRegistry
from app.ideas.models import IdeasRequest, IdeasClarification
from app.ideas.graph import run_ideas, SYSTEM as IDEAS_SYSTEM

from app.assistant import AssistantRequest,run_assistant

app = FastAPI(title="Local financial research")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
executor = ThreadPoolExecutor(max_workers=1)
busy = False


class ResearchRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    mode: Literal["live", "demo"] = "live"

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value


@app.get("/health")
def health():
    return {"status": "ok", "sec_configured": bool(os.getenv("SEC_USER_AGENT")),
            "busy": busy, "provider": os.getenv("LLM_PROVIDER", "ollama"), "model": MODEL if os.getenv("LLM_PROVIDER", "ollama").lower()=="openrouter" else os.getenv("OLLAMA_MODEL", "gemma4:e4b")}


def perform_research(payload, emit):
    sec = None
    try:
        if payload.mode == "live":
            sec = SECClient(os.getenv("SEC_USER_AGENT", ""))
        model = DemoModel() if payload.mode == "demo" else create_model()
        state = run_research(payload.question, model, registry=ToolRegistry(sec=sec), on_event=emit)
        return state["report"]
    finally:
        if sec:
            sec.close()


def perform_ideas(payload, emit):
    sec = SECClient(os.getenv("SEC_USER_AGENT", ""))
    try:
        return run_ideas(payload, create_model(system_prompt=IDEAS_SYSTEM), ToolRegistry(sec=sec), emit)
    finally:
        sec.close()


@app.post('/assistant')
async def assistant(payload: AssistantRequest):
    return await stream_run(payload,run_assistant,payload.mode=='live')


@app.post("/stock-ideas")
async def stock_ideas(payload: IdeasRequest):
    return await stream_run(payload, perform_ideas, True)


@app.post("/research")
async def research(payload: ResearchRequest):
    return await stream_run(payload, perform_research, payload.mode == "live")


async def stream_run(payload, runner, needs_sec):
    global busy
    if busy:
        raise HTTPException(409, "A research run is already active. Try again when it finishes.")
    if needs_sec and not os.getenv("SEC_USER_AGENT"):
        raise HTTPException(503, "SEC contact is missing. Load .env before starting the backend.")
    if needs_sec:
        try:
            create_model()
        except ModelProviderError as error:
            raise HTTPException(503, str(error)) from None
    busy = True
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    def emit(event):
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "progress", **event})

    def finished(future):
        global busy
        busy = False
        try:
            queue.put_nowait({"type": "report", "report": future.result()})
        except (IdeasClarification, ModelProviderError) as error:
            queue.put_nowait({"type": "error", "message": str(error)})
        except Exception:
            logging.exception("Research run failed")
            queue.put_nowait({"type": "error", "message": "Research failed. Check the model provider and the backend terminal, then retry."})

    # Do not cancel the running thread on disconnect or free the slot prematurely.
    future = loop.run_in_executor(executor, runner, payload, emit)
    future.add_done_callback(finished)

    async def stream():
        yield json.dumps({"type": "started"}) + "\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except asyncio.TimeoutError:
                yield json.dumps({"type": "heartbeat"}) + "\n"
                continue
            yield json.dumps(event) + "\n"
            if event["type"] in {"report", "error"}:
                return

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
