"""
Session artwork counter — batches sync reports to the backend.

Accumulates artwork syncs in memory during the session.
Flushes to /stats/artwork-synced every 10 minutes OR on app close.
Never blocks the UI — all network calls are in background threads.
"""
import threading
import time


class _ArtworkCounter:
    def __init__(self):
        self._count  = 0
        self._lock   = threading.Lock()
        self._timer  = None
        self._running = False

    def start(self):
        """Start the 10-minute flush cycle."""
        if self._running:
            return
        self._running = True
        self._schedule_flush()

    def stop(self):
        """Stop the cycle and do a final flush."""
        self._running = False
        if self._timer:
            self._timer.cancel()
        self.flush(final=True)

    def increment(self, n: int = 1):
        """Called each time artwork is synced to Steam."""
        with self._lock:
            self._count += n

    def flush(self, final: bool = False):
        """Send accumulated count to backend then reset."""
        with self._lock:
            count = self._count
            self._count = 0

        if count <= 0:
            return

        threading.Thread(
            target=self._send,
            args=(count, final),
            daemon=True,
        ).start()

    def _schedule_flush(self):
        if not self._running:
            return
        self._timer = threading.Timer(600, self._tick)  # 10 minutes
        self._timer.daemon = True
        self._timer.start()

    def _tick(self):
        self.flush()
        self._schedule_flush()  # reschedule

    def _send(self, count: int, final: bool):
        try:
            from app.services.steamkustom_auth import get_token
            import urllib.request, json as _j, ssl, certifi

            API_URL = "https://api.pimpmysteam.com"
            token = get_token()
            if not token:
                return

            ctx = ssl.create_default_context(cafile=certifi.where())
            req = urllib.request.Request(
                f"{API_URL}/stats/artwork-synced",
                data=_j.dumps({"count": count}).encode(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (compatible; SteamGrunge/1.0)",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=8, context=ctx)
            label = "final flush" if final else "periodic flush"
            print(f"[Stats] {label}: reported {count} artwork sync(s) to backend")
        except Exception as e:
            print(f"[Stats] Flush failed ({count} syncs lost): {e}")


# Global singleton
_session_artwork_counter = _ArtworkCounter()