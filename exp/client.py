#!/usr/bin/env python3
"""
Test Client for Client Disconnection Experiment

Makes a request to the middleware, waits 2 seconds, then forcefully closes the connection.
This simulates a client that disconnects during a long-running LLM request.

Run: python client.py
Connects to: http://localhost:8000
"""

import asyncio
import logging
import socket
import time

import httpx

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MIDDLEWARE_URL = "http://localhost:8000/v1/chat/completions"
DISCONNECT_AFTER_SECONDS = 2.0


async def test_disconnect_with_httpx():
    """
    Test using httpx with a short timeout to simulate disconnect.
    """
    logger.info("=" * 60)
    logger.info("CLIENT_DISCONNECT: Starting test with httpx timeout")
    logger.info("=" * 60)
    
    start_time = time.time()
    
    request_data = {
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "Hello, this is a test message"}
        ],
    }
    
    try:
        # Use a short timeout to force disconnect
        async with httpx.AsyncClient(timeout=DISCONNECT_AFTER_SECONDS) as client:
            logger.info(
                f"CLIENT_DISCONNECT: Sending request to {MIDDLEWARE_URL}"
            )
            logger.info(
                f"CLIENT_DISCONNECT: Will timeout/disconnect after {DISCONNECT_AFTER_SECONDS}s"
            )
            
            response = await client.post(
                MIDDLEWARE_URL,
                json=request_data,
            )
            
            elapsed = time.time() - start_time
            logger.info(
                f"CLIENT_DISCONNECT: Got response! status={response.status_code}, "
                f"elapsed={elapsed:.1f}s"
            )
            logger.info(f"CLIENT_DISCONNECT: Response: {response.text[:200]}")
            
    except httpx.TimeoutException as e:
        elapsed = time.time() - start_time
        logger.warning(
            f"CLIENT_DISCONNECT: TIMEOUT after {elapsed:.1f}s - connection dropped"
        )
        logger.warning(f"CLIENT_DISCONNECT: Exception: {type(e).__name__}: {e}")
    except httpx.ReadTimeout as e:
        elapsed = time.time() - start_time
        logger.warning(
            f"CLIENT_DISCONNECT: READ TIMEOUT after {elapsed:.1f}s"
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"CLIENT_DISCONNECT: Unexpected error after {elapsed:.1f}s: "
            f"{type(e).__name__}: {e}"
        )


async def test_disconnect_with_cancel():
    """
    Test using asyncio.wait_for to cancel the request after timeout.
    """
    logger.info("=" * 60)
    logger.info("CLIENT_DISCONNECT: Starting test with asyncio cancellation")
    logger.info("=" * 60)
    
    start_time = time.time()
    
    request_data = {
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "Hello, this is a test message"}
        ],
    }
    
    async def make_request():
        async with httpx.AsyncClient(timeout=60.0) as client:
            return await client.post(
                MIDDLEWARE_URL,
                json=request_data,
            )
    
    try:
        logger.info(
            f"CLIENT_DISCONNECT: Sending request to {MIDDLEWARE_URL}"
        )
        logger.info(
            f"CLIENT_DISCONNECT: Will cancel after {DISCONNECT_AFTER_SECONDS}s"
        )
        
        response = await asyncio.wait_for(
            make_request(),
            timeout=DISCONNECT_AFTER_SECONDS,
        )
        
        elapsed = time.time() - start_time
        logger.info(
            f"CLIENT_DISCONNECT: Got response! status={response.status_code}, "
            f"elapsed={elapsed:.1f}s"
        )
        
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        logger.warning(
            f"CLIENT_DISCONNECT: asyncio.TimeoutError after {elapsed:.1f}s - "
            f"request cancelled"
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"CLIENT_DISCONNECT: Unexpected error after {elapsed:.1f}s: "
            f"{type(e).__name__}: {e}"
        )


def test_disconnect_with_raw_socket():
    """
    Test using raw socket to forcefully close connection.
    This most accurately simulates a real client disconnect.
    """
    logger.info("=" * 60)
    logger.info("CLIENT_DISCONNECT: Starting test with raw socket disconnect")
    logger.info("=" * 60)
    
    start_time = time.time()
    
    # Create raw socket connection
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(60.0)
    
    try:
        logger.info("CLIENT_DISCONNECT: Connecting to localhost:8000...")
        sock.connect(("localhost", 8000))
        
        # Send HTTP request
        request_body = '{"model": "test-model", "messages": [{"role": "user", "content": "Hello"}]}'
        http_request = (
            f"POST /v1/chat/completions HTTP/1.1\r\n"
            f"Host: localhost:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(request_body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{request_body}"
        )
        
        logger.info("CLIENT_DISCONNECT: Sending HTTP request...")
        sock.sendall(http_request.encode())
        
        # Wait for specified time
        logger.info(
            f"CLIENT_DISCONNECT: Waiting {DISCONNECT_AFTER_SECONDS}s before disconnect..."
        )
        time.sleep(DISCONNECT_AFTER_SECONDS)
        
        # Forcefully close the connection
        elapsed = time.time() - start_time
        logger.warning(
            f"CLIENT_DISCONNECT: FORCEFULLY CLOSING SOCKET after {elapsed:.1f}s"
        )
        
        # Use SO_LINGER with timeout=0 to force RST instead of FIN
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b'\x01\x00\x00\x00\x00\x00\x00\x00')
        sock.close()
        
        logger.warning("CLIENT_DISCONNECT: Socket closed with RST")
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"CLIENT_DISCONNECT: Error after {elapsed:.1f}s: {type(e).__name__}: {e}"
        )
    finally:
        try:
            sock.close()
        except:
            pass


async def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("CLIENT_DISCONNECT: CLIENT TEST STARTING")
    logger.info(f"CLIENT_DISCONNECT: Target: {MIDDLEWARE_URL}")
    logger.info(f"CLIENT_DISCONNECT: Disconnect after: {DISCONNECT_AFTER_SECONDS}s")
    logger.info("=" * 60)
    
    # Test 1: httpx timeout
    await test_disconnect_with_httpx()
    
    logger.info("")
    logger.info("Waiting 5 seconds before next test...")
    logger.info("(Watch the server/middleware logs to see if request continues)")
    logger.info("")
    await asyncio.sleep(5)
    
    # Test 2: asyncio cancellation  
    await test_disconnect_with_cancel()
    
    logger.info("")
    logger.info("Waiting 5 seconds before next test...")
    await asyncio.sleep(5)
    
    # Test 3: Raw socket disconnect
    test_disconnect_with_raw_socket()
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("CLIENT_DISCONNECT: ALL TESTS COMPLETED")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Now watch the server/middleware logs for ~30 more seconds")
    logger.info("to see if the backend request completes despite client disconnect.")
    logger.info("")
    
    # Wait to see what happens on the server side
    logger.info("Waiting 35 seconds to observe server behavior...")
    await asyncio.sleep(35)
    
    logger.info("CLIENT_DISCONNECT: Client test finished")


if __name__ == "__main__":
    asyncio.run(main())

