# GPU-free proof image preparation

This directory is the entire candidate technical repository. Do not upload its
parent directory: references, story, prompts and local credentials stay private.

One recommended path: public GitHub standard ubuntu-24.04 AMD64 runner plus Docker
Hub Personal public repository, reusing the pinned official worker layers with
registry blob mounts. Three model layers are streamed and SHA256-verified before
publishing the final manifest. No Docker engine, base download, model disk copy,
Runpod API key, endpoint deployment or GPU is involved in this job.

Run `python3 stream_image.py` for an offline plan. Publishing is opt-in. A failed
base-layer mount aborts; there is no expensive disk/transfer fallback. Failed
uploads are canceled. Completed unreferenced model blobs may remain subject to
registry garbage collection; no manifest is published after an integrity failure.

## Account actions

1. Create a public GitHub repository named `wan-proof-worker` and grant the Codex
   GitHub connection access. This uploads ONLY this directory. Public standard
   runners are free/unlimited; private/larger runners are deliberately excluded.
2. Sign into/create Docker Hub Personal; create a public `wan-proof-worker` repo.
   Put your username and a Read/Write access token into GitHub Actions repository
   secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. Do not paste the token in chat.
   Add repository variable `IMAGE_REPOSITORY=<docker-username>/wan-proof-worker`.
   No paid subscription, payment method or Runpod credits are needed now.

Run the workflow once with `publish=false` first, then publish after validation.
Configured limit: 180 minutes, no automatic rerun. Provider hosted-job maximum:
6 hours. Estimated assembly/upload time 30–120 minutes, throughput dependent.
Runner documents 4 CPU,16GB RAM,14GB disk; this algorithm only needs 512MiB disk
and roughly tens of MiB of streaming buffers. No large Actions artifact/cache.

Docker Personal includes unlimited public repositories and 200 authenticated
pulls/6h. Docker does not publish an unconditional free image-storage byte quota;
fair-use throttling/additional-charge terms remain. Account eligibility and base
blob mounting must be verified after connection, not assumed. Do not upgrade or
enable billing if the free operation is rejected.

Image size is still approximately 33GB compressed, not yet measured after gzip.
It includes exactly18,144,966,705 model bytes; the change is how it is assembled,
not removal of required dependencies. Streaming keeps the free runner disk small.

## Before the separately approved first GPU test

Fetch the immutable image digest from the small build receipt. Full container CPU
boot/node/model discovery has not run on this small runner; source checks are not
runtime proof. Do not claim GPU compatibility or successful container boot.

Set `PROOF_WORKFLOW_B64` and `PROOF_CONTRACT_B64` on the future endpoint from the
existing fixed local cloud JSON files. These contain the established prompt and
reference checksum; they are not included in the public repo/image. The reference
image is supplied only in the one approved job. Keep endpoint min0/max1/GPU1,
idle5s, execution600s, TTL900s, no network volume. The20min whole-attempt watchdog
includes checksum verification, startup, model loading, generation and delivery.

The first job must return its bounded checksum-verified MP4, full local decode and
saved provider zero-worker evidence before the existing client allows job2.
Save settled billing with the clip. Keep local controls disabled/$0 meanwhile.

## Primary references checked 2026-10-05

- https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- https://docs.github.com/en/actions/reference/limits
- https://docs.docker.com/docker-hub/usage/
- https://github.com/opencontainers/distribution-spec/blob/main/spec.md
- https://docs.runpod.io/serverless/endpoints/model-caching
