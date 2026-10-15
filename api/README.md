# Reelio API (hosted multi-user backend)
Multi-user backend: sign up / log in, one private space per user (config, queue, ledger, encrypted secrets), and worker-only routes that hand each flow to exactly one worker at a time.
- Passwords: PBKDF2-SHA256 150k. Sessions: random 256-bit tokens stored hashed, 30 days, logout kills them.
- Secrets: AES-256-GCM with a per-user data key wrapped by `MASTER_KEY` (a Worker secret). The browser can write secrets and list their names, never read values; only `WORKER_SECRET` holders can.
- Config saves use a version number (optimistic concurrency) and enforce plan account limits server-side.
- Worker routes: `/v1/internal/lease` (flow lease with expiry, so a crashed worker's flow is picked up again), `/secrets`, `/ledger` (409 on duplicate source id or content = exactly-once), `/queue`, `/release`.
- Test: `npm test` (10 tests incl. isolation, encryption at rest, leases, exactly-once). 
## Also included
Teams (owner/editor/viewer invites), audit log, admin console routes (list/suspend/plan/stats), plan sync from a signed license entitlement, worker pull/push, and a worker `serve` mode (`python -m reelio serve`, workflow `tick-hosted.yml`).
## Not done yet
Email magic links/passkeys, D1 storage (KV today), R2 video hosting (Cloudinary today), a VPS runner for heavy use. See docs/ROADMAP.md.
