#!/usr/bin/env python3
"""
Mock Cloud Backend Server

Simulates a slow LLM API (like Google Gemini) that takes 30 seconds to respond.
Logs all connection events to help debug client disconnection behavior.

Run: python server.py
Listens on: http://localhost:9000
"""

import asyncio
import logging
import time
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mock Cloud Backend")

# Track active requests
active_requests: dict = {}
request_counter = 0


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    Mock chat completions endpoint that simulates a 30-second thinking delay.
    """
    global request_counter
    request_counter += 1
    request_id = request_counter
    start_time = time.time()
    
    logger.info(f"CLIENT_DISCONNECT: [REQ-{request_id}] Request received from {request.client.host}")
    active_requests[request_id] = {
        "start_time": start_time,
        "status": "processing",
    }
    
    try:
        # Read the request body
        body = await request.json()
        model = body.get("model", "unknown")
        logger.info(f"CLIENT_DISCONNECT: [REQ-{request_id}] Model: {model}, starting 30s thinking delay...")
        
        # Simulate long thinking time (30 seconds)
        # Check periodically if connection is still alive
        think_duration = 30
        check_interval = 1.0
        elapsed = 0
        
        while elapsed < think_duration:
            await asyncio.sleep(check_interval)
            elapsed = time.time() - start_time
            
            # Check if client disconnected
            if await request.is_disconnected():
                logger.warning(
                    f"CLIENT_DISCONNECT: [REQ-{request_id}] Client disconnected after {elapsed:.1f}s! "
                    f"Stopping processing."
                )
                active_requests[request_id]["status"] = "client_disconnected"
                return JSONResponse(
                    status_code=499,
                    content={"error": "Client disconnected"},
                )
            
            if int(elapsed) % 5 == 0 and elapsed > 0:
                logger.debug(
                    f"CLIENT_DISCONNECT: [REQ-{request_id}] Still thinking... {elapsed:.1f}s elapsed"
                )
        
        # Thinking complete, prepare response
        total_time = time.time() - start_time
        logger.info(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] Thinking complete after {total_time:.1f}s, "
            f"sending response..."
        )
        
        response_data = {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"This is a mock response after {total_time:.1f}s of thinking.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        }
        
        active_requests[request_id]["status"] = "completed"
        logger.info(f"CLIENT_DISCONNECT: [REQ-{request_id}] Response sent successfully")
        
        return JSONResponse(content=response_data)
        
    except asyncio.CancelledError:
        elapsed = time.time() - start_time
        logger.warning(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] Request CANCELLED after {elapsed:.1f}s!"
        )
        active_requests[request_id]["status"] = "cancelled"
        raise
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] Error after {elapsed:.1f}s: {type(e).__name__}: {e}"
        )
        active_requests[request_id]["status"] = "error"
        raise


@app.get("/status")
async def status():
    """Return status of all requests."""
    return {
        "total_requests": request_counter,
        "active_requests": {
            k: v for k, v in active_requests.items() 
            if v["status"] == "processing"
        },
        "all_requests": active_requests,
    }


@app.on_event("startup")
async def startup():
    logger.info("CLIENT_DISCONNECT: Mock Cloud Server starting on port 9000")


@app.on_event("shutdown")
async def shutdown():
    logger.info("CLIENT_DISCONNECT: Mock Cloud Server shutting down")
    logger.info(f"CLIENT_DISCONNECT: Total requests processed: {request_counter}")
    for req_id, info in active_requests.items():
        logger.info(f"CLIENT_DISCONNECT: [REQ-{req_id}] Final status: {info['status']}")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9000,
        log_level="warning",  # Reduce uvicorn noise, we have our own logging
    )

