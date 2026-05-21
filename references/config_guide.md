# Label Studio Labeling Configuration — Authoring Guide

This is the **self-contained reference** the skill uses to draft XML
labeling configs. It is distilled from the same source material the
AutoMax MCP returns when asked for Label Studio configuration help —
overview, project-setup guidelines, sample tasks, and tag references.
The skill must work **without** AutoMax connected, so treat this file
as the authority.

If you are extending the skill: when AutoMax changes its guidance,
update this file. Don't rely on the MCP being available at runtime.

---

## 1. Mental model

A Label Studio config is a small XML document wrapped in `<View>` that
describes **two things**:

1. **What data the annotator sees** — declared by **object tags**
   (`<Text>`, `<Image>`, `<Audio>`, `<Video>`, `<HyperText>`,
   `<Paragraphs>`, `<TimeSeries>`, `<Table>`, `<PDF>`, `<List>`,
   `<Chat>`).
2. **How the annotator interacts** — declared by **control tags**
   (`<Labels>`, `<Choices>`, `<TextArea>`, `<Rating>`, `<Taxonomy>`,
   `<Number>`, `<RectangleLabels>`, `<PolygonLabels>`,
   `<KeyPointLabels>`, `<BrushLabels>`, `<EllipseLabels>`,
   `<VideoRectangle>`, `<TimeSeriesLabels>`, `<ParagraphLabels>`,
   `<HyperTextLabels>`, `<Pairwise>`, `<Relations>`).

Control tags link to object tags via `toName=<object-tag-name>`. The
object tag's `value="$key"` binds it to a field in your task JSON.

```xml
<View>
  <Text name="text" value="$text"/>
  <Choices name="sentiment" toName="text" choice="single">
    <Choice value="Positive"/>
    <Choice value="Negative"/>
    <Choice value="Neutral"/>
  </Choices>
</View>
```

In this config: `<Text>` is the object tag (it displays the data),
and `<Choices>` is the control tag (it captures the answer). The
control's `toName="text"` matches the object's `name="text"`. The
`$text` in `value="$text"` is a dataset variable — it maps to the
`"text"` key in your task's `data` object.

Task JSON for the above:

```json
{"data": {"text": "Opossums are great"}}
```

That's the whole pattern. Everything else is variations.

---

## 2. Hard rules (validator enforces these)

These are the rules that, if broken, will either crash the editor or
silently produce broken annotations. The local validator in
`scripts/validate_config.py` checks every one of them.

### 2.1 Wrapper

- The config **must** be wrapped in a single `<View>` root.
- Nested `<View>` tags are fine and encouraged for visual grouping.

### 2.2 `name` attributes

- Every object tag and every control tag **must** have a `name`.
- `name` values **must be unique** across the whole config.

### 2.3 `toName` attributes (the #1 source of broken configs)

- Every control tag **must** have a `toName`.
- `toName` **must** point to the `name` of an **object tag**. It must
  not point to another control tag.
- `toName` points to **exactly one** object tag, **except**
  `<Pairwise>`, which points to two (comma-separated, e.g.
  `toName="textA,textB"`).
- The referenced object tag **must exist** in the same config.

### 2.4 `value` attributes

- Object tags **must** declare a `value`. For dynamic data (the
  common case) the value is a dataset variable: `value="$text"`,
  `value="$image_url"`, etc. The variable name must match the
  corresponding key in your task JSON's `data` object.
- Plain strings are allowed for static `<Header>` / `<Text>` /
  `<Label>` content.

### 2.5 Tag nesting

| Tag                                                                                          | What it can contain          | Recursive nesting allowed? |
| -------------------------------------------------------------------------------------------- | ---------------------------- | -------------------------- |
| `<Label>`                                                                                    | nothing                      | no                         |
| `<Choice>`                                                                                   | nothing (except in Taxonomy) | no (except in Taxonomy)    |
| `<Labels>`, `<RectangleLabels>`, `<PolygonLabels>`, `<KeyPointLabels>`, `<BrushLabels>`, `<EllipseLabels>`, `<HyperTextLabels>`, `<ParagraphLabels>`, `<TimeSeriesLabels>`, `<VideoRectangle>` | `<Label>` (one level)        | no                         |
| `<Choices>`                                                                                  | `<Choice>` (one level)       | no                         |
| `<Taxonomy>`                                                                                 | `<Choice>`                   | **yes** — recursive        |

