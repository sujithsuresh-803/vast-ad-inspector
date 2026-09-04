"""
vast_inspector.py — a VAST video ad-tag implementation reviewer.

What it does: parses a VAST XML ad tag (the IAB standard Google Ad Manager serves for
video/CTV), validates it against a checklist of real ad-serving best practices, and prints a
partner-ready "implementation review" — PASS / WARN / FAIL per check with a plain-English
recommendation. This mirrors the day-to-day of a video Technical Solutions Consultant:
implementation reviews, integration troubleshooting, and turning technical findings into
guidance a partner's team can act on.

Checks are grounded in the IAB VAST 4.x spec + common field failure modes:
  - VAST version & Ad type (InLine vs Wrapper)
  - Wrapper redirect chains (latency / timeout risk)
  - Impression & Error beacons present
  - Linear Duration + MediaFiles present
  - MediaFile hygiene: MP4/WebM for device reach, multiple bitrates (ABR), VPAID deprecation
  - Quartile TrackingEvents (start / firstQuartile / midpoint / thirdQuartile / complete)
  - ClickThrough on the linear creative
  - AdVerifications / Open Measurement (OM SDK) for viewability & fraud
  - Skippable offset

Usage:  python vast_inspector.py [tag.xml ...]      (defaults to ./sample_tags/*.xml)
"""
import sys
import glob
import re
import xml.etree.ElementTree as ET
from pathlib import Path

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
ICON = {PASS: "[PASS]", WARN: "[WARN]", FAIL: "[FAIL]", INFO: "[INFO]"}
MAX_WRAPPER_DEPTH = 5           # industry rule of thumb for redirect chains
GOOD_MIME = {"video/mp4", "video/webm"}
MIN_BITRATES_FOR_ABR = 2


def _localname(tag):
    return tag.split("}", 1)[-1]  # strip namespace


def _find_all(el, name):
    return [e for e in el.iter() if _localname(e.tag) == name]


def _first(el, name):
    for e in el.iter():
        if _localname(e.tag) == name:
            return e
    return None


def review(path):
    findings = []          # (severity, check, detail)
    def add(sev, check, detail):
        findings.append((sev, check, detail))

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return [(FAIL, "XML well-formed", f"Tag does not parse as XML: {e}")], {}

    version = root.get("version", "unknown")
    add(INFO, "VAST version", f"version=\"{version}\"")
    if version.startswith("2"):
        add(WARN, "VAST version", "VAST 2.0 is legacy; recommend upgrading the partner to 4.x for "
                                  "AdVerifications (OM SDK), universal ad ID, and improved error reporting.")

    ads = _find_all(root, "Ad")
    if not ads:
        add(FAIL, "Ad present", "No <Ad> element found — nothing will serve.")
        return findings, {"version": version}

    for ad in ads:
        inline = _first(ad, "InLine")
        wrapper = _first(ad, "Wrapper")

        if wrapper is not None:
            add(INFO, "Ad type", "Wrapper (redirect). Downstream tag cannot be resolved offline.")
            uri = _first(wrapper, "VASTAdTagURI")
            if uri is None or not (uri.text or "").strip():
                add(FAIL, "Wrapper URI", "Wrapper has no <VASTAdTagURI> — the redirect is broken.")
            else:
                add(WARN, "Wrapper chain", f"Redirects to {uri.text.strip()[:60]}… — verify the full chain "
                    f"is <= {MAX_WRAPPER_DEPTH} hops; each hop adds latency and a timeout/opt-out risk on CTV.")
            # impression on wrapper is still expected
            _check_impression(wrapper, add)
            continue

        if inline is None:
            add(FAIL, "Ad type", "Ad is neither InLine nor Wrapper.")
            continue

        add(INFO, "Ad type", "InLine (fully reviewable).")
        _check_impression(inline, add)

        # Error beacon
        add(PASS if _first(inline, "Error") is not None else WARN, "Error beacon",
            "<Error> present — server-side failures are trackable." if _first(inline, "Error") is not None
            else "No <Error> element — you lose visibility into VAST errors (code 100/303/etc.). Add one.")

        linear = _first(inline, "Linear")
        if linear is None:
            add(WARN, "Linear creative", "No <Linear> creative found (non-linear/companion only?).")
        else:
            _check_linear(linear, add)

        # AdVerifications / OM SDK
        has_verif = _first(inline, "AdVerifications") is not None or _first(inline, "Verification") is not None
        add(PASS if has_verif else WARN, "Viewability (OM SDK)",
            "AdVerifications present — Open Measurement viewability/fraud signals enabled."
            if has_verif else "No <AdVerifications> — no Open Measurement (OM SDK); viewability & IVT "
            "measurement will be blind. Strongly recommended for premium video/CTV buys.")

    summary = _summarise(findings)
    return findings, {"version": version, **summary}


