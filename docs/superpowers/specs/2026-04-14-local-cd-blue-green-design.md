# Local CD — Blue/Green Deployment via Traefik

**Date:** 2026-04-14  
**Status:** Approved  
**Scope:** echelon extension (`/Users/michalbachorik/work/evolution/echelon`)

---

## Overview

Adds local continuous deployment to the echelon extension. After `harness.run` merges a feature branch to main, a git `post-merge` hook fires `deploy.sh`, which performs a zero-downtime blue/green swap using Docker + Traefik. Designed to run identically locally and in a datacenter/cloud — the swap logic never changes, only the trigger mechanism.

This is **not** a separate extension. CD is phase 3 of the echelon pipeline:

```
echelon.run → harness.run (build → merge to main)
                    │
             post-merge hook fires
                    │
             .specify/scripts/deploy.sh (blue/green swap)
                    │
             Traefik routes active_port → new slot
```

---

## Configuration

Added to `echelon.yml` and `config-template.yml`:

```yaml
deploy:
  blue_port: 3000        # Blue slot host port
  green_port: 3001       # Green slot host port
  active_port: 80        # Traefik-exposed port (user-facing URL)
  dockerfile: Dockerfile # Optional — defaults to Dockerfile in project root
```

**App name** is derived automatically: `basename(PROJECT_ROOT)`, lowercased, hyphens preserved. Never declared in config — it would be redundant.

If the `deploy:` block is absent when `echelon.run` starts, fail immediately with:

```
✗ deploy config missing in echelon.yml.
  Add a deploy: block with blue_port, green_port, active_port.
  See config-template.yml for reference.
```

**Port conflict detection:** on init, if the requested ports are already claimed by another app in `deploy-state.json`, fail with the conflicting app name and its ports.

---

## Shared Infrastructure

One `speckit-traefik` container and one `speckit-deploy` Docker network per machine, shared by all echelon-based apps.

```
Machine state (two apps):

  speckit-traefik       (shared proxy, always running)
  weather-blue          (:3000, routed from :80)
  animacure-blue        (:3002, routed from :81)

  Docker network: speckit-deploy
```

Traefik discovers containers via Docker label polling — no config file to manage. Adding a second app means starting a container with the right labels; Traefik picks it up automatically within ~100ms.

---

## Lazy Init (on first `echelon.run`)

Init runs once, transparently, as part of `echelon.run` section 1.0 (after `PROJECT_ROOT` is anchored). Subsequent runs skip it entirely.

**Init sequence (`deploy-init.sh`):**

1. Validate `deploy:` block exists in `echelon.yml` — fail fast if missing
2. Check `deploy-state.json` exists → if yes, skip all init
3. Derive app name from `basename(PROJECT_ROOT)`
4. Check requested ports not already claimed → fail with conflict message if taken
5. Create Docker network: `docker network create speckit-deploy 2>/dev/null || true`
6. Start Traefik if not running:
   ```bash
   docker run -d \
     --name speckit-traefik \
     --network speckit-deploy \
     -p {active_port}:80 \
     -v /var/run/docker.sock:/var/run/docker.sock:ro \
     --restart unless-stopped \
     traefik:v3 \
       --providers.docker=true \
       --providers.docker.network=speckit-deploy \
       --entrypoints.{app}.address=:{active_port}
   ```
   If Traefik is already running, add the new entrypoint via `docker exec speckit-traefik` is not possible at runtime — instead, stop and recreate Traefik with the merged set of `--entrypoints.*` flags derived from all registered apps in `deploy-state.json`. This recreate takes ~1s and temporarily drops all apps, acceptable for local use.
7. If Traefik container exists but is not healthy → fail with clear message (do not silently proceed)
8. Install git hook: write `.git/hooks/post-merge` → calls `.specify/scripts/deploy.sh`
9. Write `.specify/squad/deploy-state.json`:
   ```json
   {
     "app": "{name}",
     "active": "blue",
     "blue_port": 3000,
     "green_port": 3001,
     "active_port": 80,
     "last_deploy": null,
     "blue_image": null,
     "green_image": null
   }
   ```

---

