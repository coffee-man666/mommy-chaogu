"""Retry helpers for data-fetch operations in basket-analysis skill.

Why this module:
- efinance (money flow) rate-limits aggressively in sandboxes (~74% success typical)
- Tencent K-line API SSL handshake fails intermittently (1-2% of requests)
- Chrome --print-to-pdf can fail on transient dbus/sandbox issues
- Web search hits rate limits (429) periodically

A single shared retry helper with exponential backoff + jitter gives all
data-fetch paths the same behavior. Logs to stdout so the agent sees
exactly which fetches retried.

Usage:
    from retry import retry_with_backoff, RetryableError

    def fetch_url(url):
        # must raise on transient failure, return data on success
        ...

    result = retry_with_backoff(fetch_url, args=(url,),
                                max_attempts=3, initial_delay=2, backoff_factor=2,
                                retriable_exceptions=(urllib.error.URLError, TimeoutError))
"""
from __future__ import annotations

import random
import subprocess
import time
import urllib.error
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")


# Errors that we should retry (transient). SSL handshake failures, timeouts,
# connection resets, rate-limit HTTP codes are typical. Don't retry on
# programming errors (TypeError, ValueError, KeyError).
DEFAULT_RETRIABLE = (
    urllib.error.URLError,        # SSL EOF, name resolution, refused
    urllib.error.HTTPError,      # 429 / 5xx (caller can choose to filter status)
    TimeoutError,                  # socket timeout
    ConnectionError,
    ConnectionResetError,
    ConnectionRefusedError,
    OSError,                       # covers some network-layer errors
    subprocess.TimeoutExpired,
)


def is_retriable_http_error(exc: urllib.error.HTTPError, retriable_status: tuple = (408, 425, 429, 500, 502, 503, 504)) -> bool:
    """Decide whether an HTTPError is retriable. 4xx (except 408/425/429) are usually
    not retriable (client error, not transient). 5xx are always retriable.
    """
    return getattr(exc, "code", None) in retriable_status


def retry_with_backoff(
    fn: Callable[..., T],
    args: tuple = (),
    kwargs: dict | None = None,
    max_attempts: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
    jitter: float = 0.3,
    retriable_exceptions: Iterable[type] = DEFAULT_RETRIABLE,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
    quiet: bool = False,
) -> T:
    """Call `fn(*args, **kwargs)` up to `max_attempts` times with exponential backoff.

    Args:
        fn: the function to call. Must raise on failure.
        args: positional args to pass.
        kwargs: keyword args to pass.
        max_attempts: total attempts (1 = no retry).
        initial_delay: seconds before the first retry.
        backoff_factor: each retry delay multiplies by this.
        max_delay: cap on per-retry sleep.
        jitter: ± fraction of random jitter (0.3 = ±30%), to avoid synchronized retries.
        retriable_exceptions: tuple of exception types to retry on. Anything else
            is raised immediately (caller can extend or replace).
        on_retry: optional callback(attempt_no, exception, next_delay) called before
            each sleep. Useful for logging.
        quiet: if True, don't print to stdout.

    Returns:
        Whatever `fn` returns on first success.

    Raises:
        The last exception if all attempts fail.
    """
    kwargs = kwargs or {}
    last_exc = None
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except retriable_exceptions as e:
            last_exc = e
            if attempt >= max_attempts:
                break
            # Jitter: ±jitter fraction
            sleep_for = delay * (1.0 + random.uniform(-jitter, jitter))
            sleep_for = max(0, min(sleep_for, max_delay))
            if not quiet:
                print(f"  ⟳ retry {attempt}/{max_attempts-1} after {sleep_for:.1f}s: {e}")
            if on_retry:
                on_retry(attempt, e, sleep_for)
            time.sleep(sleep_for)
            delay *= backoff_factor
    # Exhausted all attempts
    raise last_exc  # type: ignore[misc]


def _find_mommy() -> str:
    """Find the `mommy` binary. Checks common install locations and PATH."""
    import shutil
    from pathlib import Path

    # 1. PATH first
    found = shutil.which("mommy")
    if found:
        return found

    # 2. Common install locations (sandbox-specific)
    candidates = [
        "/workspace/.home/.local/bin/mommy",
        "/usr/local/bin/mommy",
        "/usr/bin/mommy",
        Path.home() / ".local/bin/mommy",
    ]
    for c in candidates:
        if Path(c).exists():
            return str(c)
    return "mommy"  # fallback, will likely fail


