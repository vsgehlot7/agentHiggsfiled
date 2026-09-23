# Verification record

Verification record updated on 2026-09-22. Local checks and recovery of a user-submitted live video passed. The source is published on GitHub with the submission limitation below.

## Passed

- 23 unit and regression tests, including duplicate prevention, concurrent state locking, changed inputs, uncertain submissions, stale/wrong Unlimited evidence, Excel error cells, path containment, video-container checks, CSV formula escaping, case-insensitive output collisions and blocked-job recovery while paused.
- Clean-checkout simulation using only the files intended for GitHub. Copying the disabled example to `prompts.xlsx` produced a valid empty queue.
- Check, Pause and Resume launchers executed successfully in that isolated checkout, including Resume before a state directory existed.
- Isolated Git staging included source, tests, documentation, launchers, the disabled example workbook and empty input/output folder markers. It excluded the working workbook, media, state, status report, environment files, logs and browser authentication fixtures.
- Signed-in Higgsfield page inspection showed Kling 2.5 Turbo, 5s, 720p, Unlimited mode enabled and Generate Unlimited. The website draft inspection returned `price.mode = unlimited` and `price.effective_credits = 0`.
- After the user submitted the prepared demo, the agent matched the completed result's exact prompt and input asset to the queue record. The website showed Kling 2.5 Turbo, 1280x720 and five seconds.
- The exact result was downloaded through the browser, saved exclusively in `videos/`, checked with `ffprobe` and decoded with `ffmpeg`: H.264 MP4, 1280x720, 24 fps, 5.041667 seconds, 1,124,351 bytes. Sampled frames show the ball moving right across the same blue tabletop, without added text. The durable ledger and `status.csv` now record completion; no second generation was submitted.

## Changes from review

- Reject actual Excel error cells in enabled rows while preserving literal prompt text that resembles an error.
- Exclude the working prompt workbook and common credential/session files from Git. Ship a disabled example workbook under `templates/`.
- Remove personal absolute paths and fixed browser IDs from the published instructions.
- Make Resume create its state directory when needed.
- Document the local scheduler and the Codex browser dependency for a new checkout.
- Keep blocked jobs active so another job cannot overwrite a draft awaiting user action. Regression tests cover blocked-to-submitted-to-completed recovery and direct completion while paused, with receipt/output validation and duplicate prevention.

## Submission limit

The website's `submit_video_generation` action returned `status = rejected` and `code = form_unavailable`, without a generation receipt. The agent did not retry and marked the local job blocked. The user then clicked Generate Unlimited and reported completion. Recovery, download and local verification of that result passed; fully unattended submission remains unverified. This test does not establish that website confirmation gates can be automated.

The point-in-time Unlimited observation does not replace the fresh checks required before each submission. The browser agent must stop if a paid charge, mandatory confirmation, expired session or unknown submission outcome appears.

The Python helper handles local validation and bookkeeping. Codex performs browser interaction, and the recurring schedule is stored locally in Codex rather than in this repository.
