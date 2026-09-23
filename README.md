# Higgsfield video queue

A Codex-assisted browser workflow with a local Excel queue and durable job ledger. The Python helper validates inputs and records progress. It does not generate videos by itself. Browser execution requires Codex with computer-use access and a signed-in Higgsfield account with the matching Unlimited entitlement.

See [VERIFICATION.md](VERIFICATION.md) for tested behavior and the remaining submission limitation.

Put your images in `images/`. Open `prompts.xlsx`, enter one row per video in the Queue sheet, and save the workbook. Set `enabled` to `YES` when that row is ready.

| Column | What to enter |
| --- | --- |
| enabled | YES to queue; NO or blank to skip |
| job_id | A unique name such as scene_001. Letters, digits, underscores and hyphens only. |
| image | Exact filename inside images/, for example scene_001.png |
| prompt | The complete motion/video prompt for that image |

The example row is disabled. Replace it or add your own rows. PNG, JPG, JPEG and WebP are accepted. Save Excel changes before expecting them to be picked up. Completed results go in `videos/`; progress is in `status.csv`.

The agent uses Kling 2.5 Turbo, 5 seconds and 720p. It submits only when the website visibly confirms Unlimited mode. It stops on credit pricing, missing Unlimited access, ambiguous submission results or mandatory user confirmation. It does not use Higgsfield's paid API or spend credits to accelerate a queue.

## Running

The original local setup has a recurring Codex task that checks this folder every 10 minutes. That schedule is stored in Codex, outside this repository, and is not installed by cloning it. Keep the computer awake and Codex running, and sign in to your existing Higgsfield account in the automation browser. Existing Chrome login does not automatically sign in that separate browser. Generation may take longer than one check interval.

For an immediate run, tell this Codex task: “Process my Higgsfield queue now.” The full execution instructions are in `AGENT.md`. The Python helper alone validates and tracks jobs; Codex performs the browser work.

Double-click `Pause Queue.command` to stop new submissions locally. Double-click `Resume Queue.command` to remove that local pause; the next scheduled check will resume. These files do not change the Codex schedule. Already submitted videos continue on Higgsfield.

Double-click `Check Queue.command` to validate your saved rows without generating anything. It lists missing files, duplicate IDs and other input errors.

## New checkout and GitHub

Use Python 3.9 or newer on macOS or Linux. The helper uses the standard library only; no package installation, API key or browser credentials belong in this repository. The `.command` launchers require macOS and zsh. Windows is not supported because the queue lock uses `fcntl`.

Create your private working workbook from the disabled example:

```sh
cp -n templates/prompts.example.xlsx prompts.xlsx
python3 queue_agent.py scan
python3 -m unittest discover -s tests -v
```

Keep the example workbook disabled. Use the root `prompts.xlsx` for actual jobs. The working workbook, images, videos, state, status report, environment files and browser authentication folder are ignored by Git. The source, tests, instructions, launchers and `templates/prompts.example.xlsx` are intended for GitHub.

After cloning, open this folder as a local Codex task and ask it to follow `AGENT.md`. Create a recurring task in Codex if you want scheduled processing; the repository contains no background service or GitHub-hosted video runner. Review staged files before pushing. Git ignore rules do not remove files already committed to a repository.

## Credits and operating limits

Website Unlimited access and API billing differ. The agent checks the actual website before every submission and has no paid fallback. This prevents intentional credit spending; it cannot guarantee Higgsfield's billing behavior if the service displays incorrect information. Codex runs still use your Codex allowance.

Duplicate image/prompt pairs and previously claimed jobs are not automatically retried. A blocked job holds the queue so a later job cannot replace its browser draft while the user resolves it. Do not delete `state/` to start over: that removes duplicate protection. If a job is blocked or interrupted, ask this task to inspect and recover it.

All 23 local tests pass. A live demo was prepared with Kling 2.5 Turbo, 5s, 720p and Unlimited mode at a displayed effective cost of 0 credits. After the website rejected the agent's submission request with `form_unavailable`, the user clicked Generate Unlimited. The agent matched the completed result to the exact prompt and input image, downloaded and decoded the 1280x720, 5.04-second MP4, and marked the original job completed without regeneration. Fully unattended submission remains unverified; website confirmation gates still require the user. Unlimited eligibility and effective cost must be checked again before every submission. See [VERIFICATION.md](VERIFICATION.md) for the verification record.

Sources: [Higgsfield API and website billing](https://higgsfield.ai/creator-hub/help-center/integrations/what-is-the-higgsfield-api), [local scheduled tasks](https://learn.chatgpt.com/docs/automations).
