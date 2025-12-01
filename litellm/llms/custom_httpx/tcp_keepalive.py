"""
TCP Keepalive configuration utilities for long-running LLM connections.

This module provides cross-platform TCP keepalive configuration for aiohttp and httpx
clients. TCP keepalive sends periodic probes to keep connections alive through firewalls,
load balancers, and NAT gateways that may drop idle connections.

For models with extended thinking (hours of processing), TCP keepalive is critical because:
1. Intermediate network devices (AWS NLB, firewalls) have idle timeouts (often 60-350s)
2. Without keepalive probes, these devices silently drop the connection
3. The client only discovers the broken connection when trying to read the response

Usage:
    # For aiohttp - use socket_factory with TCPConnector
    from litellm.llms.custom_httpx.tcp_keepalive import create_keepalive_socket_factory
    
    connector = aiohttp.TCPConnector(socket_factory=create_keepalive_socket_factory())
    session = aiohttp.ClientSession(connector=connector)
    
    # For httpx - socket options are passed directly
    from litellm.llms.custom_httpx.tcp_keepalive import get_keepalive_socket_options
    
    # Use with httpcore connection pool
    socket_options = get_keepalive_socket_options()
"""

import logging
import socket
import sys
from typing import Any, Callable, List, Optional, Tuple

from litellm.constants import (
    TCP_KEEPALIVE_COUNT,
    TCP_KEEPALIVE_ENABLED,
    TCP_KEEPALIVE_IDLE,
    TCP_KEEPALIVE_INTERVAL,
)

logger = logging.getLogger(__name__)

# Type alias for socket options: (level, optname, value)
SocketOption = Tuple[int, int, int]


def _apply_keepalive_to_socket(
    sock: socket.socket,
    idle: int = TCP_KEEPALIVE_IDLE,
    interval: int = TCP_KEEPALIVE_INTERVAL,
    count: int = TCP_KEEPALIVE_COUNT,
) -> None:
    """
    Apply TCP keepalive settings to a socket with cross-platform support.
    
    Args:
        sock: The socket to configure
        idle: Seconds of idle time before first keepalive probe (TCP_KEEPIDLE)
        interval: Seconds between keepalive probes (TCP_KEEPINTVL)
        count: Number of failed probes before connection is considered dead (TCP_KEEPCNT)
    
    Platform differences:
        - Linux: Uses TCP_KEEPIDLE, TCP_KEEPINTVL, TCP_KEEPCNT
        - macOS: Uses TCP_KEEPALIVE (instead of TCP_KEEPIDLE), TCP_KEEPINTVL, TCP_KEEPCNT
        - Windows 10 1709+: Uses TCP_KEEPIDLE, TCP_KEEPINTVL, TCP_KEEPCNT via setsockopt
        - Older Windows: Uses SIO_KEEPALIVE_VALS via ioctl (only idle and interval)
    """
    if not TCP_KEEPALIVE_ENABLED:
        logger.debug("TCP keepalive disabled via TCP_KEEPALIVE_ENABLED")
        return
    
    try:
        # Enable SO_KEEPALIVE on the socket
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        logger.debug("SO_KEEPALIVE enabled on socket")
        
        # Platform-specific keepalive parameter configuration
        if sys.platform == "win32":
            _apply_windows_keepalive(sock, idle, interval, count)
        elif sys.platform == "darwin":
            _apply_macos_keepalive(sock, idle, interval, count)
        else:
            # Linux and other Unix-like systems
            _apply_linux_keepalive(sock, idle, interval, count)
            
    except OSError as e:
        logger.warning(f"Failed to configure TCP keepalive: {e}")


def _apply_linux_keepalive(
    sock: socket.socket, idle: int, interval: int, count: int
) -> None:
    """Apply TCP keepalive settings on Linux."""
    try:
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
            logger.debug(f"TCP_KEEPIDLE set to {idle}s")
    except (AttributeError, OSError) as e:
        logger.debug(f"Could not set TCP_KEEPIDLE: {e}")
    
    try:
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval)
            logger.debug(f"TCP_KEEPINTVL set to {interval}s")
    except (AttributeError, OSError) as e:
        logger.debug(f"Could not set TCP_KEEPINTVL: {e}")
    
    try:
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, count)
            logger.debug(f"TCP_KEEPCNT set to {count}")
    except (AttributeError, OSError) as e:
        logger.debug(f"Could not set TCP_KEEPCNT: {e}")


def _apply_macos_keepalive(
    sock: socket.socket, idle: int, interval: int, count: int
) -> None:
    """Apply TCP keepalive settings on macOS."""
    # macOS uses TCP_KEEPALIVE instead of TCP_KEEPIDLE
    try:
        if hasattr(socket, "TCP_KEEPALIVE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, idle)
            logger.debug(f"TCP_KEEPALIVE (macOS idle) set to {idle}s")
        elif hasattr(socket, "TCP_KEEPIDLE"):
            # Fallback for some macOS versions
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
            logger.debug(f"TCP_KEEPIDLE set to {idle}s")
    except (AttributeError, OSError) as e:
        logger.debug(f"Could not set keepalive idle time on macOS: {e}")
    
    try:
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval)
            logger.debug(f"TCP_KEEPINTVL set to {interval}s")
    except (AttributeError, OSError) as e:
        logger.debug(f"Could not set TCP_KEEPINTVL: {e}")
    
    try:
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, count)
            logger.debug(f"TCP_KEEPCNT set to {count}")
    except (AttributeError, OSError) as e:
        logger.debug(f"Could not set TCP_KEEPCNT: {e}")


