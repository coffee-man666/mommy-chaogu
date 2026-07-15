# Database lifecycle

Every database handle has one explicit owner. SQLAlchemy-backed stores inherit
`EngineOwner`; `EarningsStore` owns its raw `sqlite3.Connection`. Owners expose
idempotent `close()` methods and context-manager support.

## Ownership rules

- A store constructed by application code must be used in a `with` block or
  closed in `finally`.
- `CachedMarketDataAdapter` owns and closes its `CacheStore`.
- FastAPI dependency singletons are application-owned and are closed from the
  lifespan shutdown hook, after the background service stops.
- A SQLAlchemy `Session` or raw connection borrowed from an owner remains
  scoped to its local context manager and must never escape it.
- Tests that construct stores should close them explicitly. The weak finalizer
  in `EngineOwner` is a safety net, not the primary lifecycle mechanism.

All SQLAlchemy SQLite connections enable foreign keys, use a 5-second busy
timeout, and select WAL mode for file databases. The raw earnings connection
uses the same settings. WAL improves reader/writer concurrency; callers must
still keep transactions short.
