#!/bin/bash
#
# Run the client disconnect experiment
#
# This script starts all three components and runs the test.
# Watch the logs to see how client disconnection is (not) propagated.
#
# Usage: ./run_test.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Client Disconnect Experiment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}Cleaning up...${NC}"
    
    # Kill background processes
    if [ ! -z "$SERVER_PID" ]; then
        echo "Stopping server (PID: $SERVER_PID)..."
        kill $SERVER_PID 2>/dev/null || true
    fi
    
    if [ ! -z "$MIDDLEWARE_PID" ]; then
        echo "Stopping middleware (PID: $MIDDLEWARE_PID)..."
        kill $MIDDLEWARE_PID 2>/dev/null || true
    fi
    
    # Wait a moment for processes to terminate
    sleep 1
    
    # Force kill if still running
    kill -9 $SERVER_PID 2>/dev/null || true
    kill -9 $MIDDLEWARE_PID 2>/dev/null || true
    
    echo -e "${GREEN}Cleanup complete${NC}"
}

# Set trap to cleanup on exit
trap cleanup EXIT INT TERM

# Check if ports are available
check_port() {
    local port=$1
    if lsof -i :$port > /dev/null 2>&1; then
        echo -e "${RED}Error: Port $port is already in use${NC}"
        echo "Please stop any process using port $port and try again."
        exit 1
    fi
}

echo "Checking if ports are available..."
check_port 8000
check_port 9000
echo -e "${GREEN}Ports 8000 and 9000 are available${NC}"
echo ""

# Start the mock cloud server
echo -e "${BLUE}Starting mock cloud server on port 9000...${NC}"
python server.py &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"

# Wait for server to start
sleep 2

# Check if server is running
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo -e "${RED}Error: Server failed to start${NC}"
    exit 1
fi

echo -e "${GREEN}Server started successfully${NC}"
echo ""

# Start the middleware
echo -e "${BLUE}Starting middleware on port 8000...${NC}"
python middleware.py &
MIDDLEWARE_PID=$!
echo "Middleware PID: $MIDDLEWARE_PID"

# Wait for middleware to start
sleep 2

# Check if middleware is running
if ! kill -0 $MIDDLEWARE_PID 2>/dev/null; then
    echo -e "${RED}Error: Middleware failed to start${NC}"
    exit 1
fi

echo -e "${GREEN}Middleware started successfully${NC}"
echo ""

# Run the test client
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Running test client...${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}The client will:${NC}"
echo "  1. Send a request to middleware"
echo "  2. Wait 2 seconds"
echo "  3. Disconnect"
echo ""
echo -e "${YELLOW}Watch for:${NC}"
echo "  - Does middleware detect the disconnect?"
echo "  - Does middleware cancel the task?"
echo "  - Does the backend request continue anyway?"
echo "  - Does the backend complete after 30s despite client disconnect?"
echo ""
echo -e "${BLUE}========================================${NC}"
echo ""

# Run the client (this will take ~45 seconds)
python client.py

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Experiment complete${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Analysis:${NC}"
echo ""
echo "If you see the backend server log 'Response sent successfully'"
echo "AFTER the client disconnected, it confirms the bug:"
echo ""
echo "  task.cancel() does NOT stop threads in run_in_executor()"
echo ""
echo "The solution would be to:"
echo "  1. Use async HTTP client (httpx.AsyncClient) directly"
echo "  2. Or implement cooperative cancellation in the sync code"
echo "  3. Or use asyncio-native patterns throughout"
echo ""

# Cleanup is handled by trap

