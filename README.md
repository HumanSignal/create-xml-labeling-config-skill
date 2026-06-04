# Create XML Labeling Config Skill

Agent skill for drafting Label Studio XML labeling configurations from a
plain-English description of the annotation task. It validates configs locally
and against your running Label Studio instance, then — only after you say yes —
pushes the result to LS as a new project or as an update to an existing one.

It can be installed into Claude, Codex, Cursor, and other agents supported by
the `skills` CLI.

Use this skill when you want an agent to create or iterate on a Label Studio
project from a labeling brief: text classification, NER/span labeling, image
bounding boxes, audio transcription, taxonomy review, ranking, pairwise
comparison, time-series segmentation, and so on.

The skill is **self-contained**: every rule and template it needs to write a
correct config lives in `references/config_guide.md`. No external knowledge
base or runtime lookup is required.

## Install

Install with the `skills` CLI. Pick the command for your agent:

**Codex**

```bash
npx skills add humansignal/create-xml-labeling-config-skill --skill create-xml-labeling-config-skill -g -a codex
```

**Claude Code**

```bash
npx skills add humansignal/create-xml-labeling-config-skill --skill create-xml-labeling-config-skill -g -a claude-code
```

**Cursor**

```bash
npx skills add humansignal/create-xml-labeling-config-skill --skill create-xml-labeling-config-skill -g -a cursor
```

Restart your agent after installing.

## Use

Ask your agent to use the skill:

```text
Use $create-xml-labeling-config-skill to build a labeling config for
sentiment classification with labels Positive / Neutral / Negative.
```

Other example prompts:

- *"Use $create-xml-labeling-config-skill to make an NER config for legal
  contracts with labels Party / Date / Amount / Clause type."*
- *"Use $create-xml-labeling-config-skill to set up a Label Studio project
  for image bounding boxes — labels Person, Vehicle, Animal."*
- *"Use $create-xml-labeling-config-skill to update project 42 with a
  'rationale' text area on the rating config."*

The skill produces a `.xml` Label Studio config and a sample task JSON,
validates both layers (local + server), and only pushes to your LS instance
after you explicitly approve.

## What you get per run

- A `.xml` config saved to `/tmp/labeling-config-<slug>-<date>.xml`.
- A sample task JSON in the chat reply (so you can import a test row
  immediately).
- Local + server-side validation results.
- After your approval: the project URL in your Label Studio instance.

## Prerequisites

- A running Label Studio (community OSS or LSE) you can reach from
  this machine. Default assumed URL is `http://localhost:8080`.
- A Label Studio personal API key. Get one from your LS instance:
  **Account & Settings → Access Token → Copy**.

### Install Label Studio locally (if you don't have it yet)

```bash
# In a fresh virtualenv:
pip install label-studio
label-studio start
# Open http://localhost:8080, create an account, then grab your
# Access Token from the Account page.
```

That's all you need — the skill itself doesn't depend on the LS
Python package being installed (it talks to LS over HTTP).

### Or deploy Label Studio on Hugging Face Spaces

