# PixelPitch — Higgsfield Image Generation Agent

Reusable automation that generates images on [higgsfield.ai](https://higgsfield.ai/ai/image)
by reading prompts from a Markdown file and driving Chrome.

The agent (named **PixelPitch** by default) automatically sets the **model**,
**quality**, **aspect ratio**, and **Unlimited** toggle before generating each prompt.

## Files

| File | Purpose |
|------|---------|
| `higgsfield_agent.sh` | The reusable agent script |
| `image_prompts.md` | Your prompts (edit this) |

## One-Time Setup

1. **Open Chrome** with a tab on `https://higgsfield.ai/ai/image` and **log in**.
2. Enable AppleScript control:
   **Chrome menu → View → Developer → "Allow JavaScript from Apple Events"** (checked ✓)
3. Grant Accessibility permission to your terminal:
   **System Settings → Privacy & Security → Accessibility** → enable Terminal (or iTerm).

> The agent sets model / quality / aspect / Unlimited for you — you no longer
> need to configure them on the page by hand.

## Configuration

Edit the **CONFIG block** near the top of `higgsfield_agent.sh`, or pass values as
environment variables:

| Setting | Default | Values | Env var |
|---------|---------|--------|---------|
| Agent name | `PixelPitch` | any | `AGENT_NAME` |
| Model | `Nano Banana Pro` | any model name shown on the site | `MODEL` |
| Quality | `1K` | `1K`, `2K`, `4K` | `QUALITY` |
| Aspect ratio | `9:16` | e.g. `9:16`, `16:9`, `1:1` | `ASPECT` |
| Unlimited | `on` | `on`, `off` | `UNLIMITED` |

Example — generate 4K square images with a different model:

```bash
MODEL="GPT Image 2" QUALITY=4K ASPECT=1:1 ./higgsfield_agent.sh image_prompts.md 1
```

## Usage

```bash
cd /Users/vishal/Documents/Claude/cowork/cricket

# Run Batch 1 (prompts 1-8) from image_prompts.md
./higgsfield_agent.sh

# Run Batch 2 (prompts 9-16)
./higgsfield_agent.sh image_prompts.md 2

# Run ALL prompts with a 60s wait between each
./higgsfield_agent.sh image_prompts.md all 60

# Use a different prompts file
./higgsfield_agent.sh my_other_prompts.md 1
```

### Arguments

```
./higgsfield_agent.sh [PROMPTS_FILE] [BATCH] [WAIT_SECONDS]
```

- **PROMPTS_FILE** — path to the `.md` file (default: `image_prompts.md`)
- **BATCH** — `1`, `2`, … (8 prompts each) or `all` (default: `1`)
- **WAIT_SECONDS** — wait after each generation (default: `50`)

## Prompt File Format

Just a numbered list. Headings are ignored — only `N. ` lines are read.

```markdown
# My Prompts

## Batch 1
1. First prompt text, descriptive, photorealistic
2. Second prompt text, cinematic lighting

## Batch 2
9. Ninth prompt text...
```

> Tip: Keep each prompt on a **single line**. Multi-line prompts are not parsed.

## How It Works

1. Finds the open Chrome tab matching `higgsfield.ai/ai/image`.
2. Applies settings once per run: selects the **model** (from the model dialog),
   **quality** and **aspect ratio** (`button[role=option]` dropdowns), and ensures
   the **Unlimited** switch matches your config.
3. For each prompt: focuses the prompt box (a Lexical rich-text editor) and types
   using **System Events keystrokes** — required because the editor ignores
   programmatic DOM changes; it only reacts to real keyboard input.
4. Clicks the **Unlimited** generate button.
5. Waits, then repeats for the next prompt.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `"Prompt is required"` on page | Editor didn't receive keystrokes → check Accessibility permission |
| `NO_TAB` error | Open a Chrome tab on higgsfield.ai/ai/image |
| `osascript not allowed to send keystrokes` | Grant Accessibility permission to your terminal |
| JS execution error | Enable "Allow JavaScript from Apple Events" in Chrome |
| Images cut off / incomplete | Increase `WAIT_SECONDS` (e.g. 60–90) |
| `NOT_FOUND` for model/quality/aspect | The name must match the site exactly (e.g. `2K`, not `2k`); the model name must match the label in the model picker |