### 2.6 Styling — `className` and `style`

- `className=` may only be set on `<View>`. To style anything else,
  wrap it in a `<View>` and apply `className=` to the `<View>`.
- `style=` may only be set on `<View>`, `<Filter>`, or `<Header>`. For
  anything else, wrap in `<View>` and style the `<View>`.
- Use `<Style>...</Style>` to declare custom CSS classes.

### 2.7 `perRegion` and `perItem`

- `perRegion="true"` is used on control tags whose answer applies to a
  specific region (a span, bounding box, keypoint, etc.) — typically
  inside a `<View visibleWhen="region-selected">` wrapper.
- `perItem="true"` is used when an object tag uses `valueList` (e.g.
  `<Image valueList="$images">`) and you want one answer per image.
- Both still require `toName=` pointing to the relevant **object** tag
  (never to another control tag).

### 2.8 Tags to avoid

- `<AudioPlus>` — deprecated. Use `<Audio>`. Same attributes, same
  functionality.
- `<Repeater>` — deprecated. Causes performance issues on large tasks
  and breaks agreement metrics. If you need to label multiple items of
  the same type, prefer `<Image valueList="$images">` with
  `perItem="true"` controls, or `<Paragraphs>`, or `<List>`.

### 2.9 Don't invent attributes

Do not add attributes that are not in the official tag documentation
unless the user explicitly asks for them. If you find yourself wanting
an attribute that isn't documented, the answer is almost always to
use a different tag.

### 2.10 ML-backend `model_*` attributes

Only emit `model_*` attributes (e.g. `model_score_threshold`) when the
user has confirmed they're connecting an ML backend that uses them
(YOLO, etc.). Otherwise omit them.

### 2.11 ReactCode

`<ReactCode>` is Enterprise-only and is only justified when built-in
tags cannot do the job (spreadsheet editors, tree/graph views, custom
canvases, multi-panel forms, embedded iframes). For ordinary
classification / NER / bbox / transcription / rating tasks, use the
standard tags — never reach for ReactCode "to be flexible." If the
user explicitly says "use ReactCode" or "custom interface," ask them
to use the `create-interface-skill` instead — that skill has the
right reference materials for ReactCode generation.

---

## 3. Conditional logic — `visibleWhen` / `whenTagName` / `whenChoiceValue`

Show/hide parts of the interface based on what the annotator has
selected. The attributes:

| Attribute         | Allowed values                                                                  |
| ----------------- | ------------------------------------------------------------------------------- |
| `visibleWhen`     | `region-selected` / `no-region-selected` / `choice-selected` / `choice-unselected` |
| `whenTagName`     | the `name` of the controlling Choices/Labels tag                                |
| `whenChoiceValue` | the `value` of the controlling Choice                                           |
| `whenLabelValue`  | the `value` of the controlling Label                                            |

**Critical gotcha:** put `visibleWhen` on **both** the wrapping `<View>`
and on the nested control. If you only set it on the `<View>`, the
nested control still serializes its (default) answer into the
annotation result. Example:

```xml
<View>
  <Text name="text" value="$text"/>
  <Choices name="feedback" toName="text" choice="single">
    <Choice value="Good"/>
    <Choice value="Bad"/>
  </Choices>
  <View visibleWhen="choice-selected" whenTagName="feedback" whenChoiceValue="Bad">
    <Choices name="color" toName="text"
             visibleWhen="choice-selected" whenTagName="feedback" whenChoiceValue="Bad">
      <Choice value="Red"/>
      <Choice value="Green"/>
    </Choices>
  </View>
</View>
```

