# Higgsfield Image Generation Agent

Reusable automation that generates images on [higgsfield.ai](https://higgsfield.ai/ai/image)
by reading prompts from a Markdown file and driving Chrome.

## Files

| File | Purpose |
|------|---------|
| `higgsfield_agent.sh` | The reusable agent script |
| `image_prompts.md` | Your prompts (edit this) |

## One-Time Setup

1. **Open Chrome** with a tab on `https://higgsfield.ai/ai/image` and **log in**.
2. On the page, set your options once: **model**, **9:16** ratio, **Unlimited** toggle ON.
3. Enable AppleScript control:
   **Chrome menu → View → Developer → "Allow JavaScript from Apple Events"** (checked ✓)
4. Grant Accessibility permission to your terminal:
   **System Settings → Privacy & Security → Accessibility** → enable Terminal (or iTerm).

## Usage

```bash
git clone https://github.com/vsgehlot7/agentHiggsfiled.git
cd agentHiggsfiled

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
2. Focuses the prompt box (a Lexical rich-text editor).
3. Types the prompt using **System Events keystrokes** — this is required because
   the editor ignores programmatic DOM changes; it only reacts to real keyboard input.
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
