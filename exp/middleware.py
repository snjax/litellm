#!/usr/bin/env python3
"""
LiteLLM Flow Reproduction Middleware

This middleware reproduces the exact asyncio/threading flow from LiteLLM to debug
why client disconnection doesn't cancel upstream cloud requests.

TWO MODES:
1. USE_ASYNC_CLIENT=False (default): Uses run_in_executor like LiteLLM - BROKEN
2. USE_ASYNC_CLIENT=True: Uses async httpx directly - WORKS

Run: python middleware.py
Listens on: http://localhost:8000
Forwards to: http://localhost:9000
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="LiteLLM Flow Reproduction Middleware")

# Backend server URL
BACKEND_URL = "http://localhost:9000/v1/chat/completions"

# Thread pool executor (like LiteLLM uses)
executor = ThreadPoolExecutor(max_workers=10)

# SWITCH: Set to True to use async httpx (WORKS), False to use executor (BROKEN)
USE_ASYNC_CLIENT = True

# Request tracking
request_counter = 0

# Shared async httpx client
async_client: Optional[httpx.AsyncClient] = None


class ClientDisconnectedError(Exception):
    """Raised when the client disconnects during a request."""
    pass


async def _check_client_disconnection(
    request: Request,
    llm_call_task: asyncio.Task,
    request_id: int,
    check_interval: float = 0.5,
    max_duration: float = 18000.0,
) -> None:
    """
    Monitors for client disconnection and cancels the LLM call task if detected.
    
    This reproduces the exact logic from litellm/proxy/common_request_processing.py
    """
    start_time = time.time()
    check_count = 0
    
    logger.debug(
        f"CLIENT_DISCONNECT: [REQ-{request_id}] Starting disconnection checker - "
        f"check_interval={check_interval}s, task_id={id(llm_call_task)}"
    )
    
    while time.time() - start_time < max_duration:
        await asyncio.sleep(check_interval)
        check_count += 1
        elapsed = time.time() - start_time
        
        # Check task state first
        task_done = llm_call_task.done()
        task_cancelled = llm_call_task.cancelled() if task_done else False
        
        # Log every 4th check (every 2 seconds)
        if check_count % 4 == 0:
            logger.debug(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] Check #{check_count} - "
                f"elapsed={elapsed:.1f}s, task_done={task_done}"
            )
        
        # Check if client disconnected
        is_disconnected = await request.is_disconnected()
        
        if is_disconnected:
            logger.warning(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] CLIENT DISCONNECTED! "
                f"elapsed={elapsed:.1f}s, check_count={check_count}, "
                f"task_done={task_done}, task_cancelled={task_cancelled}"
            )
            
            if not task_done:
                logger.warning(
                    f"CLIENT_DISCONNECT: [REQ-{request_id}] Calling task.cancel()..."
                )
                cancel_result = llm_call_task.cancel()
                logger.warning(
                    f"CLIENT_DISCONNECT: [REQ-{request_id}] task.cancel() returned {cancel_result}"
                )
                
                # Give the task a moment to process the cancellation
                try:
                    await asyncio.wait_for(asyncio.shield(llm_call_task), timeout=0.1)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                except Exception as e:
                    logger.debug(
                        f"CLIENT_DISCONNECT: [REQ-{request_id}] Exception waiting for cancel: "
                        f"{type(e).__name__}: {e}"
                    )
                
                logger.warning(
                    f"CLIENT_DISCONNECT: [REQ-{request_id}] After cancel - "
                    f"task_done={llm_call_task.done()}, "
                    f"task_cancelled={llm_call_task.cancelled() if llm_call_task.done() else 'N/A'}"
                )
            else:
                logger.warning(
                    f"CLIENT_DISCONNECT: [REQ-{request_id}] Task already done, cannot cancel"
                )
            
            raise ClientDisconnectedError("Client disconnected the request")
        
        # If the LLM call completed, stop checking
        if task_done:
            logger.debug(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] Task completed normally - "
                f"elapsed={elapsed:.1f}s"
            )
            return


def sync_http_request(request_id: int, data: dict) -> dict:
    """
    Synchronous HTTP request function that runs in executor.
    
    This reproduces how litellm.completion() works - it's a sync function
    that makes HTTP requests, and it's called via run_in_executor().
    
    IMPORTANT: This function runs in a THREAD, not in the asyncio event loop.
    When task.cancel() is called, it does NOT interrupt this thread!
    """
    start_time = time.time()
    
    logger.info(
        f"CLIENT_DISCONNECT: [REQ-{request_id}] [THREAD] sync_http_request STARTED "
        f"(thread will NOT be cancelled by task.cancel())"
    )
    
    try:
        # Create httpx client and make request
        with httpx.Client(timeout=60.0) as client:
            logger.info(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] [THREAD] Sending POST to backend..."
            )
            
            response = client.post(
                BACKEND_URL,
                json=data,
            )
            
            elapsed = time.time() - start_time
            logger.info(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] [THREAD] Response received! "
                f"status={response.status_code}, elapsed={elapsed:.1f}s"
            )
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] [THREAD] sync_http_request COMPLETED "
                f"after {elapsed:.1f}s"
            )
            
            return result
            
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] [THREAD] sync_http_request ERROR "
            f"after {elapsed:.1f}s: {type(e).__name__}: {e}"
        )
        raise


async def acompletion_with_executor(request_id: int, data: dict) -> dict:
    """
    BROKEN: Async completion using run_in_executor (like LiteLLM does).
    
    When task.cancel() is called, it only cancels the await - 
    the thread in executor continues running!
    """
    loop = asyncio.get_event_loop()
    
    logger.debug(
        f"CLIENT_DISCONNECT: [REQ-{request_id}] acompletion_with_executor - "
        f"starting run_in_executor (BROKEN - thread won't be cancelled)"
    )
    
    func = partial(sync_http_request, request_id, data)
    
    try:
        result = await loop.run_in_executor(executor, func)
        
        logger.debug(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] acompletion_with_executor - completed"
        )
        
        return result
        
    except asyncio.CancelledError:
        logger.warning(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] acompletion_with_executor - "
            f"CancelledError caught! BUT the thread in executor is STILL RUNNING!"
        )
        raise


async def acompletion_with_async_client(request_id: int, data: dict) -> dict:
    """
    FIXED: Async completion using async httpx client directly.
    
    When task.cancel() is called, the async HTTP request is properly cancelled
    and the connection to backend is closed immediately.
    """
    global async_client
    
    start_time = time.time()
    
    logger.info(
        f"CLIENT_DISCONNECT: [REQ-{request_id}] [ASYNC] acompletion_with_async_client STARTED "
        f"(will be properly cancelled by task.cancel())"
    )
    
    try:
        logger.info(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] [ASYNC] Sending POST to backend..."
        )
        
        response = await async_client.post(
            BACKEND_URL,
            json=data,
        )
        
        elapsed = time.time() - start_time
        logger.info(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] [ASYNC] Response received! "
            f"status={response.status_code}, elapsed={elapsed:.1f}s"
        )
        
        response.raise_for_status()
        result = response.json()
        
        logger.info(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] [ASYNC] acompletion_with_async_client COMPLETED "
            f"after {elapsed:.1f}s"
        )
        
        return result
        
    except asyncio.CancelledError:
        elapsed = time.time() - start_time
        logger.warning(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] [ASYNC] CancelledError caught after {elapsed:.1f}s! "
            f"Connection to backend PROPERLY CLOSED."
        )
        raise
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] [ASYNC] ERROR after {elapsed:.1f}s: "
            f"{type(e).__name__}: {e}"
        )
        raise


async def acompletion(request_id: int, data: dict) -> dict:
    """
    Async completion function - switches between broken and fixed implementations.
    """
    if USE_ASYNC_CLIENT:
        return await acompletion_with_async_client(request_id, data)
    else:
        return await acompletion_with_executor(request_id, data)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    Main endpoint that reproduces LiteLLM proxy flow.
    """
    global request_counter
    request_counter += 1
    request_id = request_counter
    start_time = time.time()
    
    logger.info(
        f"CLIENT_DISCONNECT: [REQ-{request_id}] ===== REQUEST RECEIVED ====="
    )
    
    try:
        # Read request body
        data = await request.json()
        logger.debug(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] Request data: model={data.get('model')}"
        )
        
        # Create the LLM call coroutine
        llm_call_coro = acompletion(request_id, data)
        
        # Create a task for the LLM call (like LiteLLM does)
        llm_call_task = asyncio.create_task(llm_call_coro)
        
        logger.debug(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] Created LLM call task - "
            f"task_id={id(llm_call_task)}"
        )
        
        # Create disconnection checker task
        disconnection_checker_task = asyncio.create_task(
            _check_client_disconnection(
                request=request,
                llm_call_task=llm_call_task,
                request_id=request_id,
            )
        )
        
        logger.debug(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] Created disconnection checker task"
        )
        
        # Wait for LLM call (like asyncio.gather in LiteLLM)
        try:
            logger.debug(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] Awaiting LLM call task..."
            )
            
            response = await llm_call_task
            
            elapsed = time.time() - start_time
            logger.info(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] LLM call completed successfully "
                f"after {elapsed:.1f}s"
            )
            
            return JSONResponse(content=response)
            
        except asyncio.CancelledError:
            elapsed = time.time() - start_time
            logger.warning(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] asyncio.CancelledError caught "
                f"after {elapsed:.1f}s"
            )
            raise HTTPException(
                status_code=499,
                detail="Client disconnected the request",
            )
        except ClientDisconnectedError as e:
            elapsed = time.time() - start_time
            logger.warning(
                f"CLIENT_DISCONNECT: [REQ-{request_id}] ClientDisconnectedError caught "
                f"after {elapsed:.1f}s"
            )
            raise HTTPException(
                status_code=499,
                detail="Client disconnected the request",
            )
        finally:
            # Cancel the disconnection checker if it's still running
            if not disconnection_checker_task.done():
                logger.debug(
                    f"CLIENT_DISCONNECT: [REQ-{request_id}] Cancelling disconnection checker"
                )
                disconnection_checker_task.cancel()
                try:
                    await disconnection_checker_task
                except (asyncio.CancelledError, ClientDisconnectedError):
                    pass
                    
    except HTTPException:
        raise
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"CLIENT_DISCONNECT: [REQ-{request_id}] Unexpected error after {elapsed:.1f}s: "
            f"{type(e).__name__}: {e}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def status():
    """Return middleware status."""
    return {
        "total_requests": request_counter,
        "backend_url": BACKEND_URL,
        "use_async_client": USE_ASYNC_CLIENT,
    }


@app.on_event("startup")
async def startup():
    global async_client
    
    logger.info("CLIENT_DISCONNECT: Middleware starting on port 8000")
    logger.info(f"CLIENT_DISCONNECT: Backend URL: {BACKEND_URL}")
    logger.info(f"CLIENT_DISCONNECT: USE_ASYNC_CLIENT: {USE_ASYNC_CLIENT}")
    
    if USE_ASYNC_CLIENT:
        async_client = httpx.AsyncClient(timeout=60.0)
        logger.info("CLIENT_DISCONNECT: Created async httpx client")


@app.on_event("shutdown")
async def shutdown():
    global async_client
    
    logger.info("CLIENT_DISCONNECT: Middleware shutting down")
    logger.info(f"CLIENT_DISCONNECT: Total requests processed: {request_counter}")
    
    if async_client:
        await async_client.aclose()
        logger.info("CLIENT_DISCONNECT: Closed async httpx client")
    
    executor.shutdown(wait=False)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="warning",  # Reduce uvicorn noise
    )