---

## 4. Object tag reference (the common ones)

### 4.1 `<Text>` — plain text

```xml
<Text name="t" value="$text"/>
```

| Attribute            | Type                                 | Default | Notes                                                      |
| -------------------- | ------------------------------------ | ------- | ---------------------------------------------------------- |
| `name`               | string                               | —       | required                                                   |
| `value`              | string                               | —       | required; `$key` for dataset variable, or literal text     |
| `valueType`          | `url` / `text`                       | `text`  | `url` loads from URL; `text` treats the value as the text  |
| `saveTextResult`     | `yes` / `no`                         | —       | Whether to store the labeled text in the result            |
| `encoding`           | `none` / `base64` / `base64unicode`  | —       |                                                            |
| `selectionEnabled`   | bool                                 | true    | Disable to use Text purely for display                     |
| `highlightColor`     | hex string                           | —       |                                                            |
| `showLabels`         | bool                                 | —       |                                                            |
| `granularity`        | `symbol`/`word`/`sentence`/`paragraph` | —     | Enforce span alignment to whole words / sentences          |

### 4.2 `<HyperText>` — HTML

```xml
<HyperText name="h" value="$html" inline="true"/>
```

| Attribute        | Type | Default | Notes                                                |
| ---------------- | ---- | ------- | ---------------------------------------------------- |
| `name` / `value` |      |         | required                                             |
| `valueType`      | `url` / `text` | `text` |                                                |
| `inline`         | bool | false   | Embed HTML directly (true) vs render in iframe (false) |
| `clickableLinks` | bool | false   | Allow opening links from inside the markup           |

Other attributes mirror `<Text>` (selectionEnabled, granularity, etc.).

### 4.3 `<Image>` — single image or list

```xml
<Image name="img" value="$image_url"/>
<!-- multi-image labeling -->
<Image name="imgs" valueList="$images"/>
```

Key attributes:

- `value` (single image) / `valueList` (multiple images, expects a
  JSON list of URLs in the data field).
- `zoom`, `zoomControl`, `brightnessControl`, `contrastControl`,
  `rotateControl` — toolbars on the canvas.
- `crossOrigin="anonymous"` — when loading from a CORS-enabled CDN.

For multi-image (`valueList`), pair with `perItem="true"` on any
classification controls so each image gets its own answer.

### 4.4 `<Audio>` — audio (replaces deprecated AudioPlus)

```xml
<Audio name="a" value="$audio_url"/>
```

Common attributes: `defaultZoom`, `defaultSpeed`, `defaultVolume`,
`hotkey`, `cursorWidth`, `cursorColor`.

### 4.5 `<Video>` — video frames

```xml
<Video name="v" value="$video"/>
```

Pair with `<VideoRectangle>` for object tracking, `<Labels>` for
classifying tracked objects, `<Choices>` (perItem) for per-frame
labels.

### 4.6 `<Paragraphs>` — speaker-attributed dialogue

Data shape (JSON list of `{author, text}` objects):

```json
{"data": {"dialogue": [{"author": "Alice", "text": "Hi"},
                        {"author": "Bob", "text": "Hello"}]}}
```

Config:

```xml
<Paragraphs name="d" value="$dialogue" nameKey="author" textKey="text"/>
<ParagraphLabels name="lbl" toName="d">
  <Label value="Question"/>
  <Label value="Answer"/>
</ParagraphLabels>
```

### 4.7 `<TimeSeries>` — multivariate time series

Two value types:

- `valueType="url"` — load CSV from a URL.
- `valueType="json"` — embed columns directly in the task JSON
  (`{"time": [...], "channel1": [...], ...}`).

```xml
<TimeSeries name="ts" value="$csv" valueType="url"
            timeColumn="time" sep=",">
  <Channel column="channel1" displayFormat=",.1f"/>
  <Channel column="channel2" displayFormat=",.1f"/>
</TimeSeries>
<TimeSeriesLabels name="lbl" toName="ts">
  <Label value="Anomaly"/>
</TimeSeriesLabels>
```

