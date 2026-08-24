import time

from phamp_mb7 import PhAmpError, PhAmpMB7


_RETRYABLE_TEXT = (
    "semaphore timeout",
    "could not open",
)


def install_phamp_connect_retry(attempts=3, delay_s=0.7):
    """Retry transient Windows/Bluetooth SPP COM-open failures."""

    if getattr(PhAmpMB7, "_lumigon_retry_installed", False):
        return

    original_connect = PhAmpMB7.connect

    def connect_with_retry(self):
        last_error = None
        total_attempts = max(1, int(attempts))

        for attempt in range(1, total_attempts + 1):
            try:
                return original_connect(self)
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                retryable = isinstance(exc, PhAmpError) and any(
                    token in message for token in _RETRYABLE_TEXT
                )

                if not retryable or attempt >= total_attempts:
                    raise

                try:
                    self.disconnect()
                except Exception:
                    pass

                time.sleep(max(0.1, float(delay_s)))

        raise last_error

    PhAmpMB7.connect = connect_with_retry
    PhAmpMB7._lumigon_retry_installed = True