def retry_money_flow(
    codes: list[str],
    db_path: str = "/workspace/.home/.local/share/mommy-chaogu/portfolio.db",
    max_attempts: int = 2,
    initial_delay: float = 5.0,
) -> dict[str, bool]:
    """Best-effort money-flow pull for a list of codes via `mommy flows --pool custom`.

    Why this exists:
    - efinance (the upstream for `mommy flows`) rate-limits aggressively in sandboxes
    - First pull usually gets ~74% coverage. A retry with backoff typically gets
      80-85%, sometimes 100%.
    - Rather than failing the whole run, we report per-code success and continue.

    Args:
        codes: list of 6-digit A-share codes
        db_path: path to portfolio.db (mommy default)
        max_attempts: total attempts (1 = no retry). 2 is usually enough.
        initial_delay: seconds before first retry.

    Returns:
        dict[code -> bool] indicating success on the FINAL attempt.
        Codes that are in today_money_flow_cache at the end count as success
        even if they succeeded on an earlier attempt (idempotent).
    """
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    mommy_bin = _find_mommy()
    overall_success: dict[str, bool] = {}

    for attempt in range(1, max_attempts + 1):
        missing = [c for c in codes if not cur.execute(
            "SELECT 1 FROM today_money_flow_cache WHERE code=?", (c,)
        ).fetchone()]
        if not missing:
            print(f"  ✅ money flow: all {len(codes)} codes already cached (skipping attempt {attempt})")
            overall_success = {c: True for c in codes}
            break

        print(f"  📥 money flow attempt {attempt}/{max_attempts}: pulling {len(missing)}/{len(codes)} missing codes (via {mommy_bin})")
        missing_str = " ".join(missing)
        try:
            r = subprocess.run(
                [mommy_bin, "flows", "--db", db_path, "--pool", "custom",
                 "--codes", *missing_str.split(),
                 "pull", "--target", "today", "--force"],
                capture_output=True, text=True, timeout=120,
            )
            still_missing = [c for c in missing if not cur.execute(
                "SELECT 1 FROM today_money_flow_cache WHERE code=?", (c,)
            ).fetchone()]
            newly_ok = [c for c in missing if c not in still_missing]
            print(f"  → pulled {len(newly_ok)} codes, still missing {len(still_missing)}")
            for c in newly_ok:
                overall_success[c] = True
            if not still_missing:
                break
        except subprocess.TimeoutExpired:
            print(f"  ⚠️ money flow attempt {attempt} timed out")
        except FileNotFoundError as e:
            print(f"  ⚠️ money flow attempt {attempt} failed: mommy binary not found at {mommy_bin}: {e}")
        except Exception as e:
            print(f"  ⚠️ money flow attempt {attempt} failed: {type(e).__name__}: {e}")

        if attempt < max_attempts:
            sleep_for = initial_delay * (2 ** (attempt - 1))
            print(f"  ⏸ waiting {sleep_for}s before retry...")
            time.sleep(sleep_for)

    # Final pass
    for c in codes:
        overall_success[c] = bool(cur.execute(
            "SELECT 1 FROM today_money_flow_cache WHERE code=?", (c,)
        ).fetchone())
    conn.close()

    n_ok = sum(1 for v in overall_success.values() if v)
    n_total = len(codes) or 1
    print(f"  📊 money flow final coverage: {n_ok}/{n_total} ({n_ok*100//n_total}%)")
    return overall_success


def retry_kline(code: str, days: int = 60, max_attempts: int = 3) -> list[float] | None:
    """Tencent K-line fetch with retry. Returns closes or None on permanent failure.

    Returns:
        list of closing prices (oldest first) or None if all attempts fail.
    """
    import json
    import urllib.request

    market = "sh" if code.startswith(("6", "9")) else "sz"
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,{days},qfq"

    def _fetch_once():
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("gbk"))
        if data.get("code") != 0:
            raise urllib.error.URLError(f"code={data.get('code')}")
        stock = data["data"][f"{market}{code}"]
        klines = stock.get("qfqday") or stock.get("day") or []
        closes = [float(k[2]) for k in klines if len(k) >= 3]
        if not closes:
            raise urllib.error.URLError("no klines returned")
        return closes

    try:
        return retry_with_backoff(_fetch_once, max_attempts=max_attempts,
                                  initial_delay=2.0, backoff_factor=2.0)
    except Exception as e:
        print(f"  ⚠️ K-line {code} failed after {max_attempts} attempts: {e}")
        return None


def retry_web_search(search_fn, query: str, max_attempts: int = 3, **kwargs):
    """Best-effort web search wrapper. Retries on common transient failures.

    Args:
        search_fn: the web_search function (from Mavis tools).
        query: query string.
        max_attempts: total attempts.
        **kwargs: extra args to pass to search_fn (e.g. count, freshness).
    """
    return retry_with_backoff(search_fn, args=(query,), kwargs=kwargs,
                              max_attempts=max_attempts, initial_delay=3.0,
                              backoff_factor=2.0)