### 4.8 `<Table>` — key-value table

```xml
<Table name="tbl" value="$row"/>
```

Where `$row` is a flat JSON object: `{"col1": "v1", "col2": "v2"}`.

### 4.9 `<List>` — ranked items

```xml
<List name="results" value="$results" title="Title" elementValue="$body"/>
```

For SERP-ranking / item-ranking tasks; pair with a `<Ranker>` or
`<Choices>` to collect a ranking.

---

## 5. Control tag reference (the common ones)

### 5.1 `<Labels>` — text spans / generic spans

```xml
<Labels name="lbl" toName="t">
  <Label value="Person" background="red"/>
  <Label value="Organization" background="blue"/>
</Labels>
```

Per-`Label` attributes: `value` (required), `background` (CSS color),
`hotkey`, `hint`, `showAlias`, `alias`.

Per-`Labels` attributes: `choice` (`single` / `multiple`), `showInline`
(render horizontally), `opacity`, `fillColor`, `strokeColor`.

For images use `<RectangleLabels>`, `<PolygonLabels>`,
`<KeyPointLabels>`, `<BrushLabels>`, `<EllipseLabels>` — same nesting
rules, different region type.

### 5.2 `<Choices>` — classification

```xml
<Choices name="sentiment" toName="t" choice="single" required="true">
  <Choice value="Positive"/>
  <Choice value="Negative"/>
  <Choice value="Neutral"/>
</Choices>
```

Attributes: `choice` (`single` / `multiple`), `showInline`, `required`,
`requiredMessage`, `perRegion`, `perItem`, `visibleWhen` (and
companions).

`<Choice>` attributes: `value` (required), `alias`, `hint`, `style`.

### 5.3 `<Taxonomy>` — hierarchical classification

```xml
<Taxonomy name="cat" toName="t">
  <Choice value="Animal">
    <Choice value="Mammal">
      <Choice value="Primate"/>
      <Choice value="Carnivora"/>
    </Choice>
    <Choice value="Bird"/>
  </Choice>
  <Choice value="Plant"/>
</Taxonomy>
```

The **only** tag where `<Choice>` may nest. Attributes:
`leafsOnly` (force leaf selection), `pathSeparator`, `maxUsages`,
`maxWidth`, `showFullPath`, `placeholder`.

**Convention:** if the user wants a "dropdown" of categorical
options, prefer `<Taxonomy>` over `<Choices>` — Taxonomy renders as a
search-friendly tree picker, Choices renders as radio/checkbox
buttons.

### 5.4 `<TextArea>` — free-text input

```xml
<TextArea name="note" toName="t" rows="3"
          placeholder="Reasoning..." editable="true"/>
```

| Attribute           | Type                  | Default | Notes                                                          |
| ------------------- | --------------------- | ------- | -------------------------------------------------------------- |
| `name` / `toName`   |                       |         | required                                                       |
| `value`             | string                | —       | Pre-filled default (submittable)                               |
| `placeholder`       | string                | —       | Placeholder hint (not submittable)                             |
| `maxSubmissions`    | string                | —       | Max number of answers                                          |
| `editable`          | bool                  | false   | Show edit icon after submission                                |
| `transcription`     | bool                  | false   | With `editable=true`, stays editable                           |
| `skipDuplicates`    | bool                  | false   | Warn on duplicates                                             |
| `displayMode`       | `tag` / `region-list` | `tag`   | `region-list` puts an input next to each region                |
| `rows`              | number                | 1       | If 1, Enter submits; if >1, Shift+Enter or Add button submits  |
| `required`          | bool                  | false   |                                                                |
| `requiredMessage`   | string                | —       |                                                                |
| `showSubmitButton`  | bool                  | —       | Defaults: hidden when rows=1, visible when rows>1              |
| `perRegion`         | bool                  | —       |                                                                |
| `perItem`           | bool                  | —       |                                                                |