def _apply_windows_keepalive(
    sock: socket.socket, idle: int, interval: int, count: int
) -> None:
    """Apply TCP keepalive settings on Windows."""
    # Try modern Windows 10 1709+ setsockopt approach first
    setsockopt_worked = False
    
    try:
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
            logger.debug(f"TCP_KEEPIDLE set to {idle}s (Windows setsockopt)")
            setsockopt_worked = True
    except (AttributeError, OSError) as e:
        logger.debug(f"TCP_KEEPIDLE via setsockopt failed: {e}")
    
    try:
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval)
            logger.debug(f"TCP_KEEPINTVL set to {interval}s (Windows setsockopt)")
            setsockopt_worked = True
    except (AttributeError, OSError) as e:
        logger.debug(f"TCP_KEEPINTVL via setsockopt failed: {e}")
    
    try:
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, count)
            logger.debug(f"TCP_KEEPCNT set to {count} (Windows setsockopt)")
    except (AttributeError, OSError) as e:
        logger.debug(f"TCP_KEEPCNT via setsockopt failed: {e}")
    
    # Fallback to SIO_KEEPALIVE_VALS ioctl for older Windows
    if not setsockopt_worked:
        try:
            if hasattr(socket, "SIO_KEEPALIVE_VALS"):
                # SIO_KEEPALIVE_VALS takes (onoff, keepalivetime_ms, keepaliveinterval_ms)
                sock.ioctl(
                    socket.SIO_KEEPALIVE_VALS,
                    (1, idle * 1000, interval * 1000)
                )
                logger.debug(
                    f"TCP keepalive set via SIO_KEEPALIVE_VALS: "
                    f"idle={idle}s, interval={interval}s"
                )
        except (AttributeError, OSError) as e:
            logger.warning(f"Failed to set keepalive via SIO_KEEPALIVE_VALS: {e}")


def get_keepalive_socket_options(
    idle: int = TCP_KEEPALIVE_IDLE,
    interval: int = TCP_KEEPALIVE_INTERVAL,
    count: int = TCP_KEEPALIVE_COUNT,
) -> List[SocketOption]:
    """
    Get a list of socket options for TCP keepalive configuration.
    
    These options can be passed to httpcore connection pools or other libraries
    that accept socket_options parameters.
    
    Args:
        idle: Seconds before first keepalive probe
        interval: Seconds between probes
        count: Number of failed probes before connection is dead
    
    Returns:
        List of (level, optname, value) tuples for setsockopt
    
    Example:
        socket_options = get_keepalive_socket_options()
        pool = httpcore.AsyncConnectionPool(socket_options=socket_options)
    """
    if not TCP_KEEPALIVE_ENABLED:
        return []
    
    options: List[SocketOption] = []
    
    # Enable SO_KEEPALIVE
    options.append((socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1))
    
    # Platform-specific idle time option
    if sys.platform == "darwin":
        # macOS uses TCP_KEEPALIVE for idle time
        if hasattr(socket, "TCP_KEEPALIVE"):
            options.append((socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, idle))
        elif hasattr(socket, "TCP_KEEPIDLE"):
            options.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle))
    else:
        # Linux and Windows 10 1709+
        if hasattr(socket, "TCP_KEEPIDLE"):
            options.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle))
    
    # Interval between probes
    if hasattr(socket, "TCP_KEEPINTVL"):
        options.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval))
    
    # Number of probes before giving up
    if hasattr(socket, "TCP_KEEPCNT"):
        options.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, count))
    
    return options


def create_keepalive_socket_factory(
    idle: int = TCP_KEEPALIVE_IDLE,
    interval: int = TCP_KEEPALIVE_INTERVAL,
    count: int = TCP_KEEPALIVE_COUNT,
) -> Callable[[Tuple[int, int, int, str, Tuple[str, int]]], socket.socket]:
    """
    Create a socket factory function for aiohttp TCPConnector with TCP keepalive.
    
    This factory creates sockets with TCP keepalive enabled and configured with
    the specified parameters. Use it with aiohttp.TCPConnector's socket_factory
    parameter.
    
    Args:
        idle: Seconds before first keepalive probe (default from TCP_KEEPALIVE_IDLE)
        interval: Seconds between probes (default from TCP_KEEPALIVE_INTERVAL)
        count: Number of failed probes before connection is dead (default from TCP_KEEPALIVE_COUNT)
    
    Returns:
        A callable that creates configured sockets for aiohttp
    
    Example:
        import aiohttp
        from litellm.llms.custom_httpx.tcp_keepalive import create_keepalive_socket_factory
        
        connector = aiohttp.TCPConnector(
            socket_factory=create_keepalive_socket_factory(idle=60, interval=30, count=5)
        )
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get('https://api.example.com') as resp:
                data = await resp.text()
    """
    def socket_factory(addr_info: Tuple[int, int, int, str, Tuple[str, int]]) -> socket.socket:
        """
        Socket factory for aiohttp TCPConnector.
        
        Args:
            addr_info: Tuple of (family, type, proto, canonname, sockaddr)
        
        Returns:
            Configured socket with TCP keepalive enabled
        """
        family, sock_type, proto, canonname, sockaddr = addr_info
        
        # Create the socket
        sock = socket.socket(family=family, type=sock_type, proto=proto)
        
        # Apply TCP keepalive settings
        _apply_keepalive_to_socket(sock, idle=idle, interval=interval, count=count)
        
        return sock
    
    return socket_factory

