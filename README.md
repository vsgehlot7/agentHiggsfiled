# PixelPitch — Higgsfield Image Generation Agent

Generates images on [higgsfield.ai](https://higgsfield.ai/ai/image) from prompts in
Markdown files. It sets the **model**, **quality**, **aspect ratio**, and **Unlimited**
toggle, then types each prompt and generates.

There are **two modes**:

| Mode | Runs in background? | Steals keyboard? | How |
|------|--------------------|------------------|-----|
| **CDP (recommended)** | ✅ Yes | ❌ No | Drives a dedicated debug Chrome via DevTools Protocol with *trusted* input |
| Keystroke (legacy) | ❌ No | ✅ Yes | Uses System Events keystrokes in your main Chrome |

> **Why CDP?** The prompt box is a *Lexical* editor that only accepts trusted input.
> Synthetic JS events can't clear it; OS keystrokes work but take over your keyboard.
> Chrome's DevTools Protocol sends *trusted* events to a **background** tab, so the
> agent runs fully in the background while you keep working.

## Files

| File | Purpose |
|------|---------|
| `run_batch.sh` | One-command runner (CDP, foreground or background) |
| `cdp_agent.js` | The CDP agent (Node) |
| `start_chrome_debug.sh` | Launches the dedicated debug Chrome |
| `batches/batch_1.md`, `batch_2.md`, … | **One MD file per batch of 8 prompts** |
| `higgsfield_agent.sh` | Legacy keystroke agent (foreground only) |

## One-Time Setup

1. **Node 22+** is required (built-in WebSocket). The runner auto-picks it from nvm.
2. First run launches a **dedicated debug Chrome** (separate profile in
   `~/.chrome-pixelpitch`) — your **main Chrome and its tabs are never touched**.
3. In that debug window, **log into Higgsfield once** and leave it open.

That's it. No Chrome menu flags, no Accessibility permission needed for CDP mode.

## Usage

```bash
cd /Users/vishal/Documents/Claude/cowork/cricket

# Run one batch in the foreground (you watch the log)
./run_batch.sh batches/batch_1.md

# Run one batch fully in the BACKGROUND (keep working!)
./run_batch.sh batches/batch_2.md --bg
#   -> logs to batches/batch_2.log ; watch with: tail -f batches/batch_2.log
```

**One MD file = one batch.** To run the next 8, just point at the next file:
```bash
./run_batch.sh batches/batch_1.md --bg   # first 8
./run_batch.sh batches/batch_2.md --bg   # next 8
```

## Configuration

Set via environment variables (or edit defaults in `run_batch.sh`):

| Setting | Default | Values | Env var |
|---------|---------|--------|---------|
| Model | `Nano Banana Pro` | any model on the site | `MODEL` |
| Quality | `2K` | `1K`, `2K`, `4K` | `QUALITY` |
| Aspect ratio | `9:16` | `9:16`, `16:9`, `1:1`, … | `ASPECT` |
| Unlimited | `on` | `on`, `off` | `UNLIMITED` |
| Wait per image | `50` | seconds | `WAIT` |
| Agent name | `PixelPitch` | any | `AGENT_NAME` |

```bash
# 4K square images, next batch, background
MODEL="Nano Banana Pro" QUALITY=4K ASPECT=1:1 ./run_batch.sh batches/batch_2.md --bg
```

## Prompt File Format

A numbered list, one prompt per line. Headings are ignored.

```markdown
# Batch 1 (9:16)
1. First prompt, descriptive, photorealistic
2. Second prompt, cinematic lighting
...
8. Eighth prompt
```

## How CDP Mode Works

1. `start_chrome_debug.sh` launches Chrome with `--remote-debugging-port=9222` and a
   dedicated profile (Chrome 136+ blocks debugging on the default profile).
2. `cdp_agent.js` connects to the Higgsfield tab over the DevTools WebSocket.
3. Applies settings via `Runtime.evaluate` (button clicks).
4. Per prompt: focuses the editor, sends **trusted** `Cmd+A` + `Backspace` to clear,
   then `Input.insertText` to type — Lexical accepts these because they're trusted.
5. Clicks generate, waits, repeats. All against a **background** tab.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Cannot reach Chrome debug port` | Run `./start_chrome_debug.sh` (or just use `run_batch.sh`, which does it) |
| Debug window asks to log in | Log into Higgsfield once in the debug Chrome window |
| `No Chrome tab on …/ai/image` | Open `higgsfield.ai/ai/image` in the debug window |
| `NOT_FOUND` for quality/aspect | Value must match exactly (`2K` not `2k`; `9:16` not `9-16`) |
| Images incomplete | Increase `WAIT` (e.g. `WAIT=70`) |
| Node error about WebSocket | Ensure Node 22+ is installed (nvm) |
