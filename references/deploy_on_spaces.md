# Deploy Label Studio on a Hugging Face Space

This skill **drafts and validates** a Label Studio XML config. Drafting and local
validation need no instance — but the two steps that deliver the payoff need a
reachable Label Studio instance at `LABEL_STUDIO_URL`:

- `validate_config.py --server` — validates against Label Studio's own engine.
- `push_config.py` — pushes the config to a new or existing project.

The skill has no story for *creating* that instance. Any standard Label Studio
install works — local, Docker, self-hosted, or Enterprise/cloud. This guide
covers **one convenient option**: a hosted instance on a
[Hugging Face Space](https://huggingface.co/spaces) with persistent storage,
**agent-executable end-to-end via the `hf` CLI** (no UI clicks). Once the instance
is up — by whatever route — return to the workflow in `SKILL.md`.

## Contents

- [Prerequisites](#prerequisites)
- [Three-command deploy](#three-command-deploy)
- [Verify](#verify)
- [Get a credential for this skill](#get-a-credential-for-this-skill)
- [Lock down a non-demo deployment](#lock-down-a-non-demo-deployment)
- [Hardware notes](#hardware-notes)

## Prerequisites

- **`hf` CLI ≥ 1.14** — ships with `huggingface_hub` (`pip install huggingface_hub`,
  or via uv/conda). See the
  [installation guide](https://huggingface.co/docs/huggingface_hub/installation).
- **Logged in**: `hf auth login` (or set `HF_TOKEN`).
- **A namespace you can write to** — your user, or an org you belong to.

## Three-command deploy

Set the variables once, then run the three commands. Replace `<ns>` with your
namespace and `<space>` with the Space name you want.

```bash
NS=<ns>
SPACE=<space>
BUCKET=label-studio-data
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
```

**1. Create a storage bucket.** Spaces are ephemeral — local disk is wiped on
restart. A [bucket](https://huggingface.co/docs/huggingface_hub/guides/buckets)
mounted at `/data` (step 2) holds Label Studio's SQLite database and uploaded
media instead, so projects, tasks, and annotations survive restarts.

```bash
hf buckets create $NS/$BUCKET
```

**2. Duplicate the official Label Studio Space**, attaching the bucket and setting
env + secret in one shot:

```bash
hf repos duplicate LabelStudio/LabelStudio $NS/$SPACE \
    --type space \
    --flavor cpu-upgrade \
    -v hf://buckets/$NS/$BUCKET:/data \
    -e LABEL_STUDIO_BASE_DATA_DIR=/data \
    -e STORAGE_PERSISTENCE=1 \
    -s SECRET_KEY=$SECRET_KEY \
    --exist-ok
```

| Flag | Purpose |
|---|---|
| `-v hf://buckets/$NS/$BUCKET:/data` | Mount the bucket at `/data` so writes survive restarts |
| `-e LABEL_STUDIO_BASE_DATA_DIR=/data` | Point Label Studio at `/data` for SQLite + media |
| `-e STORAGE_PERSISTENCE=1` | Enable Label Studio's persistence mode |
| `-s SECRET_KEY=...` | Stable Django `SECRET_KEY` so sessions survive restarts |
| `--flavor cpu-upgrade` | 16 GB RAM tier; `cpu-basic` works for trivial projects |

**3. Factory rebuild** so the mount and env vars take effect on a fresh container:

```bash
hf spaces restart $NS/$SPACE --factory-reboot
```

## Verify

```bash
hf spaces logs $NS/$SPACE          # watch build / runtime logs
hf spaces volumes ls $NS/$SPACE    # confirm the bucket mount
hf spaces variables ls $NS/$SPACE  # confirm env vars
```

Open `https://$NS-$SPACE.hf.space` once the logs show
`Starting development server at http://0.0.0.0:8080/`.

## Get a credential for this skill

After signing up the first user, generate an **Access Token** from
**Account & Settings → Access Token** and set it so `validate_config.py --server`
and `push_config.py` can reach the instance:

```
LABEL_STUDIO_URL=https://<ns>-<space>.hf.space
LABEL_STUDIO_API_KEY=<access-token>
```

If you hit `401 — legacy token authentication has been disabled for this
organization`, your instance has legacy tokens switched off (a common modern
default). Use a **Personal Access Token** instead — Account & Settings →
Personal Access Tokens — and follow Label Studio's
[access tokens guide](https://labelstud.io/guide/access_tokens) for the
refresh-token exchange.

## Lock down a non-demo deployment

The duplicated Space allows public signup by default. For anything beyond a
throwaway demo, disable open signup and create an admin before sharing the URL:

```bash
# 1. In the Space's Dockerfile, add then commit + push:
#    ENV LABEL_STUDIO_DISABLE_SIGNUP_WITHOUT_LINK=true

# 2. Seed the bootstrap admin via secrets:
hf spaces secrets add $NS/$SPACE \
    -s LABEL_STUDIO_USERNAME=admin@example.com \
    -s LABEL_STUDIO_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
hf spaces restart $NS/$SPACE --factory-reboot
```

After this, accounts come only from the admin invite link inside Label Studio.

## Hardware notes

- **`cpu-basic`** ignores `--sleep-time` and has a fixed 48-hour timeout. Use
  `cpu-upgrade` or above for auto-pause.
- **`cpu-upgrade` (16 GB)** is comfortable up to ~50k tasks; SQLite-on-bucket
  performance degrades past that. For external Postgres, cloud-storage backends,
  and advanced knobs, see the
  [upstream Space README](https://huggingface.co/spaces/LabelStudio/LabelStudio/blob/main/README.md).
