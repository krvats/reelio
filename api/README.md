# Reelio API (Phase B, part 1)
Multi-user backend: sign up / log in, one private space per user (config, queue, ledger, encrypted secrets), and worker-only routes that hand each flow to exactly one worker at a time.
- Passwords: PBKDF2-SHA256 150k. Sessions: random 256-bit tokens stored hashed, 30 days, logout kills them.
- Secrets: AES-256-GCM with a per-user data key wrapped by `MASTER_KEY` (a Worker secret). The browser can write secrets and list their names, never read values; only `WORKER_SECRET` holders can.
- Config saves use a version number (optimistic concurrency) and enforce plan account limits server-side.
- Worker routes: `/v1/internal/lease` (flow lease with expiry, so a crashed worker's flow is picked up again), `/secrets`, `/ledger` (409 on duplicate source id or content = exactly-once), `/queue`, `/release`.
- Test: `npm test` (10 tests incl. isolation, encryption at rest, leases, exactly-once). 
## Not done yet
The Python worker still reads/writes git; porting it to lease + these routes, the web app's login screen against this API, email magic links/passkeys, linking plans from the license service, D1 storage, and R2 video hosting are the next steps (see docs/ROADMAP.md).