If you'd rather not run Label Studio locally, you can stand up a hosted
instance with persistent storage on a [Hugging Face Space](https://huggingface.co/spaces)
using three `hf` CLI commands — handy when you want a shareable URL or
have no local environment. See
[`references/deploy_on_spaces.md`](references/deploy_on_spaces.md).

## Credentials (`.env`)

The scripts read credentials from `.env` at the skill root. They walk
up from their own directory until they find it, so this works whether
the skill is symlinked into a project or run standalone.

```bash
cd create-xml-labeling-config-skill
cp .env.example .env
# then open .env in your editor and fill in the values
```

`.env` is gitignored. `.env.example` is the trackable template that
documents what each variable does and where to get it.

Required:

- `LABEL_STUDIO_URL` — base URL of your LS instance, e.g.
  `http://localhost:8080`.
- `LABEL_STUDIO_API_KEY` — personal API token from the Account page.

If `LABEL_STUDIO_API_KEY` isn't set, the server-side validation and
the push step are skipped (you'll see warnings) but local validation
still runs and the config is still saved to disk so you can upload it
manually.

## Python dependency

Just the standard library. The validate and push scripts use
`urllib` + `xml.etree` from the stdlib so there's no install step.

```bash
pip install -r requirements.txt   # currently a no-op; reserved for future deps
```

## Repository Layout

```text
SKILL.md
README.md
.env.example
requirements.txt
agents/openai.yaml
references/
  config_guide.md
scripts/
  validate_config.py
  push_config.py
```

`SKILL.md` contains the core workflow and hard rules. `references/config_guide.md`
is the baked-in Label Studio authoring guide loaded by the agent when drafting
a config. The `scripts/` directory holds the local + server-side validator and
the push tool.

## How the validator works

`validate_config.py` runs three layers:

1. **XML well-formed.** Must parse as XML with a single `<View>` root.
2. **Structural rules** baked from the LS authoring guide:
   - every object/control tag has a `name`
   - all `name`s are unique
   - every control tag's `toName` points at an existing **object** tag
   - `<Pairwise>` allows two comma-separated `toName` targets
   - `<Label>` / `<Choice>` nesting rules
   - `style=` only on View/Filter/Header; `className=` only on View
   - no deprecated tags (`AudioPlus`, `Repeater`)
   - `visibleWhen` consistency between a `<View>` and the controls
     it wraps
3. **Server-side** (optional, with `--server`): posts the config to
   your LS instance — either against an existing `--project-id`'s
   `/validate/` endpoint, or by creating a throwaway project that's
   deleted immediately. Catches engine-level issues that purely
   structural checks miss.

Run it directly on any file:

```bash
python3 scripts/validate_config.py /tmp/my-config.xml
python3 scripts/validate_config.py /tmp/my-config.xml --server
python3 scripts/validate_config.py /tmp/my-config.xml --server --project-id 42
python3 scripts/validate_config.py - < my-config.xml
python3 scripts/validate_config.py /tmp/my-config.xml --json   # machine-readable
```

Exit code is `0` only if every requested check passes.

## How the push works

`push_config.py` either creates a new project from the config or
updates an existing project's `label_config`:

```bash
# New project
python3 scripts/push_config.py /tmp/my-config.xml --title "Legal NER"

# Update existing
python3 scripts/push_config.py /tmp/my-config.xml --project-id 42

# Dry-run (no network call)
python3 scripts/push_config.py /tmp/my-config.xml --title "Test" --dry-run
```

On success it prints the project URL.

**A note on updates:** if the existing project already has
annotations, Label Studio may reject changes that would invalidate
those annotations (e.g. renaming a `Choices` tag). Keep the
object/control `name`s stable across updates, or — if you need a
breaking change — create a fresh project.

## What this skill does NOT do

- **Auto-import data.** It pushes the labeling configuration only.
  After you have the project URL, import tasks via the Data Manager,
  the SDK (`ls.projects.import_tasks(...)`), or Project Settings →
  Cloud Storage.
- **Generate ReactCode / custom React interfaces.** That's the
  `create-interface-skill`'s job. If you ask for "use ReactCode" or
  "custom interface", this skill should hand off to that one.
- **Sync changes back from LS.** One-way: skill → LS. If you tweak
  the config in the LS UI after pushing, this skill won't pull those
  changes back.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Could not reach Label Studio at http://localhost:8080` | LS isn't running, or your `LABEL_STUDIO_URL` is wrong. Confirm with `curl http://localhost:8080/health`. |
| `--server requested but LABEL_STUDIO_API_KEY is not set` | Set `LABEL_STUDIO_API_KEY` in `.env`. Get the token from the LS Account page. |
| `Label Studio rejected the config (HTTP 400): label_config: ...` | LS's engine-level validator caught something. The error message is usually specific (`toName` mismatch, unknown attribute). Fix and re-validate. |
| `Label Studio rejected config update for project N (HTTP 400): ... annotations` | The update would invalidate existing annotations. Either keep names stable, or create a new project. |
| Config passes both validators but the LS UI behaves oddly | Almost always a missing attribute on a control tag. Re-read the relevant tag's section in `references/config_guide.md`. |