### 5.5 `<Rating>` — 1-N star rating

```xml
<Rating name="rating" toName="t" maxRating="5" icon="star"
        size="medium" defaultValue="0" required="false"/>
```

Attributes: `maxRating`, `icon` (`star` / `heart` / `fire` / `smile`),
`size` (`small`/`medium`/`large`), `defaultValue`, `required`,
`requiredMessage`, `perRegion`, `perItem`.

### 5.6 `<Number>` — numeric input

```xml
<Number name="depth" toName="img" min="0" max="100" step="0.1"
        defaultValue="0" perRegion="true"/>
```

Attributes: `min`, `max`, `step`, `defaultValue`, `required`,
`requiredMessage`, `perRegion`, `perItem`.

### 5.7 `<DateTime>` — date / time / datetime input

```xml
<DateTime name="when" toName="t" only="date"/>
```

`only`: `date` / `time` / `datetime` / `month` / `year`.

### 5.8 `<Pairwise>` — compare two objects

```xml
<View>
  <Text name="a" value="$textA"/>
  <Text name="b" value="$textB"/>
  <Pairwise name="pw" toName="a,b" selectionStyle="background-color: lightblue"/>
</View>
```

The **only** tag with two `toName` values.

### 5.9 `<Relations>` — relations between regions

```xml
<Relations>
  <Relation value="causes"/>
  <Relation value="is_part_of"/>
</Relations>
```

Used with any region-producing labels (Labels, RectangleLabels, etc.).

### 5.10 `<Filter>` — search box over labels

```xml
<View>
  <Text name="t" value="$text"/>
  <Filter name="f" toName="lbl" hotkey="shift+f" minlength="1"/>
  <Labels name="lbl" toName="t">
    <Label value="Person"/>
    <Label value="Organization"/>
    <Label value="Location"/>
    <!-- ...add more labels as needed... -->
  </Labels>
</View>
```

Note: `<Filter>` is unusual — its `toName` points at the `<Labels>`
control it filters, not at the object tag. The validator treats this
as a control-→-control reference and would normally flag it, but
`<Filter>` is allowlisted because that's how it's documented to work.

Indispensable when you have more than ~15-20 labels.

---

## 6. Layout & styling

### 6.1 Headers

```xml
<Header value="Step 1: Classify the sentiment" size="3"/>
```

`size`: 1-6 (HTML h1-h6). Inline `style` is allowed on `<Header>`.

### 6.2 View grouping

```xml
<View>
  <Text name="t" value="$text"/>
  <View style="display: flex; gap: 1em">
    <View style="flex: 1">
      <Header value="Sentiment" size="4"/>
      <Choices name="sentiment" toName="t" choice="single">
        <Choice value="Positive"/>
        <Choice value="Negative"/>
      </Choices>
    </View>
    <View style="flex: 1">
      <Header value="Topic" size="4"/>
      <Choices name="topic" toName="t" choice="multiple">
        <Choice value="Billing"/>
        <Choice value="Bug"/>
      </Choices>
    </View>
  </View>
</View>
```

### 6.3 Custom CSS

```xml
<View>
  <Style>
    .danger { color: red; font-weight: bold; }
  </Style>
  <View className="danger">
    <Text name="t" value="$text"/>
  </View>
</View>
```

### 6.4 The Collapse / Tabs widgets

For configs with many controls, organize with `<Collapse>` /
`<Panel>` and `<Tabs>` / `<Tab>` for switch-style grouping.

---

## 7. Sample task examples (use these placeholder URLs when generating samples)

These URLs are real Label Studio sample assets. Use them for sample
tasks so the user can immediately test the config locally.

