# Coach demo video (3 minutes)

The video is the primary judging artifact. Three parts: Coach working on a PC game today, the SDK that puts Coach inside any game, and where Horizon fits. Show only what was built during the event.

## Before you hit record

1. In `Code\muse-replay`: `git checkout gate13-guardrails`, then start Coach: `python -m uvicorn web.app:app --port 8000` (with your `.env` loaded, same as Gate 5).
2. Open `http://127.0.0.1:8000` in Chrome. Go live, share the game window.
3. In the Live card: Meme reactions ON, spice mild, style 3D, Coach is Muse Bot. Guide me ON.
4. Start the overlay over the game: `cd desktop` then `npm start`, tray icon > Set overlay link > paste the Overlay link.
5. Pick a flat PC game with clear landmarks (a door, a key, an exit) and run it windowed or borderless.
6. OBS: one scene capturing the full desktop (game + overlay), mic on for your narration. 1080p, 30 fps.
7. Have a terminal ready in `Code\muse-replay` for the SDK clip. Click **Copy for Unity** in the Game SDK box so the live id and consent id are on your clipboard.

## Shot list

| Time | Show | Say (roughly) |
|---|---|---|
| 0:00 to 0:15 | Title card, then the game running | "This is Coach, an AI co-op teammate. It watches your game, talks to you, and shows you the way. Built on Muse Spark through the Meta Model API." |
| 0:15 to 0:50 | Play. Let Coach call out on its own (watch tick). The callout banner and voice land over the game | "I'm sharing my screen. Every few seconds Coach looks at the frame and only speaks up when something matters." |
| 0:50 to 1:20 | Ask out loud (push to talk): "Where do I go?" Arrow and numbered route appear on the overlay | "Guide me is on, so Coach can point. It's off by default: Coach only draws on your screen when you let it." |
| 1:20 to 1:40 | Do something dumb on purpose (fall, miss, walk into danger). Meme card pops with the sting | "And when you mess up, it lets you know." |
| 1:40 to 2:00 | Say "Remember I like sound at 40 and inverted look in this game." Then show the Coach page: settings strip, then `127.0.0.1:8000/api/guard` | "Coach remembers how you like each game set up. It stays on topic, has rate limits and a daily token budget, and a kill switch." |
| 2:00 to 2:30 | Terminal: `python sdk/python/fake_game.py --live <id> --consent <id>`. A reaction fires from the game event; ask Coach "where's the east gate?" and the arrow anchors on the landmark | "Screen share works on any PC game. To be inside the game, a studio adds two HTTP calls: the game sends position, objective, landmarks and events; Coach sends back arrows anchored to real world positions. Events like a fall trigger reactions with no model call at all." |
| 2:30 to 2:50 | Slide: three boxes. PC today. SDK inside any game. Horizon. | "On standalone Quest, apps can't draw over other apps, so the universal version needs Meta. Horizon is the natural home: Horizon Worlds already has LLM NPCs, so Coach's persona can live in a world today, and with an OS hook or the SDK, Coach becomes the sidekick in every game." |
| 2:50 to 3:00 | Repo URL and team name | "Coach. Built solo for the Meta hackathon. Repo is public." |

## Horizon talking points (for the slide and the written submission)

- **True today:** Horizon Worlds has LLM-driven NPCs that creators configure; a creator can give an NPC Coach's persona and teaching instructions inside their world. Players see and hear it in the headset.
- **Not true today:** a third-party app cannot draw over other Quest apps; Horizon world scripts have no documented way to call an outside server, so our vision, tools, memory and guardrails don't run inside Horizon yet.
- **The ask:** a companion-app hook at the OS level, or a Coach SDK path for Horizon creators. Coach's contract (state in, directives out) is already designed for exactly that.

## Do not claim in the video

- That Coach shows up inside standalone Quest games. It watches a cast and talks; it doesn't draw in the headset.
- That the Unity client was tested in a game. Say the SDK was exercised with the fake game.
- Any Meta brand as the product name. Coach is Coach. If staff object to "Muse Bot," switch the avatar to Coach before recording.

## After recording

1. Merge `gate13-guardrails` into main (all of Gates 10 to 13 come with it), run the full suite, push. Render redeploys.
2. Make the repo public.
3. Submit: video, repo link, the written description. Aim for tonight, not the last hour.
