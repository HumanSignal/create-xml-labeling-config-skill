---
name: create-xml-labeling-config-skill
description: >-
  Draft a Label Studio XML labeling configuration from a plain-English
  description of the annotation task, validate it locally and against the
  user's running Label Studio instance, then — only after explicit approval —
  push it to that instance as a new project or as an update to an existing
  project. Use when the user asks to "build a labeling config / interface /
  template for X", "set up a Label Studio project for Y", "make me an XML
  config for Z", or shares a labeling brief and wants the result deployed.
---

# Create XML Labeling Config

End-to-end workflow: user describes what they want to annotate →
the skill drafts the XML config (using the baked-in authoring guide,
not AutoMax) → validates locally + against the user's LS instance →
shows the config and a sample task for review → pushes to LS only
after explicit approval. The user **does not** need AutoMax access
for any step — everything the skill needs to write a correct config
lives in `references/config_guide.md`.

This is the XML-based Label Studio labeling configuration runtime. Do
not use the JSX-based Interfaces format unless the user explicitly
asks for a custom React interface — hand off to `create-interface-skill`
for that.

## Operating principle

All Label Studio authoring knowledge is in
`references/config_guide.md` — rules, tag references, templates,
common mistakes. Read it before drafting. Do not invent tags or
attributes that aren't in the guide. Do not query AutoMax — the skill
is designed to be self-contained, and assuming AutoMax is available
will produce surprising failures for users without that connection.

If the guide is silent on something the user is asking for, say so
explicitly rather than guessing. Suggest a near-match from the guide
or ask the user to confirm a specific tag.

## Inputs

The user gives you at minimum a **description of the annotation task**.
Useful detail to gather (ask once, briefly, only if not provided):

- **What data type** — text / image / audio / video / PDF / HTML /
  paragraphs / time series / table. This determines the object tag.
- **What annotators do** — classify (single/multi), span-label,
  bounding-box, polygon, keypoints, transcribe, rate, rank, compare
  pairwise, fill free text, taxonomize. This determines control tags.