```python
SAMPLES = {
    "Text":         "To have faith is to trust yourself to the water",
    "TextUrl":      "https://htx-pub.s3.amazonaws.com/example.txt",
    "HyperText":    "<div>Hello, world!</div>",
    "HyperTextUrl": "/static/samples/hypertext.html",
    "Image":        "/static/samples/sample.jpg",
    "Audio":        "/static/samples/game.wav",
    "Video":        "/static/samples/opossum_snow.mp4",
    "PDF":          "/static/samples/sample.pdf",
    "OCR":          "https://htx-pub.s3.amazonaws.com/demo/ocr/example.jpg",
    "Paragraphs":   [{"author": "Alice", "text": "Hi, Bob."},
                     {"author": "Bob",   "text": "Hello, Alice!"}],
    "Table":        {"Card number": 18799210, "First name": "Max", "Last name": "Nobel"},
    "DynamicLabels": [
        {"value": "DynamicLabel1", "background": "#ff0000"},
        {"value": "DynamicLabel2", "background": "#0000ff"},
    ],
    "DynamicChoices": [
        {"value": "DynamicChoice1"},
        {"value": "DynamicChoice2"},
    ],
}
```

For time series, the LS dev server provides a generator endpoint:

```
/samples/time-series.csv?time=time&values=channel1,channel2,channel3&sep=,&tf=%Y-%m-%d+%H:%M:%S
```

---

## 8. Ready-to-use templates

Each template is correct, validated, and copy-paste ready. Adapt the
labels / colors / dataset keys to the user's case rather than starting
from scratch.

### 8.1 Text sentiment classification

```xml
<View>
  <Text name="text" value="$text"/>
  <Choices name="sentiment" toName="text" choice="single" required="true"
           requiredMessage="Pick a sentiment before submitting.">
    <Choice value="Positive"/>
    <Choice value="Neutral"/>
    <Choice value="Negative"/>
  </Choices>
</View>
```

Sample task: `{"data": {"text": "Opossums are great"}}`

### 8.2 Named entity recognition (NER)

```xml
<View>
  <Labels name="entities" toName="text">
    <Label value="Person" background="#ff7f50"/>
    <Label value="Organization" background="#1f77b4"/>
    <Label value="Location" background="#2ca02c"/>
    <Label value="Date" background="#9467bd"/>
  </Labels>
  <Text name="text" value="$text" granularity="word"/>
</View>
```

Sample task: `{"data": {"text": "Alice met Bob at OpenAI in San Francisco on Tuesday."}}`

### 8.3 Multi-label text classification

```xml
<View>
  <Text name="text" value="$text"/>
  <Choices name="topics" toName="text" choice="multiple">
    <Choice value="Billing"/>
    <Choice value="Bug"/>
    <Choice value="Feature request"/>
    <Choice value="Account"/>
    <Choice value="Other"/>
  </Choices>
</View>
```

### 8.4 Image classification

```xml
<View>
  <Image name="image" value="$image"/>
  <Choices name="label" toName="image" choice="single" required="true">
    <Choice value="Cat"/>
    <Choice value="Dog"/>
    <Choice value="Other"/>
  </Choices>
</View>
```

### 8.5 Image bounding-box object detection

```xml
<View>
  <Image name="image" value="$image" zoomControl="true"/>
  <RectangleLabels name="bbox" toName="image">
    <Label value="Person" background="#ff7f50"/>
    <Label value="Vehicle" background="#1f77b4"/>
    <Label value="Animal" background="#2ca02c"/>
  </RectangleLabels>
</View>
```

### 8.6 Image polygon segmentation

```xml
<View>
  <Image name="image" value="$image" zoomControl="true"/>
  <PolygonLabels name="poly" toName="image" strokeWidth="2">
    <Label value="Road" background="#888"/>
    <Label value="Sky" background="#87ceeb"/>
    <Label value="Building" background="#a0522d"/>
  </PolygonLabels>
</View>
```

### 8.7 Image keypoints with per-region measurements

```xml
<View>
  <Image name="image" value="$image"/>
  <KeyPointLabels name="kp" toName="image">
    <Label value="Feature point" background="red"/>
  </KeyPointLabels>
  <View visibleWhen="region-selected">
    <Header value="Measurement"/>
    <Number name="depth" toName="image" perRegion="true" min="0" max="100"/>
  </View>
</View>
```

