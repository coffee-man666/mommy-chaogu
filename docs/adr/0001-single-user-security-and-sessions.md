# ADR 0001: Single-user authentication and browser sessions

- Status: Accepted
- Date: 2026-07-14

## Context

The application is a personal investment assistant, not a multi-tenant service. It exposes
portfolio data, persistent conversations, state-changing endpoints, and configured LLM spend.
The prior remote binding had no identity boundary and all browsers shared one conversation.

## Decision

Use one owner-supplied bearer token for REST requests. Exchange it for short-lived, HMAC-signed
WebSocket tickets so the long-lived secret is never placed in a socket URL. Bind to loopback by
default and require an explicit override for unauthenticated non-loopback operation.

Generate one opaque conversation session identifier per browser tab and scope conversation reads,
writes, clearing, and summaries to it. Retain the legacy `default` session for CLI compatibility
and prune inactive browser sessions after the configured retention period.

## Consequences

- This provides an owner boundary without accounts, password storage, roles, or tenant tables.
- TLS remains the reverse proxy or hosting platform's responsibility.
- Anyone holding the owner token has full authority; token rotation is operational.
- Browser tabs intentionally do not share conversational context.
- Multi-user hosting remains out of scope and requires a new identity/data-isolation ADR.