- **Label set** — concrete label names if classifying or
  span-labeling. ("Sentiment" alone isn't enough; "Positive /
  Neutral / Negative" is.)
- **Dataset field names** — what keys does their task JSON / CSV
  actually use? If unsure, default to sensible names (`text`,
  `image`, `audio`, `video`) and surface that in the review so the
  user can correct.

Optional:

- **Target project** — new project (default) or an existing
  `--project-id` they want to update.
- **Project title / description** for a new project. If not given,
  derive a sensible title from the task description.
- **Output path** for the saved config — default
  `/tmp/labeling-config-<slug>-<YYYY-MM-DD>.xml`. A sibling sample
  tasks file is written next to it at
  `/tmp/labeling-config-<slug>-<YYYY-MM-DD>.tasks.json`.

Don't over-interrogate. Two or three quick clarifying questions are
fine; a long requirements interview is not. If the user gives you a
one-line ask ("NER for legal docs"), pick reasonable defaults, show
your work, and let them redirect at the approval gate.

## Credentials

`.env` at the skill root (or env vars):

- `LABEL_STUDIO_URL` — base URL of the user's LS instance, e.g.
  `http://localhost:8080`. Default `http://localhost:8080`.
- `LABEL_STUDIO_API_KEY` — personal API key from the LS Account page
  (Account & Settings → Access Token).

If either is missing, the validate / push steps will warn the user;
local structural validation still runs and the config is still saved
to disk for manual upload.

## Workflow

Run the steps in order. **Never push to Label Studio before the user
approves**, and never run `push_config.py` without the `--confirm`-
style explicit yes described in step 5.

### Step 1 — Clarify the task (briefly)

Skim the user's request. If you can already pick the right object
tag, control tag(s), and labels with high confidence, skip ahead to
Step 2 and surface assumptions in Step 4. Otherwise ask 1-3 questions
max, e.g.:

- "Is the data text, images, or something else?"
- "Single label per item, or multiple?"
- "What labels do you want — give me the list?"

Stop asking once you have enough to draft. Defaults are fine; the
user fixes them at the approval gate.

### Step 2 — Read the authoring guide and draft the config

Open `references/config_guide.md` and read sections 1-9
substantively before drafting. (Section 8 has the copy-paste
templates — start from the closest one rather than from a blank
page.) Specific things to nail down in your head before writing XML:

- The **object tag** and the dataset variable (`$text`, `$image`,
  `$audio`, etc.).
- The **control tag(s)** and their `toName` pointing at the object
  tag's `name`. Re-read section 2.3 — `toName` going to a control
  tag instead of an object tag is the #1 way these break.
- **Naming.** Every tag's `name` is unique and semantic
  (`sentiment`, not `c1`). The user will read these in the config
  and in the annotation JSON, so make them legible.
- **Required attributes.** `Choices`/`Labels` usually need a
  `choice="single"` or `choice="multiple"`; `TextArea` usually wants
  `rows` and a `placeholder`; `Image` benefits from `zoomControl`.
- **Visual layout.** For multi-step configs, group with nested
  `<View>` and `<Header>` tags. The guide's section 6 covers
  styling — only put `style=` on View/Filter/Header and `className=`
  on View.
- **Sample task JSON.** Build a small example task that matches the
  config's `$keys` so the user can immediately import and verify.
  Use sample assets from the guide's section 7 when the user hasn't
  provided real data URLs. Write it as a JSON **list** of task
  objects (`[{"data": {...}}]`) so it can be uploaded to Label
  Studio's Data Manager as-is.

Write the config and the sample tasks to sibling temp files:

```bash
# Pick a slug from the project title or task description.
CONFIG_PATH=/tmp/labeling-config-<slug>-$(date +%Y-%m-%d).xml
TASKS_PATH=/tmp/labeling-config-<slug>-$(date +%Y-%m-%d).tasks.json
```

### Step 3 — Validate locally

Always run local validation before showing anything to the user.

```bash
python3 ./scripts/validate_config.py "$CONFIG_PATH"
```

If it reports errors, **fix the config and re-validate** — don't
forward broken XML to the user for review. The validator catches:

- malformed XML
- missing / duplicate `name` attributes
- `toName` pointing at a non-existent or non-object tag
- bad nesting (`<Label>` inside `<Label>`, `<Choice>` inside
  `<Choice>` outside Taxonomy)
- `style=` / `className=` on the wrong tags
- deprecated tags (`AudioPlus`, `Repeater`)
- `visibleWhen` missing on a nested control whose wrapping `<View>`
  has it (this is a warning, not a hard error — fix it anyway)

Warnings are informational; act on them if they apply. If the user
specifically asked for something the validator warns about, override
and explain in the review.

### Step 4 — Validate server-side (when LS is reachable)

```bash
python3 ./scripts/validate_config.py "$CONFIG_PATH" --server
```

The `--server` flag posts the config to the user's Label Studio
instance and uses LS's own validator. This catches engine-level
issues that pure XML/structural checks can miss — e.g. unknown tag
combinations, mismatched control/object types, attributes that don't
work together. It does this by creating a throwaway project, posting
the config, and deleting the project immediately — no cruft is left
behind on success.

If `LABEL_STUDIO_API_KEY` is missing, the script skips this layer
with a warning and the user can still review the config locally;
they just won't get engine-level validation until they wire up the
key. Surface that to the user verbatim instead of hiding it.

If the server-side validator rejects the config, **fix and re-run
both validators** before showing the user. The whole point of having
two layers is that no broken config reaches the approval gate.

### Step 5 — Show the user; wait for explicit approval

Reply with **four things**, in this order:

1. **The config itself** in a fenced ```xml``` block, with the
   `.xml` path the user can find it at.
2. **A sample task JSON** matching the config's `$keys`, in a fenced
   ```json``` block, with the `.tasks.json` path the user can
   upload directly to the Data Manager. Pick realistic-looking
   sample data — for images use one of the documented sample URLs
   from section 7 of the guide. Always write the file as a JSON
   list (`[{"data": {...}}]`) so Data Manager / `import_tasks`
   accept it without reshaping.
3. **Assumptions you made** (if any), as a short bulleted list. Be
   specific. "Assumed dataset key is `$text`; change if your CSV
   column is named differently."
4. **Validation status** — local + server, in one line each.

Then explicitly ask:

> "Want me to push this to Label Studio? Reply **yes** to create a
> new project / update project N, or tell me what to change."

**Wait for an explicit yes** before running `push_config.py`. A "ya"
or "sure" or "go ahead" is fine. Anything ambiguous → ask again.
Anything that looks like a change request → iterate on the config
and re-run steps 2-4.

If the user pushed back on assumptions (label names, dataset keys,
data type, etc.), update the config, re-validate (both layers), and
re-present. Don't silently push a tweaked version.

### Step 6 — Push (only on explicit yes)

For a new project:

```bash
python3 ./scripts/push_config.py "$CONFIG_PATH" \
  --title "<project title>" \
  --description "<short description>"
```

For an update to an existing project:

```bash
python3 ./scripts/push_config.py "$CONFIG_PATH" --project-id <id>
```

The script prints the project URL on success — repeat it verbatim
in your reply so the user can click through.

If the push fails (HTTP error, auth failure, etc.), surface the
error verbatim. Most failures are:

- `LABEL_STUDIO_API_KEY` missing or wrong → tell user to refresh
  from Account page.
- `LABEL_STUDIO_URL` wrong → typical when LS is on a non-default
  port or behind a tunnel.
- Updating a project that already has annotations and the config
  change invalidates them → LS will return a structured error. Pass
  it through verbatim and recommend creating a new project instead.

### Step 7 — Tell the user what to do next

After a successful push, **open the sample tasks file** so the user
can drag-and-drop it into the Data Manager:

```bash
open "$TASKS_PATH"
```

`open` is macOS only. The skill is built for a local LS workflow on
macOS (see the Notes & limits section). On other platforms, fall
back to printing the path and skipping the `open` call.

Then end the response with a 2-line hint:

- The project URL.
- One concrete next step — usually "import the sample tasks at
  `<TASKS_PATH>` from the Data Manager, or via
  `ls.projects.import_tasks(...)` with the SDK." If the user's data
  is in cloud storage, mention Project Settings → Cloud Storage.
  Don't generate the import command unless the user asks for it —
  that's a separate task.

## What this skill does NOT do

- **Query AutoMax.** Everything needed to draft a correct config is
  in `references/config_guide.md`. If you find yourself reaching for
  AutoMax, the guide is missing something — update the guide
  instead of relying on a runtime MCP.
- **Push without explicit approval.** Step 5's approval gate is
  load-bearing. Skipping it once teaches the user that the skill
  acts on its own and breaks trust.
- **Generate ReactCode / custom interfaces.** That's the
  `create-interface-skill`'s job and the right reference materials
  live there. If the user asks for ReactCode or a custom React UI,
  hand off to that skill instead of attempting it here.
- **Import tasks.** Pushing the project's config and importing data
  are two different decisions. The skill stops at the project URL;
  the user imports data separately (and the SDK / UI / cloud
  storage docs cover that better than this skill could).
- **Reformat a config you didn't generate.** If the user pastes
  their own config and asks for tweaks, run it through
  `validate_config.py` first and surface any issues before
  editing — they may have valid intent the validator catches as
  broken (e.g. a typo) before you over-rewrite.

## Output discipline

- Configs go to `/tmp/labeling-config-<slug>-<YYYY-MM-DD>.xml`. The
  path is shown to the user in step 5.
- Sample tasks go to a sibling file
  `/tmp/labeling-config-<slug>-<YYYY-MM-DD>.tasks.json`, always
  written as a JSON list so it imports cleanly into the Data
  Manager. The path is shown alongside the inline JSON in step 5.
- On a successful push, run `open <tasks-path>` so the user can
  drag-and-drop the file into the new project's Data Manager
  without hunting for it.
- Don't paste the config back into chat *after* a successful push —
  the user has it on disk and in Label Studio. The post-push reply
  is short: project URL, next step, done.
- If the user iterates, keep the same temp file paths and overwrite
  both files. One config + one tasks file per task, not a graveyard
  of versions.

## Notes & limits

- **Local LS only.** The skill is built around `http://localhost:8080`
  by convention. It works fine with a remote LS — just set
  `LABEL_STUDIO_URL` to that URL — but the README and prompts are
  worded for the local case because that's the common scenario.
- **Validation is exhaustive but not complete.** The local validator
  catches every structural rule listed in the authoring guide. The
  server validator catches engine-level issues on top. Together they
  catch ~all broken configs, but the editor can still surprise you
  on truly weird tag combinations (relations across many regions,
  experimental tags). When something passes both validators but
  misbehaves in the UI, the issue is almost always a missing
  attribute on a control tag — re-read the relevant tag's section
  in `config_guide.md`.
- **`--project-id` updates are partial.** Label Studio applies its
  own "compatibility" check when updating a config on a project
  with existing annotations. If you rename a control's `name`, LS
  may refuse the update to protect existing results. If that
  happens, either keep the old names or create a fresh project.
- **No batch mode.** One config per run. If the user wants several,
  do them sequentially with separate approval gates.
