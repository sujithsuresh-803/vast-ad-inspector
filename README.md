# VAST Video Ad-Tag Inspector

**Author:** Sujith Suresh · a discovery + tooling project for video ad-serving technical solutions
**What it is:** a Python tool that parses a **VAST** video ad tag (the IAB standard Google Ad Manager serves for video/CTV), runs an **implementation review** against real ad-serving best practices, and returns a partner-ready report — PASS / WARN / FAIL per check with a plain-English fix. Built to mirror what a video Technical Solutions Consultant actually does: implementation reviews, integration troubleshooting, and translating technical findings into guidance a partner can act on.

> Sample tags in this repo are synthetic/illustrative; the parser implements the real IAB VAST 4.x structure.

---

## 1. Discovery — how a video ad actually serves
A publisher's player asks an ad server (e.g., **Google Ad Manager**) for an ad and gets back a **VAST** XML document. The player reads it to know *what* to play, *from where*, and *which beacons to fire when*. Key pieces:

- **InLine vs Wrapper** — a Wrapper redirects to another VAST tag (a "hop"). Chains of wrappers are normal but each hop adds latency and a failure point.
- **MediaFiles** — the actual renditions. Device reach depends on **progressive MP4/WebM** and **multiple bitrates** (adaptive delivery).
- **Tracking** — `Impression` (counting/billing), quartile events (`start → complete`, i.e. VTR/completion), and `Error` beacons.
- **VideoClicks / ClickThrough** — clickability for performance buys.
- **AdVerifications** — **Open Measurement (OM SDK)** for viewability and invalid-traffic (IVT) signals.
- **VPAID / SIMID** — VPAID is the *deprecated* interactivity/verification framework; CTV and server-side ad insertion (SSAI) don't support it. The modern split is **OM SDK** (measurement) + **SIMID** (interactivity).

## 2. The problem this tool solves
When a video partner's fill, viewability, or completion numbers look wrong, the cause is very often in the **tag itself**, not the campaign. Manually eyeballing VAST XML across partners is slow and error-prone. This tool makes the review **fast, consistent, and explainable** — the same review every time, phrased for a partner's engineers.

## 3. Common partner failure modes it catches
| Symptom the partner reports | Root cause in the tag | The tool's finding |
|---|---|---|
| "Impressions/revenue undercounting" | No `<Impression>` beacon | **FAIL** Impression tracking |
| "Ad won't play on our CTV app" | VPAID-only, or no MP4 rendition | **FAIL** VPAID deprecation / Device reach |
| "Buffering / no fill on slow networks" | Single high bitrate, no ABR | **WARN** Adaptive bitrate |
| "Completion-rate reporting looks off" | Missing quartile `Tracking` events | **WARN** Quartile tracking |
| "Viewability is unmeasured" | No `AdVerifications` / OM SDK | **WARN** Viewability |
| "Timeouts / opt-outs" | Deep wrapper redirect chain | **WARN** Wrapper chain |

## 4. What it produces
Run `python vast_inspector.py` and each tag gets a review + a **health score** and a **verdict** (READY / NEEDS WORK / BLOCKED). Two sample tags are included — a clean VAST 4.2 InLine and a problematic legacy VAST 3.0 tag.

```
IMPLEMENTATION REVIEW  ·  good_inline.xml
[PASS]  Impression tracking    1 impression beacon(s) present.
[PASS]  Device reach (MIME)    3 MP4/WebM rendition(s) - broad device/CTV support.
[PASS]  VPAID deprecation      No VPAID - good; compatible with SSAI/CTV.
[PASS]  Adaptive bitrate       3 bitrate renditions ([500, 900, 2000] kbps).
[PASS]  Quartile tracking      All quartile events present.
[PASS]  Viewability (OM SDK)   AdVerifications present.
  Health score: 100/100   Verdict: READY

IMPLEMENTATION REVIEW  ·  problematic_inline.xml
[FAIL]  Impression tracking    No <Impression> beacon - impressions will NOT be counted or billed.
[FAIL]  Device reach (MIME)    No MP4/WebM rendition (found application/x-shockwave-flash).
[FAIL]  VPAID deprecation      1 VPAID MediaFile(s). Migrate to OM SDK + SIMID.
[WARN]  Quartile tracking      Missing: firstQuartile, midpoint, thirdQuartile, complete.
[WARN]  Viewability (OM SDK)   No <AdVerifications> - viewability & IVT blind.
  Health score: 39/100   Verdict: BLOCKED
```

## 5. Product feedback loop (what I'd send back to PM)
A solutions consultant is also a sensor for the product roadmap. Patterns this tool would surface across many partner tags:
- **VPAID is still common in legacy inventory** → prioritise partner-facing migration guides + a linting gate in the onboarding flow.
- **Missing OM SDK on premium video** → viewability disputes; make AdVerifications a default in tag templates.
- **Single-bitrate MediaFiles** → low fill on constrained networks in emerging markets → nudge ABR in the creative-upload UI.

## 6. Design notes & honesty
- Pure standard-library Python (`xml.etree`), namespace-tolerant, no external ad server required.
- Checks encode publicly documented IAB VAST conventions and widely known best practices; thresholds (e.g., wrapper depth ≤ 5) are defensible rules of thumb, editable at the top of `vast_inspector.py`.
- Sample tags are synthetic and clearly labelled; no real advertiser data.

**Run it:** `python vast_inspector.py` (or pass your own `path/to/tag.xml`).