def _check_impression(el, add):
    imps = [i for i in _find_all(el, "Impression") if (i.text or "").strip()]
    add(PASS if imps else FAIL, "Impression tracking",
        f"{len(imps)} impression beacon(s) present." if imps
        else "No <Impression> beacon — impressions will NOT be counted or billed. Critical fix.")


def _check_linear(linear, add):
    # Duration
    dur = _first(linear, "Duration")
    add(PASS if dur is not None and (dur.text or "").strip() else FAIL, "Duration",
        f"Duration={dur.text.strip()}" if dur is not None and (dur.text or "").strip()
        else "Linear creative has no <Duration> — players may reject the ad.")

    # MediaFiles
    mfs = _find_all(linear, "MediaFile")
    if not mfs:
        add(FAIL, "MediaFiles", "No <MediaFile> — nothing to play.")
    else:
        mimes = [(m.get("type") or "").lower() for m in mfs]
        vpaid = [m for m in mfs if (m.get("apiFramework") or "").upper() == "VPAID"
                 or "vpaid" in (m.get("type") or "").lower()]
        good = [m for m, mime in zip(mfs, mimes) if mime in GOOD_MIME]
        bitrates = [int(m.get("bitrate")) for m in mfs if (m.get("bitrate") or "").isdigit()]

        add(PASS if good else FAIL, "Device reach (MIME)",
            f"{len(good)} MP4/WebM rendition(s) — broad device/CTV support."
            if good else f"No MP4/WebM rendition (found {sorted(set(mimes))}). Most CTV/mobile players "
            "require progressive MP4; add one.")

        if vpaid:
            add(FAIL, "VPAID deprecation", f"{len(vpaid)} VPAID MediaFile(s). VPAID is deprecated and "
                "unsupported on CTV/most SSAI; migrate to OM SDK (verification) + SIMID (interactivity).")
        else:
            add(PASS, "VPAID deprecation", "No VPAID — good; compatible with SSAI/CTV.")

        add(PASS if len(bitrates) >= MIN_BITRATES_FOR_ABR else WARN, "Adaptive bitrate",
            f"{len(bitrates)} bitrate renditions ({sorted(bitrates)} kbps) — player can adapt to bandwidth."
            if len(bitrates) >= MIN_BITRATES_FOR_ABR else
            f"Only {len(bitrates)} bitrate rendition — add multiple bitrates so low-bandwidth users still fill.")

    # Tracking quartiles
    events = {(_localname(t.tag), t.get("event")) for t in _find_all(linear, "Tracking")}
    have = {e for (_, e) in events if e}
    need = ["start", "firstQuartile", "midpoint", "thirdQuartile", "complete"]
    missing = [q for q in need if q not in have]
    add(PASS if not missing else WARN, "Quartile tracking",
        "All quartile events present." if not missing
        else f"Missing tracking events: {', '.join(missing)} — completion-rate/VTR reporting will be incomplete.")

    # ClickThrough
    ct = _first(linear, "ClickThrough")
    add(PASS if ct is not None and (ct.text or "").strip() else WARN, "ClickThrough",
        "ClickThrough present." if ct is not None and (ct.text or "").strip()
        else "No <ClickThrough> — the ad is not clickable; fine for pure awareness, a miss for performance buys.")

    # Skippable
    off = linear.get("skipoffset")
    add(INFO, "Skippable", f"skipoffset={off} (skippable)." if off else "Non-skippable linear.")


def _summarise(findings):
    counts = {PASS: 0, WARN: 0, FAIL: 0}
    for sev, _, _ in findings:
        if sev in counts:
            counts[sev] += 1
    scored = counts[PASS] + counts[WARN] + counts[FAIL]
    health = round(100 * (counts[PASS] + 0.5 * counts[WARN]) / scored) if scored else 0
    verdict = "READY" if counts[FAIL] == 0 and counts[WARN] <= 2 else \
              "NEEDS WORK" if counts[FAIL] == 0 else "BLOCKED"
    return {"pass": counts[PASS], "warn": counts[WARN], "fail": counts[FAIL],
            "health": health, "verdict": verdict}


def print_report(path, findings, meta):
    name = Path(path).name
    print("=" * 74)
    print(f"IMPLEMENTATION REVIEW  ·  {name}")
    print("=" * 74)
    for sev, check, detail in findings:
        print(f"{ICON[sev]:7} {check:22} {detail}")
    if "health" in meta:
        print("-" * 74)
        print(f"  Health score: {meta['health']}/100   "
              f"({meta['pass']} pass · {meta['warn']} warn · {meta['fail']} fail)   "
              f"Verdict: {meta['verdict']}")
    print()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        base = Path(__file__).parent / "sample_tags"
        args = sorted(glob.glob(str(base / "*.xml")))
    if not args:
        print("No VAST tags found. Pass a path or add files to ./sample_tags/")
        sys.exit(1)
    for p in args:
        f, m = review(p)
        print_report(p, f, m)
