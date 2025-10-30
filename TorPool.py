import asyncio
import logging
import time
from typing import Tuple, Dict, Optional
from stem.control import Controller



class TorPool:
    """Manage a small pool of Tor instances (socks + control ports).

    - Default layout assumes pairs: socks ports 9050,9052,9054,9056 and control ports 9051,9053,9055,9057
    - Uses async methods so callers can await rotation/renewal.
    """

    def __init__(self, count: int = 4, socks_start: int = 9050, control_start: int = 9051):
        self.count = count
        self.socks_ports = [socks_start + i * 2 for i in range(count)]
        self.control_ports = [control_start + i * 2 for i in range(count)]
        self._index = 0
        self._lock = asyncio.Lock()
        # logger
        self._logger = logging.getLogger(__name__)
        # include control_ports in the logged arguments (previously omitted which caused a formatting error)
        self._logger.info("TorPool initialized: count=%d socks=%s control=%s", self.count, self.socks_ports, self.control_ports)

    async def get_next_index(self) -> int:
        async with self._lock:
            idx = self._index
            self._index = (self._index + 1) % self.count
            return idx

    async def get_next_proxies(self) -> Tuple[Dict[str, str], int]:
        """Return proxies dict suitable for requests and the index used."""
        idx = await self.get_next_index()
        port = self.socks_ports[idx]
        proxies = {
            "http": f"socks5h://127.0.0.1:{port}",
            "https": f"socks5h://127.0.0.1:{port}",
        }
        # log the proxy selection
        try:
            # Log at INFO so it's visible in normal runs
            self._logger.info("Selected tor index=%d socks_port=%d", idx, port)
        except Exception:
            pass
        return proxies, idx

    def _renew_sync(self, idx: int) -> bool:
        """Synchronous renew using stem Controller. Returns True if NEWNYM sent."""
        if Controller is None:
            return False
        control_port = self.control_ports[idx]
        try:
            self._logger.info("Attempting NEWNYM on control port %d (index=%d)", control_port, idx)
            with Controller.from_port(port=control_port) as c:
                try:
                    c.authenticate()
                except Exception:
                    # Try without password (some setups don't require auth)
                    c.authenticate()
                c.signal("NEWNYM")
            self._logger.info("NEWNYM signalled successfully for index=%d", idx)
            return True
        except Exception:
            try:
                self._logger.exception("Failed to send NEWNYM to control port %d (index=%d)", control_port, idx)
            except Exception:
                pass
            return False

    async def renew(self, idx: Optional[int] = None, timeout: float = 5.0) -> bool:
        """Attempt to renew the circuit for the given index. If idx is None, renew current index.

        Uses a thread to avoid blocking the event loop for potentially slow control connections.
        """
        if idx is None:
            # pick the previous index (the one that was last used)
            async with self._lock:
                idx = (self._index - 1) % self.count

        try:
            self._logger.debug("Scheduling renew for index=%s", str(idx))
            result = await asyncio.wait_for(asyncio.to_thread(self._renew_sync, idx), timeout=timeout)
            self._logger.debug("Renew result for index=%s -> %s", str(idx), result)
            return bool(result)
        except Exception:
            try:
                self._logger.exception("Renew failed or timed out for index=%s", str(idx))
            except Exception:
                pass
            return False

    def get_socks_port(self, idx: int) -> int:
        return self.socks_ports[idx]


# provide a module-level singleton for convenience
_singleton: Optional[TorPool] = None


def get_tor_pool() -> TorPool:
    global _singleton
    if _singleton is None:
        _singleton = TorPool()
    return _singleton
