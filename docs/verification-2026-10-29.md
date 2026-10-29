# Verification log

Real runs of `scripts/windows_check.cmd` on a Windows 10 PC against the live Meta Model API. Nothing here is mocked.

```
=== muse-replay Windows check Thu 10/29/2026 13:31:12.41
repo: C:\Users\agamb\Code\muse-replay
using: python
--- versions
Python 3.10.2
ffmpeg version 9.0.2-full_build-www.gyan.dev Copyright (c) 2000-2026 the FFmpeg developers
--- pip install
--- pytest
........................................................................ [ 47%]
........................................................................ [ 95%]
.......                                                                  [100%]
151 passed in 98.99s (0:01:38)
--- live check
muse-replay 0.0.1
  meta_model_api: configured
  baseten_muse_spark_open: missing
models: 9 available, spark=True, asr=True
coach: All good, shake it off. Lets split up next round so we stop getting traded in mid.
tokens: in=130 out=533 reasoning=504
spoke via: sapi
  [tool] look({"question":"What is happening on screen?","t":15.0}) -> The screen shows a color test pattern with vertical bars and the number 5 and no gameplay is visible. There is no advant
agent: Got color bars with a 5, no gameplay yet. Hang tight till the feed is back.  (rounds=2, tokens in=2569 out=393)
  [tool] find_moments({"top":3}) -> {"events": 3, "moments": [{"start": 6.0, "peak": 10.0, "end": 10.15, "score": 1.0, "signals": ["scene"]}, {"start": 10.1
  [tool] cut_clip({"end":18.15,"label":"biggest moment","start":10.15}) -> {"clip": "biggestmoment_0010.2-0018.1.mp4", "seconds": 8.0}
  [tool] look({"question":"What happened in this moment?","t":14.15}) -> The screen shows only a color bar test pattern with a countdown number. There is no gameplay visible so no one has advan
  [tool] remember({"note":"Biggest moment 10-18s was just color bars countdown, no gameplay. Clipped as biggestmoment_0010.2-0018.1.mp4"}) -> saved: Biggest moment 10-18s was just color bars countdown, no gameplay. Clipped as biggestmoment_0010.2-0018.1.mp4
agent: Clipped the loudest part but it was just color bars. Nothing to play off yet, stay ready.  (rounds=5, tokens in=8549 out=821)
memory notes: 1, clips: 1
live watch tick: tools=['look_now'] spoken=[] reply='quiet' (rounds=2)
live teach tick: tools=['look_now', 'callout'] spoken=['Hey welcome in, our only job is keep these bars up and never let it go black.'] reply='quiet' (rounds=3)
live new player asks: tools=['look_now'] spoken=['Hey welcome in, our only job is keep these bars up and never let it go black.'] reply='Welcome in, this is Test Card TV and our job is keep those colour bars on screen. Can you see bars right now or is it black?' (rounds=2)
=== done
```
