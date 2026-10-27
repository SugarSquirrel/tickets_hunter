"""Fail-open operation timings; no browser access and no application state changes."""

import os
import math
import time


def log_navigation_timing(config_dict, snapshot):
    """Emit allowlisted browser-clock measurements, without affecting flow.

    Request-to-response includes transport, intermediary and server time. Zero
    redirect timestamps mean unavailable (possibly no redirect or redaction).
    Browser timestamps must never be subtracted from Python perf_counter().
    """
    try:
        if config_dict is None or not config_dict.get('advanced', {}).get('show_timing_log', True):
            return
        raw = snapshot.get('navigation_timing')
        fields = ('startTime', 'requestStart', 'responseStart', 'responseEnd',
                  'domContentLoadedEventEnd', 'redirectStart', 'redirectEnd', 'redirectCount')
        values = {}
        if isinstance(raw, dict):
            for key in fields:
                value = raw.get(key)
                if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                    values[key] = value
        available = 'startTime' in values
        parts = [f'[NAV_TIMING] nav_entry_available={int(available)}']
        if available:
            for label, start, end in (
                    ('nav_to_request_ms', 'startTime', 'requestStart'),
                    ('request_to_response_ms', 'requestStart', 'responseStart'),
                    ('response_download_ms', 'responseStart', 'responseEnd'),
                    ('response_end_to_dcl_ms', 'responseEnd', 'domContentLoadedEventEnd'),
                    ('nav_to_dcl_ms', 'startTime', 'domContentLoadedEventEnd')):
                left, right = values.get(start), values.get(end)
                if (left is not None and right is not None and right > 0
                        and (start == 'startTime' or left > 0) and right >= left):
                    parts.append(f'{label}={right - left:.1f}')
            left, right = values.get('redirectStart'), values.get('redirectEnd')
            redirect_available = left is not None and right is not None and left > 0 and right >= left
            parts.append(f'redirect_timing_available={int(redirect_available)}')
            if redirect_available:
                parts.append(f'redirect_ms={right - left:.1f}')
            count = values.get('redirectCount')
            if type(count) is int or (type(count) is float and count.is_integer()):
                parts.append(f'redirect_count={int(count)}')
        print(' '.join(parts))
    except Exception:
        pass


class flow_stage:
    """Measure a Python operation, not DOM readiness or server acceptance.

    Only fixed stage/outcome tokens and numeric counts are emitted. Exceptions
    retain their original propagation; callers may still catch them as before.
    """

    def __init__(self, config_dict, stage, *, priority=None):
        self.stage = stage
        self.priority = priority
        self.outcome = "completed"
        self.count = None
        self.started = None
        try:
            if config_dict is not None and config_dict.get("advanced", {}).get("show_timing_log", True):
                self.started = time.perf_counter()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.started is not None:
                ended = time.perf_counter()
                elapsed = (ended - self.started) * 1000
                # Reject arbitrary text rather than risk emitting URLs, answers,
                # credentials or exception messages through future call sites.
                if not self._token(self.stage) or not self._token(self.outcome):
                    return False
                outcome = "error" if exc_type is not None else self.outcome
                line = (f"[STAGE] stage={self.stage} pid={os.getpid()}"
                        f" start_ms={self.started * 1000:.1f} end_ms={ended * 1000:.1f}"
                        f" duration_ms={elapsed:.1f} outcome={outcome}")
                if type(self.priority) is int:
                    line += f" priority={self.priority}"
                if type(self.count) is int:
                    line += f" count={self.count}"
                print(line)
        except Exception:
            pass
        return False

    @staticmethod
    def _token(value):
        return (isinstance(value, str) and 0 < len(value) <= 64
                and all(c in "abcdefghijklmnopqrstuvwxyz_" for c in value))
