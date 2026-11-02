# Launch and submission readiness, 2026-11-01

Hackathon window: Oct 26 to Nov 4, 2026. Every commit on main is inside it (first commit
Oct 27, latest Nov 1). Submission deadline per the listings seen: Nov 4 (verify on the official
Devpost page; the listing we found said Nov 5, 6:30 AM IST, which is Nov 4 evening in Dallas).

## Component audit

| Component | State | Evidence |
|---|---|---|
| Web app, 21 features | Ready | docs/verification-2026-11-01.md: 19 at grade A against the running server, Corner mode unverified, highlight reel unbuilt |
| Safety reports | Ready | synthetic grooming frame reported on an automatic tick; normal frame produced nothing; /admin/incidents shows it |
| Overlay page and layout | Ready | highlight boxes, task list, callout, movable panels, hide key; verified in the browser pane and on the desktop |
| PC overlay app (desktop/) | Ready, Windows only tested | transparent click-through window over the whole 1920x1080 desktop at 125 percent scaling; Ctrl+Shift+O |
| VR guide (docs/vr.md) | Ready | Link plus XSOverlay, OVR Toolkit or Desktop+; standalone Quest limits stated |
| Consent gate and terms | Ready for a pilot | code-enforced; terms are plain drafts, not lawyer-reviewed |
| CLI (python -m coach) | Ready | health, ingest, clips, transcribe, coach, play; health runs offline |
| Tests | Ready | 172 pass, no skips, ffmpeg required (scripts/pre-merge.sh exit 0) |
| Gates | Ready | scripts/pre-merge.sh, scripts/predeploy.sh, scripts/check-no-dashes.sh; no GitHub Actions |
| House rules | Ready | no em dashes in tracked text; workflow removed |
| Docker image | Not verified today | local Docker daemon stalled during the build; Render builds the image itself; the only change since the last good image is COPY scripts |
| Hosted demo | Missing | render.yaml is ready (preDeployCommand, disk, health check); no Render service exists yet |
| Demo video | Missing | script in docs/submission.md; media/ is empty |
| Submission text | Drafted | docs/submission.md |

## Owner actions before submitting

1. Create the Render service: New, Blueprint, pick agamble33/coach-sidekick, main. Set
   META_API_KEY (the hackathon key) in the dashboard; leave META_BASE_URL as in render.yaml.
   Optional: COACH_ADMIN_TOKEN (protects /admin/incidents), COACH_ALERT_WEBHOOK. Wait for the
   deploy, open /api/health, then run the judges' walkthrough once on the hosted URL.
2. Record the demo video from the script in docs/submission.md (about 2.5 minutes) and upload it.
3. Fill the submission form from docs/submission.md with the repo, hosted demo and video links.
4. Optional but wise before real players: a lawyer pass on web/static/terms.html.

## Verdict

Code and docs: ready to submit. Blocking items are the hosted demo and the video, both owner
steps. Nothing on main is known broken.