### 8.8 OCR (text on image — bounding boxes + transcription)

```xml
<View>
  <Image name="image" value="$ocr"/>
  <Labels name="label" toName="image">
    <Label value="Text" background="#1f77b4"/>
    <Label value="Handwriting" background="#ff7f50"/>
  </Labels>
  <Rectangle name="bbox" toName="image"/>
  <TextArea name="transcription" toName="image"
            editable="true" perRegion="true"
            placeholder="Transcribe this region"
            displayMode="region-list"/>
</View>
```

### 8.9 Audio transcription / speech-to-text

```xml
<View>
  <Labels name="labels" toName="audio">
    <Label value="Speech" background="#1f77b4"/>
    <Label value="Silence" background="#888"/>
    <Label value="Noise" background="#d62728"/>
  </Labels>
  <Audio name="audio" value="$audio"/>
  <TextArea name="transcription" toName="audio"
            editable="true" perRegion="true"
            placeholder="Transcribe this segment"
            displayMode="region-list"/>
</View>
```

### 8.10 Audio classification (no regions)

```xml
<View>
  <Audio name="audio" value="$audio"/>
  <Choices name="genre" toName="audio" choice="single">
    <Choice value="Music"/>
    <Choice value="Speech"/>
    <Choice value="Silence"/>
    <Choice value="Noise"/>
  </Choices>
</View>
```

### 8.11 Video object tracking

```xml
<View>
  <Video name="video" value="$video"/>
  <VideoRectangle name="box" toName="video"/>
  <Labels name="label" toName="video">
    <Label value="Person" background="#ff7f50"/>
    <Label value="Vehicle" background="#1f77b4"/>
  </Labels>
</View>
```

### 8.12 PDF document classification + extraction

```xml
<View>
  <HyperText name="pdf" value="$pdf" inline="true"/>
  <Choices name="doc_type" toName="pdf" choice="single">
    <Choice value="Invoice"/>
    <Choice value="Contract"/>
    <Choice value="Receipt"/>
  </Choices>
  <TextArea name="summary" toName="pdf" rows="4"
            placeholder="One-paragraph summary"/>
</View>
```

(For real PDF rendering pass an HTML embed in `$pdf`:
`"<embed src='https://...pdf' width='100%' height='600px'/>"`.)

### 8.13 LLM response rating (RLHF-style)

```xml
<View>
  <Header value="Prompt"/>
  <Text name="prompt" value="$prompt"/>
  <Header value="Response"/>
  <Text name="response" value="$response"/>

  <Rating name="quality" toName="response" maxRating="5" icon="star"
          required="true" requiredMessage="Please rate quality."/>
  <Choices name="issues" toName="response" choice="multiple">
    <Choice value="Hallucination"/>
    <Choice value="Refusal"/>
    <Choice value="Off-topic"/>
    <Choice value="Toxic"/>
    <Choice value="Formatting"/>
  </Choices>
  <TextArea name="rationale" toName="response" rows="3"
            placeholder="Why this rating?" required="true"/>
</View>
```

### 8.14 Pairwise comparison (A vs B)

```xml
<View>
  <Header value="Which response is better?"/>
  <Text name="prompt" value="$prompt"/>
  <View style="display: flex; gap: 1em">
    <View style="flex: 1">
      <Header value="Response A" size="4"/>
      <Text name="responseA" value="$responseA"/>
    </View>
    <View style="flex: 1">
      <Header value="Response B" size="4"/>
      <Text name="responseB" value="$responseB"/>
    </View>
  </View>
  <Pairwise name="pw" toName="responseA,responseB"/>
</View>
```

### 8.15 Time series anomaly labeling

