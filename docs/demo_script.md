# Three-minute live demo script

The submission video must show the working product end to end. The preferred cut
is therefore a deterministic recording of the real local web application, not a
slide presentation. It uses Offline benchmark mode against the official
50,000-product snapshot and stays under 2:55 to leave upload headroom below the
three-minute limit.

Build a temporary timing cut before the final voice-over is available:

```bash
scripts/setup_demo_recording.sh
python3 scripts/build_live_demo_video.py
```

The setup command is required once per fresh clone and installs the recorder's
locked Playwright dependencies and Chromium build.

For the final cut, place seven numbered `.m4a` or `.wav` recordings in a local,
ignored directory and pass it to the builder:

```bash
python3 scripts/build_live_demo_video.py --voice-dir output/demo/voiceover
```

Record each paragraph separately, with about half a second of silence at the
start and end. The builder cleans and normalizes the clips, but it does not use
voice cloning or change the speaker's identity.

## Narration clips

### `01`

“This is Shopping Copilot running locally over the official fifty-thousand-product
snapshot, in Offline benchmark mode. A shopper can begin vaguely, so I’ll start
by exploring men’s basketball products.”

### `02`

“Turn one returns ten diverse products and asks one useful clarification. I add
polyester as a requirement. Without restarting, the shortlist reranks, and the
verified target—the Pro Club mesh basketball shorts—moves to number one.”

### `03`

“The detail view shows the snapshot price, rating, and why the item surfaced,
while clearly labelling its art as illustrative. Expert mode exposes the
remembered category and material, retrieval signals, and offline model status.”

### `04`

“That completes one end-to-end multi-turn session. Now I restart into a fresh
scenario to demonstrate a harder behavior: changing direction without carrying
stale preferences forward.”

### `05`

“The shopper starts with women’s anoraks, then adds faux fur and a drawstring
closure. Those constraints change the shortlist, but the shopper decides that
drawstring should no longer matter.”

### `06`

“Using Change direction, I replace the earlier preference with faux fur alone.
The agent advances its intent generation, removes stale department and drawstring
evidence, and at turn three ranks the eligible override target first.”

### `07`

“Expert mode confirms intent version two and a seventy-percent override route.
The same offline engine implements the official reset-and-respond contract.
Across all two hundred public sessions, it scored zero point eight one five three
two two, using zero model tokens and costing zero dollars.”

## Recorded interaction timeline

| Target time | Live action |
|---|---|
| 0:00–0:06 | Show the ready application and the Live local demo overlay. |
| 0:06–0:20 | Click **Help me explore** and show the Turn 1 clarification. |
| 0:20–0:34 | Type `For that, what matters is: polyester; 100% Polyester.` and send. |
| 0:34–0:47 | Show `B071F2Z7JG` at rank one. |
| 0:47–1:01 | Open the Pro Club product details and match reasons. |
| 1:01–1:15 | Open **How it decided** and show the Turn 2 state. |
| 1:15–1:22 | Restart and label the next journey as a fresh session. |
| 1:22–1:35 | Click the **Change direction** starter. |
| 1:35–1:48 | Type `For that, what matters is: Faux Fur; Drawstring closure.` and send. |
| 1:48–1:58 | Hold on the changed Turn 2 shortlist. |
| 1:58–2:13 | Use the lower **Change direction** control, enter `Faux Fur`, and apply it. |
| 2:13–2:26 | Show `B09JG4V9ZR` at rank one after the valid override. |
| 2:26–2:40 | Show intent v2, Override 70%, and revoked stale evidence. |
| 2:40–2:49 | Close over the live Expert view with public metrics and team names. |

The first journey is one uninterrupted multi-turn session. The restart before
the override journey must stay visible so the two public traces are never
presented as one conversation. Do not open Amazon, enable Hybrid, show an API
key, or describe snapshot data as current inventory.
