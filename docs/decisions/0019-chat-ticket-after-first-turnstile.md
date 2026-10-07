---
type: decision
status: current
updated: 2026-10-06
summary: After one passed Turnstile check the gateway signs a 30 minute HMAC ticket bound to the session and the normalized address; later messages carry the ticket and skip siteverify, the quota still runs on every message; amends the per-message Turnstile wording of hosting-and-security section 6 and product-page section 2.4
---

# 0019: chat ticket after the first Turnstile check

Status: accepted (2026-10-06). Amends the wording of `docs/design/hosting-and-security.md` section 6 and `docs/design/product-page.md` section 2.4, which asked for one fresh Turnstile token per message. ADR 0016 and 0017 contain no per-message token clause and are not changed.

## Context

A fresh token per message makes every send wait for a challenge round trip and one siteverify call. The quota already bounds a session, an address and the whole site, so the check only has to show that a human started the chat.

## Decision

- **Key.** No new secret. The ticket key is HMAC-SHA256(key = `GISTING_IP_SALT`, message = `gisting-chat-ticket-v1`), imported as an HMAC-SHA256 key. It is not the digest key.
- **Format.** `1.<exp>.<mac>`: `exp` is the expiry in Unix seconds, `mac` is the unpadded base64url of HMAC-SHA256(ticket key, `1|<session_id>|<exp>|<normalized ip>`). The normalized address is the one from `ip-normalize.ts` (IPv6 to its /64, mapped IPv4 to IPv4); it is not the daily digest, so a ticket survives UTC midnight. The address is not in the ticket text.
- **Lifetime.** `ticketTtlSeconds` in `apps/gateway/limits.json` is 1800. The expiry is absolute: a ticket is never renewed. After 30 minutes the page passes one more Turnstile check.
- **Checks.** A strict shape (version `1`, no leading zeros, a 43 character canonical mac), `exp > now`, `exp <= now + ttl + skew` (`ticketClockSkewSeconds` is 5 in `limits.json`; it only loosens the upper bound, never the expiry), then `crypto.subtle.verify`. All failures are the existing `TurnstileFailed` (403, caller sees `{"error":"request_failed"}`); the log reason is `ticket_malformed`, `ticket_expired` or `ticket_invalid`. The ticket value is never logged. Both time comparisons are written negated (`!(exp > now)`), so an invalid clock or a NaN ttl refuses.
- **Request.** `/api/chat` takes an optional `ticket` and an optional `turnstile_token`; at least one is required, else 400. A ticket that fails with a token present falls back to siteverify; without a token it is a 403, and no siteverify call or quota is spent.
- **Issuing.** Only a request that passed siteverify itself gets `x-gisting-ticket`, and only on an HTTP 200 (the answer or a replay answer). A request admitted by ticket gets no new one. Error responses never carry one. The page and gateway share an origin, so no CORS header is added.
- **No re-check.** A ticket does not repeat the hostname and action checks of 0017; they ran when the ticket was issued.
- **Quota.** `enforceQuota` runs on every message, ticketed or not.
- **Storage.** The page keeps the ticket in JavaScript memory only (the front end owns this).

## Known limits

- A stolen ticket works for at most 30 minutes, only with the same session id and the same address (or /64). Rotating the address within a /64 does not help an attacker; moving to another address does.
- The quota is the backstop against a ticket holder who sends as fast as allowed.
- `GISTING_IP_SALT` must be a random value of at least 128 bits (for example `openssl rand -hex 32`); the gateway fails closed (`ConfigMissing`) with fewer than `minSecretChars` (32) characters.
- Preview and production must use different salts; with the same salt a ticket from one environment is accepted by the other.
- One Turnstile check now buys one session's quota (10 messages), so the number of human checks needed to use up the site's daily quota drops to about a tenth of the per-message model; read the cost model of ADR 0006 with that in mind.
- Changing `GISTING_IP_SALT` also invalidates every ticket and every digest.
- The verifier accepts a ticket whose expiry is up to 5 seconds beyond the ttl, to tolerate clock difference between isolates.