```xml
<View>
  <TimeSeries name="ts" value="$csv" valueType="url"
              timeColumn="time" sep=",">
    <Channel column="channel1" displayFormat=",.2f" strokeColor="#1f77b4"/>
    <Channel column="channel2" displayFormat=",.2f" strokeColor="#ff7f0e"/>
  </TimeSeries>
  <TimeSeriesLabels name="anomaly" toName="ts">
    <Label value="Anomaly" background="#d62728"/>
    <Label value="Maintenance window" background="#888"/>
  </TimeSeriesLabels>
</View>
```

### 8.16 Dialogue / chat turn-by-turn labeling

```xml
<View>
  <Paragraphs name="d" value="$dialogue" nameKey="author" textKey="text"
              layout="dialogue"/>
  <ParagraphLabels name="intent" toName="d">
    <Label value="Question"/>
    <Label value="Answer"/>
    <Label value="Greeting"/>
    <Label value="Closing"/>
  </ParagraphLabels>
</View>
```

### 8.17 Conditional follow-up (`visibleWhen`)

```xml
<View>
  <Text name="text" value="$text"/>
  <Choices name="quality" toName="text" choice="single">
    <Choice value="Good"/>
    <Choice value="Bad"/>
  </Choices>
  <View visibleWhen="choice-selected" whenTagName="quality" whenChoiceValue="Bad">
    <TextArea name="reason" toName="text"
              visibleWhen="choice-selected" whenTagName="quality" whenChoiceValue="Bad"
              rows="3" placeholder="What was wrong?"/>
  </View>
</View>
```

### 8.18 Multi-image labeling (`valueList` + `perItem`)

```xml
<View>
  <Image name="imgs" valueList="$images"/>
  <RectangleLabels name="bbox" toName="imgs" showInline="true">
    <Label value="Cat" background="red"/>
    <Label value="Dog" background="blue"/>
  </RectangleLabels>
  <Choices name="quality" toName="imgs" perItem="true">
    <Choice value="Good"/>
    <Choice value="Blurry"/>
  </Choices>
</View>
```

Sample task:

```json
{"data": {"images": ["https://.../a.jpg", "https://.../b.jpg"]}}
```

---

## 9. Common authoring mistakes (and how to avoid them)

1. **`toName` pointing at another control tag.** Always points at an
   **object** tag's `name`. Re-check this on every control tag.
2. **Duplicate `name` values.** Every tag's `name` must be unique. Use
   semantic names (`sentiment`, not `c1`).
3. **`value` missing the `$`.** `value="text"` is a literal string;
   `value="$text"` is a dataset variable.
4. **Mismatch between `value="$key"` and task JSON's `data.key`.** They
   must match. The validator can't catch this without the task JSON,
   so always show the user the task JSON shape alongside the config.
5. **`<Label>` inside `<Label>`.** Common when copying from Taxonomy.
   `<Labels>` allows only one level of `<Label>`.
6. **Forgetting `visibleWhen` on the inner control.** Without it, the
   hidden control still serializes an answer. Put `visibleWhen` on
   both the wrapping `<View>` and the inner control tag.
7. **Using `style=` / `className=` on a non-View tag.** Wrap in a
   `<View>` instead.
8. **Using `<AudioPlus>` or `<Repeater>`.** Deprecated. Use `<Audio>`
   and `<Image valueList>` respectively.
9. **Inventing attributes.** If you can't point at a documented
   attribute, don't emit it.
10. **Including `model_*` attributes "just in case."** Only when an ML
    backend is wired up.

---

## 10. Importing tasks into the project

Once the config is approved and pushed, the user needs to import tasks.
Three options, ranked by robustness:

1. **JSON via SDK** — `ls.projects.import_tasks(id=..., request=[...])`.
   Each task is a dict with a `data` key matching the config's `$keys`.
2. **CSV / TSV** — column names = `$keys`. Good for tabular data and
   text classification.
3. **Cloud storage (S3 / GCS / Azure)** — best for images / audio /
   video. Configure via Project Settings → Cloud Storage in the UI, or
   via SDK (`ls.import_storage.s3.create(...)`).

The skill prints the project URL and a one-line "import next" hint on
success — it does **not** auto-import data. That's a separate user
decision.