## Blue/Green Swap (`deploy.sh`)

Called by the `post-merge` git hook. Reads state, swaps slots, updates Traefik routing.

```
1.  Read deploy-state.json → active slot (e.g. "blue"), inactive = other
2.  Derive app name from basename(pwd)
3.  Check speckit-traefik is running and healthy → fail if not
4.  docker build -t {app}:candidate -f {dockerfile} .
5.  docker run -d \
      --name {app}-{inactive} \
      --network speckit-deploy \
      --label traefik.enable=true \
      --label "traefik.http.routers.{app}.rule=PathPrefix(\`/\`)" \
      --label "traefik.http.routers.{app}.entrypoints={app}" \
      --label "traefik.http.services.{app}.loadbalancer.server.port=80" \
      --network speckit-deploy \
      -p {inactive_port}:80 \
      {app}:candidate
6.  Health check: curl -sf http://localhost:{inactive_port}
    → retry 5×, 2s apart
    → on failure: docker stop {app}-{inactive}, docker rm {app}-{inactive}, exit 1
    → active slot is unchanged — automatic rollback, nothing to undo
7.  docker stop {app}-{active}   (old slot goes down AFTER new slot is healthy)
8.  docker tag {app}:candidate {app}:{inactive}
9.  Write deploy-state.json: swap active ↔ inactive, update last_deploy + {slot}_image
```

**Zero-downtime guarantee:** Traefik routes to the new slot as soon as the container starts and labels are present (~100ms). The old slot is stopped only after the health check passes. On any failure before step 7, the old slot is never touched.

---

## Manual Command (`echelon.deploy.md`)

A lightweight command for visibility and manual control. Not part of the automated flow.

| Invocation | Action |
|---|---|
| `/speckit-echelon-deploy` | Trigger deploy manually (same as pushing to main) |
| `/speckit-echelon-deploy status` | Show active slot, ports, container health, last deploy time |
| `/speckit-echelon-deploy rollback` | Swap back to previous slot (`docker start {app}-{inactive}` + Traefik label update + state swap) |

Rollback works because the inactive container is stopped, not removed — its image is still tagged `{app}:blue` or `{app}:green`.

---

## Files Added to echelon Extension

```
echelon/
  commands/
    echelon.deploy.md             # Manual trigger, status, rollback
  scripts/bash/
    deploy.sh                     # Blue/green swap (called by git hook)
    deploy-init.sh                # One-time setup (Traefik, hook, state)
    deploy-status.sh              # Print active slot + container health
  config-template.yml             # Add deploy: section with annotations
  echelon-config.yml              # Add deploy: section for test project
```

`.specify/scripts/` is where spec-kit installs scripts at `specify extension add` time — `deploy.sh` and `deploy-init.sh` land there in the target project.

---

## Changes to `echelon.run.md`

Section 1.0 (Anchor Project Root) gains two steps after anchoring `PROJECT_ROOT`:

1. Validate `deploy:` block present → fail fast if not
2. Call `deploy-init.sh` (idempotent — skips if `deploy-state.json` exists)

No other changes to `echelon.run.md`.

---

## State File Location

`.specify/squad/deploy-state.json` — alongside `state.json`. Consistent with echelon's existing convention of owning `.specify/squad/` for runtime state.

---

## Cloud / DC Migration Path

When moving to CI/CD:

1. Remove the `post-merge` git hook (or leave it — it's harmless)
2. Point your CI runner (GitHub Actions, GitLab CI, ArgoCD) at `deploy.sh` as its deploy entrypoint
3. Replace the `docker run speckit-traefik` section in `deploy-init.sh` with your cloud provider's load balancer provisioning

The swap logic in `deploy.sh` is unchanged. The only thing that varies across environments is what calls it.

---

## Constraints and Non-Goals

- Single machine only — no remote Docker host, no Swarm, no Kubernetes (yet)
- One active slot per app at all times — no canary/weighted routing
- No HTTPS locally — plain HTTP on `active_port`. TLS is a cloud concern.
- No automatic Traefik restart on machine reboot — user runs `docker start speckit-traefik` or adds it to Docker restart policy (`--restart unless-stopped`)
