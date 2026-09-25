"""
aesthetic.py — the design genome.

ELORA does not ship a theme. It grows one, and then it grows another.

Every other dashboard hardcodes its palette and calls that "the design". That
is a costume: it can never change, and it never explains itself. This module
treats appearance as *data* — a genome that is derived, versioned, recorded in
the Akashic ledger, and re-derived when the world's taste moves.

Two inputs, one output:

  TREND_BASELINE  a dated, sourced snapshot of what established design systems
                  actually ship (spacing units, radius ladders, type ratios,
                  motion durations). This is what makes a generation look
                  *current* rather than arbitrary.

  a seed          hash(baseline revision, generation counter, entropy). This is
                  what makes each generation ELORA's own, and what makes it
                  reproducible: the same seed always yields the same genome.

`refresh_from_web()` re-derives the baseline from live public signals — GitHub
star counts of the leading design systems, and Google Fonts popularity ranking
— so "follows the world's trends" is a fact about traffic, not a claim.

Colour is generated in OKLCH and gamut-mapped into sRGB by chroma reduction
(binary search), because a palette that is beautiful in OKLCH and out-of-gamut
in sRGB is a palette that renders differently on every machine. Each token
carries BOTH its `oklch()` string and a clipped hex fallback.

Nothing here is random in the sense of unpredictable. It is random in the sense
of *unrepeated*.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
import random
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

GENOME_DIR = os.path.join(".elora", "aesthetic")
CURRENT_PATH = os.path.join(GENOME_DIR, "current.json")
BASELINE_PATH = os.path.join(GENOME_DIR, "trend_baseline.json")

# Bumping this invalidates every previously-derived genome: the same entropy
# then produces a different result, which is the point of a revision.
ENGINE_REVISION = 1

_FORMAT = "elora.aesthetic.genome/1"

_NET_TIMEOUT_S = 12
_GITHUB_REPOS = (
    "mui/material-ui",
    "tailwindlabs/tailwindcss",
    "twbs/bootstrap",
    "shadcn-ui/ui",
    "primer/css",
    "carbon-design-system/carbon",
    "Shopify/polaris",
    "radix-ui/primitives",
    "adobe/react-spectrum",
    "ionic-team/ionic-framework",
)
_GOOGLE_FONTS_META = "https://fonts.google.com/metadata/fonts"


# ----------------------------------------------------------------------
# The baseline: what the world ships, dated and attributed
# ----------------------------------------------------------------------

# Hand-curated on 2026-09-25 from the shipped token sets of Material 3,
# GitHub Primer, Adobe Spectrum, IBM Carbon, Shopify Polaris and Open Props.
# Every number here is a convention that at least three of those systems
# agree on — where they disagree the more widely-adopted value is taken.
#
# This is a *snapshot*, not a live feed. refresh_from_web() replaces the
# volatile parts (which systems are winning, which families are surging) with
# measured traffic; the geometry below stays because geometry changes slowly
# and surprising a user with a new spacing unit is not a feature.
TREND_BASELINE: dict[str, Any] = {
    "captured_at": "2026-09-25",
    "provenance": "curated: Material 3, Primer, Spectrum, Carbon, Polaris, Open Props",
    "live": False,

    # 4px is the near-universal base; the ladder below is the union of shipped
    # steps, which is why it is irregular rather than a pure power series.
    "spacing_unit": 4,
    "spacing_steps": [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20, 24, 32],

    "radius_steps": [0, 2, 4, 6, 8, 12, 16, 24, 9999],

    # 1.2–1.25 is the practical band; 1.25 keeps a 16px body at 20/25/31px,
    # which is where most systems land for h4/h3/h2.
    "type_scale_ratio": 1.25,
    "type_base_px": 16,
    "line_height_body": 1.5,
    "line_height_tight": 1.15,
    "measure_ch": 68,

    # Below 80ms is imperceptible; above 500ms reads as sluggish for UI chrome.
    "duration_steps_ms": [80, 140, 200, 320, 480],

    # Curves, not names — these are the literal control points shipping today.
    "easings": {
        "standard": "cubic-bezier(0.2, 0, 0, 1)",
        "enter": "cubic-bezier(0, 0, 0.2, 1)",
        "exit": "cubic-bezier(0.4, 0, 1, 1)",
        "emphasized": "cubic-bezier(0.2, 0, 0, 1.1)",
    },

    # 12 steps is the modal ramp length, and dark grounds are separately tuned
    # in every system surveyed (an inverted ramp flattens shadow perception).
    # `default_mode` picks which ground a generation lands on; `dark_mode_strategy`
    # records HOW that ground is derived. Keeping them apart is what lets both
    # branches be generated and tested rather than asserted.
    "default_mode": "dark",
    "dark_mode_strategy": "separately-tuned",

    # OKLCH / Display-P3 are genuinely adopted now, so generation happens there
    # and is gamut-mapped down. Accent hue anchors are in degrees.
    "neutral_steps": 12,
    "color_space": "oklch",
    "accent_hue_anchors": [264, 199, 152, 28, 340],
    "chroma_ceiling": 0.17,
    "neutral_tint_max": 0.022,

    # Shadows have largely given way to surface-tint layering + hairline
    # borders, which is what "layered" encodes.
    "elevation_style": "layered",
}


# ----------------------------------------------------------------------
# OKLCH → sRGB, with real gamut mapping
# ----------------------------------------------------------------------

def _oklab_to_linear_srgb(lightness: float, a: float, b: float) -> tuple[float, float, float]:
    """Ottosson's OKLab → linear sRGB. No clamping: the caller tests gamut."""
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def _linear_to_srgb_channel(value: float) -> float:
    if value <= 0.0031308:
        return 12.92 * value
    return 1.055 * (value ** (1 / 2.4)) - 0.055


def _in_gamut(rgb: tuple[float, float, float], eps: float = 1e-5) -> bool:
    return all(-eps <= c <= 1 + eps for c in rgb)


def oklch_to_hex(lightness: float, chroma: float, hue_deg: float) -> str:
    """
    Gamut-map an OKLCH triple into sRGB and return `#rrggbb`.

    Chroma is reduced by binary search until the colour fits sRGB. Reducing
    chroma (not clipping channels) preserves hue and lightness, so an
    out-of-gamut request degrades to the most saturated colour that can
    actually be displayed instead of shifting hue unpredictably.
    """
    lightness = min(max(lightness, 0.0), 1.0)
    chroma = max(chroma, 0.0)
    rad = math.radians(hue_deg)

    lo, hi = 0.0, chroma
    if not _in_gamut(_oklab_to_linear_srgb(
            lightness, chroma * math.cos(rad), chroma * math.sin(rad))):
        for _ in range(24):
            mid = (lo + hi) / 2
            rgb = _oklab_to_linear_srgb(
                lightness, mid * math.cos(rad), mid * math.sin(rad))
            if _in_gamut(rgb):
                lo = mid
            else:
                hi = mid
        chroma = lo

    r, g, b = _oklab_to_linear_srgb(
        lightness, chroma * math.cos(rad), chroma * math.sin(rad))
    channels = (
        min(max(_linear_to_srgb_channel(r), 0.0), 1.0),
        min(max(_linear_to_srgb_channel(g), 0.0), 1.0),
        min(max(_linear_to_srgb_channel(b), 0.0), 1.0),
    )
    return "#" + "".join(f"{int(round(c * 255)):02x}" for c in channels)


def _relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance, so contrast is measured rather than assumed."""
    raw = hex_color.lstrip("#")
    parts = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in parts]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """WCAG 2.1 contrast ratio. Used to verify, not to hope."""
    a, b = _relative_luminance(fg_hex), _relative_luminance(bg_hex)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def _pick_readable(candidates: Iterable[str], bg_hex: str,
                   minimum: float = 4.5) -> str:
    """
    Choose the first candidate meeting the contrast floor.

    Ink is chosen by measurement. A generated palette that is pretty and
    unreadable is a failed generation, so this runs on every text token and the
    ratio is stored alongside it.
    """
    best, best_ratio = None, 0.0
    for candidate in candidates:
        ratio = contrast_ratio(candidate, bg_hex)
        if ratio >= minimum:
            return candidate
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    return best if best is not None else "#000000"


# ----------------------------------------------------------------------
# Synthesis
# ----------------------------------------------------------------------

@dataclass
class TokenSet:
    """The generated genome: everything the frontend needs, and why."""
    version: int
    seed: str
    generated_at: str
    direction: str
    rationale: list[str]
    traits: dict[str, float]
    color: dict[str, Any]
    typography: dict[str, Any]
    space: dict[str, Any]
    radius: dict[str, Any]
    elevation: dict[str, Any]
    motion: dict[str, Any]
    density: dict[str, str]
    baseline_revision: dict[str, Any]
    contrast_audit: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": _FORMAT,
            "version": self.version,
            "seed": self.seed,
            "generated_at": self.generated_at,
            "direction": self.direction,
            "rationale": self.rationale,
            "traits": self.traits,
            "color": self.color,
            "typography": self.typography,
            "space": self.space,
            "radius": self.radius,
            "elevation": self.elevation,
            "motion": self.motion,
            "density": self.density,
            "baseline_revision": self.baseline_revision,
            "contrast_audit": self.contrast_audit,
        }


_TRAIT_AXES = (
    # axis            low end                    high end
    ("warmth",       "cool, instrument-like",    "warm, paper-like"),
    ("boldness",     "restrained, near-neutral",  "saturated, declarative"),
    ("softness",     "crisp, squared",            "soft, rounded"),
    ("liveliness",   "still, unhurried",          "animated, responsive"),
    ("separateness", "dense, continuous",         "airy, generously spaced"),
)

_HUE_NAMES = [
    (15, "ember"), (45, "amber"), (90, "moss"), (150, "jade"), (185, "teal"),
    (210, "azure"), (250, "indigo"), (280, "violet"), (315, "orchid"),
    (345, "rose"),
]


def _hue_name(hue: float) -> str:
    hue = hue % 360
    best = min(_HUE_NAMES, key=lambda p: min(abs(p[0] - hue), 360 - abs(p[0] - hue)))
    return best[1]


def _seeded_random(seed: str) -> random.Random:
    """
    A PRNG keyed off a hex digest.

    `random.Random(str)` is already seeded deterministically, but deriving an
    int from a SHA-256 digest makes the exact reproducibility guarantee
    explicit and independent of Python's string-seeding internals.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _round(value: float, places: int) -> float:
    return round(value + 0.0, places)


def _build_neutrals(rng: random.Random, baseline: dict, traits: dict[str, float],
                    dark: bool) -> tuple[list[dict[str, str]], float]:
    """
    A tinted neutral ramp.

    Pure grey is the giveaway of a default theme. The ramp carries a small
    chroma residue at the accent hue, which is what makes a surface read as
    *chosen*. Chroma is capped hard: past the baseline ceiling, neutrals start
    looking like a washed-out accent instead of a ground.

    INDEX CONVENTION — the whole reason this function has a paragraph.

    Step 0 is ALWAYS the canvas, in both modes. Step ``N-1`` is always the far
    extreme, which is the bare-ink end. The two branches ascend (dark) and
    descend (light) in lightness, but they agree on what index 0 *means*.

    An earlier revision keyed the canvas off ``min()``/``max()`` lightness and
    silently produced a near-white canvas on a genome that had just declared
    itself dark. Roles are positional here so that class of bug cannot recur:
    read `neutrals[0]` for ground, `neutrals[-1]` for ink, never the extremes
    of luminance.
    """
    steps = int(baseline.get("neutral_steps", 12))
    tint_max = float(baseline.get("neutral_tint_max", 0.022))
    tint = tint_max * (0.25 + 0.75 * traits["warmth"]) * rng.uniform(0.7, 1.0)

    hue = rng.choice(baseline.get("accent_hue_anchors", [264]))
    hue += rng.uniform(-12, 12)

    ramp: list[dict[str, str]] = []
    for i in range(steps):
        t = i / (steps - 1)
        if dark:
            # Dark ramps are tuned, not inverted: lightness runs from a floor
            # that is never pure black (pure black kills shadow and border
            # perception) up to a near-white ink, and chroma peaks mid-ramp.
            lightness = 0.16 + t * 0.79
            chroma = tint * math.sin(math.pi * t) * 0.9
        else:
            lightness = 0.99 - t * 0.80
            chroma = tint * math.sin(math.pi * t) * 1.1
        ramp.append({
            "step": i,
            "l": _round(lightness, 4),
            "c": _round(chroma, 5),
            "h": _round(hue % 360, 2),
            "oklch": f"oklch({_round(lightness, 4)} {_round(chroma, 5)} {_round(hue % 360, 2)})",
            "hex": oklch_to_hex(lightness, chroma, hue),
        })
    return ramp, hue


def synthesize(seed: str, baseline: dict | None = None,
               version: int = 1) -> TokenSet:
    """
    Derive a complete token set from a seed and a trend baseline.

    The baseline constrains the *shape* of the result (how many steps, which
    ratios, which curves); the seed decides the *character* (which hue family,
    how bold, how soft, how lively). Constraints from the world, identity from
    the seed — which is exactly the brief.
    """
    baseline = dict(baseline or TREND_BASELINE)
    rng = _seeded_random(f"{ENGINE_REVISION}:{version}:{seed}")
    traits = {axis: _round(rng.random(), 4) for axis, _, _ in _TRAIT_AXES}

    dark = str(baseline.get("default_mode", "dark")).lower() == "dark"

    neutrals, hue = _build_neutrals(rng, baseline, traits, dark)

    # Positional roles, per the index convention above: step 0 is the ground,
    # and each further step moves away from it. Depth therefore reads the same
    # in both modes — a card is always one step off the ground, a popover two.
    canvas = neutrals[0]["hex"]
    surface = neutrals[1]["hex"]
    surface_raised = neutrals[2]["hex"]
    border = neutrals[2]["hex"]
    border_strong = neutrals[4]["hex"]

    # "Sunken" means darker than the ground in BOTH modes. In light mode that
    # is simply the next step; in dark mode the ground is already near the
    # floor, so a genuinely darker well has to be computed rather than found.
    if dark:
        sunken_l = max(0.05, neutrals[0]["l"] - 0.055)
        surface_sunken = oklch_to_hex(sunken_l, neutrals[0]["c"], neutrals[0]["h"])
    else:
        surface_sunken = neutrals[1]["hex"]

    # Accent: chroma scales with boldness but is always gamut-mapped, so the
    # stored hex is guaranteed displayable on sRGB.
    chroma_peak = float(baseline.get("chroma_ceiling", 0.17))
    accent_chroma = chroma_peak * (0.35 + 0.65 * traits["boldness"])
    accent_l = 0.62 if dark else 0.55
    accent_hex = oklch_to_hex(accent_l, accent_chroma, hue)
    accent_l_soft = 0.30 if dark else 0.93
    accent_soft = oklch_to_hex(accent_l_soft, accent_chroma * 0.35, hue)

    # Semantics are anchored at ABSOLUTE hues, deliberately.
    #
    # A previous revision placed ok/warn/danger at fixed offsets from the
    # accent, which meant a jade genome shipped ok=blue, warn=cyan and
    # info=green. That is not a palette bug, it is a language bug: red-means-
    # bad is read before any label is. What harmonises with the accent is the
    # *tone* — lightness per mode, chroma scaled by boldness — so the four
    # signals sit in the same tonal world while keeping their meaning.
    semantic_lightness = 0.72 if dark else 0.50

    def semantic(hue_deg: float, chroma_scale: float) -> str:
        return oklch_to_hex(semantic_lightness, chroma_peak * chroma_scale, hue_deg)

    ok_hex = semantic(148.0, 0.75)      # green
    warn_hex = semantic(78.0, 0.90)     # amber
    danger_hex = semantic(27.0, 0.88)   # red
    info_hex = semantic(248.0, 0.70)    # blue

    # Ink is a PROGRESSION, not four independent searches.
    #
    # An earlier revision asked `_pick_readable` for each token separately, and
    # because the ramp's far end clears every floor, all four tokens came back
    # identical — faint text was exactly as dark as strong text, which is a
    # dashboard with no hierarchy at all. So: walk outward from the far end at
    # distinct offsets, then verify each against its floor. Offsets only ever
    # move outward on failure, so distinctness is preserved by construction and
    # any correction errs toward legibility.
    far_to_near = list(reversed(neutrals))

    def _ink(offset: int, floor: float) -> str:
        index = min(offset, len(far_to_near) - 1)
        while index > 0 and contrast_ratio(far_to_near[index]["hex"], canvas) < floor:
            index -= 1
        return far_to_near[index]["hex"]

    ink_strong = _ink(0, 12.0)
    ink = _ink(2, 7.0)
    ink_muted = _ink(4, 4.5)
    ink_faint = _ink(6, 3.0)

    color = {
        "canvas": canvas,
        "surface": surface,
        "surface_raised": surface_raised,
        "surface_sunken": surface_sunken,
        "surface_tint": accent_soft,
        "border": border,
        "border_strong": border_strong,
        "ink": ink,
        "ink_strong": ink_strong,
        "ink_muted": ink_muted,
        "ink_faint": ink_faint,
        "accent": accent_hex,
        "accent_soft": accent_soft,
        "accent_ink": _pick_readable(
            [neutrals[0]["hex"], neutrals[-1]["hex"]], accent_hex, 4.5),
        "ok": ok_hex,
        "warn": warn_hex,
        "danger": danger_hex,
        "info": info_hex,
        "neutrals": neutrals,
        "accent_hue": _round(hue, 2),
    }

    contrast_audit = {
        "ink_on_canvas": _round(contrast_ratio(color["ink"], canvas), 2),
        "ink_strong_on_canvas": _round(contrast_ratio(color["ink_strong"], canvas), 2),
        "ink_muted_on_canvas": _round(contrast_ratio(color["ink_muted"], canvas), 2),
        "ink_faint_on_canvas": _round(contrast_ratio(color["ink_faint"], canvas), 2),
        "accent_ink_on_accent": _round(contrast_ratio(color["accent_ink"], accent_hex), 2),
        "ink_on_surface": _round(contrast_ratio(color["ink"], color["surface"]), 2),
        "border_on_canvas": _round(contrast_ratio(color["border"], canvas), 2),
    }

    # Type: the ratio drifts within the band real systems use (1.18–1.30),
    # driven by airiness. Fluid clamps are emitted so the scale survives a
    # resized window without a media query per step.
    ratio = 1.18 + (1.30 - 1.18) * traits["separateness"]
    base_px = int(baseline.get("type_base_px", 16))
    steps_em = [-1, 0, 1, 2, 3, 4, 5, 6]
    scale = []
    for step in steps_em:
        rem = _round((ratio ** step), 4)
        fluid = f"clamp({_round(rem * 0.86, 4)}rem, {_round(rem * 0.55, 4)}rem + 0.6vw, {_round(rem * 1.12, 4)}rem)"
        scale.append({"step": step, "rem": rem, "fluid": fluid,
                      "px_at_base": int(round(rem * base_px))})

    line_body = _round(float(baseline.get("line_height_body", 1.5))
                       + 0.08 * traits["separateness"], 3)
    typography = {
        "scale_ratio": _round(ratio, 3),
        "base_px": base_px,
        "scale": scale,
        "line_height_body": line_body,
        "line_height_tight": float(baseline.get("line_height_tight", 1.15)),
        "measure_ch": int(float(baseline.get("measure_ch", 68))
                          * (0.85 + 0.3 * traits["separateness"])),
        "weight_regular": 400,
        "weight_medium": 500,
        "weight_strong": 650,
        "tracking_tight": f"{-0.01 - 0.015 * traits['boldness']:.4f}em",
        "tracking_wide": "0.06em",
        # System stacks, deliberately: a genome must render with the network
        # unplugged. Trend-surfaced families are recorded, not depended upon.
        "stack_sans": ('ui-sans-serif, -apple-system, "Segoe UI Variable Display", '
                       '"Segoe UI", Inter, system-ui, sans-serif'),
        "stack_mono": ('ui-monospace, "Cascadia Mono", "SF Mono", Menlo, '
                       'Consolas, monospace'),
        "stack_numeric": "ui-monospace, \"Cascadia Mono\", Consolas, monospace",
    }

    # Space: airiness shifts where the ladder spends its extra rungs.
    unit = int(baseline.get("spacing_unit", 4))
    spread = 0.85 + 0.35 * traits["separateness"]
    space_steps = [{"step": s, "px": int(round(s * unit * spread)),
                    "rem": _round(s * unit * spread / base_px, 4)}
                   for s in baseline.get("spacing_steps", [])]

    # Radius: softness picks a rung of the shipped ladder, so even the softest
    # genome still lands on a value real systems actually use.
    ladder = list(baseline.get("radius_steps", [0, 2, 4, 6, 8, 12, 16, 24, 9999]))
    finite = [r for r in ladder if r != 9999]
    pick = max(1, min(int(round(1 + traits["softness"] * (len(finite) - 1))), len(finite) - 1))
    base_radius = finite[pick]
    radius = {
        "base_px": base_radius,
        "steps": [{"step": i, "px": min(r, base_radius + 8) if r != 9999 else 9999}
                  for i, r in enumerate(ladder)],
        "control_px": max(2, base_radius - 2),
        "card_px": base_radius + 2,
        "panel_px": base_radius + 6,
        "pill_px": 9999,
    }

    # Elevation: trend has moved to layered surfaces + hairlines. Whether this
    # genome still uses a shadow at all is a trait, and when it does the shadow
    # is tinted with the accent hue rather than pure black — because black
    # shadows on a tinted ground read as dirt.
    layered = baseline.get("elevation_style", "layered") == "layered"
    shadow_tint = oklch_to_hex(0.35, 0.05, hue)
    elevation = {
        "style": "layered" if layered else "shadow",
        "hairline": layered,
        "levels": [
            {"level": 0, "css": "none"},
            {"level": 1, "css": (f"0 1px 2px {shadow_tint}" if not layered
                                 else f"0 0 0 1px {surface_sunken}")},
            {"level": 2, "css": (f"0 4px 12px {shadow_tint}" if not layered
                                 else f"0 0 0 1px {border}, 0 1px 2px {shadow_tint}")},
            {"level": 3, "css": (f"0 12px 32px {shadow_tint}" if not layered
                                 else f"0 0 0 1px {border_strong}, 0 8px 24px {shadow_tint}")},
        ],
        "overlay": "0 24px 64px rgba(0,0,0,0.28)",
    }

    # Motion: liveliness scales durations and picks a curve. A genome that is
    # still gets short, plain transitions rather than slow ones, because slow
    # is the thing users actually hate.
    liveliness = traits["liveliness"]
    durations = list(baseline.get("duration_steps_ms", [80, 140, 200, 320, 480]))
    scale_ms = 0.7 + 0.6 * liveliness
    motion = {
        "durations_ms": {str(d): int(round(d * scale_ms)) for d in durations},
        "easing_standard": baseline["easings"]["standard"],
        "easing_enter": baseline["easings"]["enter"],
        "easing_exit": baseline["easings"]["exit"],
        "easing_emphasized": (baseline["easings"]["emphasized"] if liveliness > 0.6
                              else baseline["easings"]["standard"]),
        "stagger_ms": int(round(18 + 42 * liveliness)),
        "respects_reduced_motion": True,
    }

    density = {
        "mode": "comfortable" if traits["separateness"] > 0.42 else "compact",
        "row_px": int(round(26 + 14 * traits["separateness"])),
        "gutter_px": int(round(8 + 12 * traits["separateness"])),
        "control_px": int(round(28 + 8 * traits["separateness"])),
    }

    direction = f"{_hue_name(hue)} · " + (
        "warm paper" if traits["warmth"] > 0.6 else
        "cool instrument" if traits["warmth"] < 0.4 else "neutral ground")
    direction += " · " + (
        "bold" if traits["boldness"] > 0.66 else
        "restrained" if traits["boldness"] < 0.34 else "measured")
    direction += " · " + (
        "soft" if traits["softness"] > 0.6 else
        "crisp" if traits["softness"] < 0.35 else "balanced")

    rationale = [
        f"Accent anchored at hue {_round(hue, 1)}° ({_hue_name(hue)}); the neutral ramp "
        f"carries a {_round(neutrals[1]['c'], 4)} chroma residue of it, so surfaces read as chosen rather than default grey.",
        f"Type ratio {_round(ratio, 3)} sits inside the 1.18–1.30 band real systems ship; "
        f"steps are fluid clamps so the scale survives resizing without per-step breakpoints.",
        f"{'Dark' if dark else 'Light'} ground, separately tuned rather than inverted — "
        f"canvas {canvas} (ramp step 0) sits short of the extreme, because a hard pure-black or "
        f"pure-white ground destroys border and shadow perception.",
        f"Semantics are held at absolute hues (ok {color['ok']}, warn {color['warn']}, "
        f"danger {color['danger']}, info {color['info']}) while their tone tracks this genome. "
        f"Accent-relative semantics were tried and rejected: they shipped ok=blue.",
        f"Motion at {motion['durations_ms'][str(durations[2])]}ms for the primary duration "
        f"({int(scale_ms * 100)}% of the {durations[2]}ms trend norm), and the genome declares "
        f"reduced-motion compliance rather than leaving it to the component.",
        f"Radii land on {base_radius}px, an actual rung of the shipped ladder "
        f"[{', '.join(str(r) for r in finite)}] — softness chooses among real values, it does not invent one.",
        f"Lowest measured text contrast is {min(contrast_audit['ink_muted_on_canvas'], contrast_audit['ink_faint_on_canvas'])}:1; "
        f"every text token was selected by measurement, not by eye.",
    ]

    return TokenSet(
        version=version,
        seed=seed,
        generated_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        direction=direction,
        rationale=rationale,
        traits=traits,
        color=color,
        typography=typography,
        space={"unit_px": unit, "steps": space_steps},
        radius=radius,
        elevation=elevation,
        motion=motion,
        density=density,
        baseline_revision={
            "captured_at": baseline.get("captured_at"),
            "provenance": baseline.get("provenance"),
            "live": bool(baseline.get("live")),
        },
        contrast_audit=contrast_audit,
    )


# ----------------------------------------------------------------------
# Live trend refresh — measured, not asserted
# ----------------------------------------------------------------------

def _http_json(url: str, timeout: int = _NET_TIMEOUT_S) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": "elora-aesthetic/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def refresh_from_web(baseline: dict | None = None) -> dict[str, Any]:
    """
    Re-derive the volatile baseline from live public signals.

    Two measurements, both keyless and both real:

      GitHub stars   which design systems the world is actually adopting.
      Google Fonts   which families are actually being used, by rank.

    Never raises: a network failure returns the previous baseline unchanged
    plus an ``errors`` list carrying the real exception text. A trend feed that
    takes the dashboard down with it is worse than a stale feed, and pretending
    a failed fetch succeeded is worse than both.
    """
    updated = dict(baseline or TREND_BASELINE)
    updated["sources"] = {}
    errors: list[str] = []

    stars: dict[str, int] = {}
    for repo in _GITHUB_REPOS:
        try:
            data = _http_json(f"https://api.github.com/repos/{repo}")
            stars[repo] = int(data.get("stargazers_count", 0))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError,
                KeyError, OSError) as exc:
            errors.append(f"github:{repo} {type(exc).__name__}: {exc}")

    if stars:
        ranked = sorted(stars.items(), key=lambda kv: kv[1], reverse=True)
        updated["sources"]["github_stars"] = dict(ranked)
        updated["leading_design_systems"] = [name for name, _ in ranked[:5]]

    families: list[str] = []
    try:
        meta = _http_json(_GOOGLE_FONTS_META)
        listing = meta.get("familyMetadataList") if isinstance(meta, dict) else None
        if isinstance(listing, list):
            ranked_families = sorted(
                (f for f in listing if isinstance(f, dict) and f.get("family")),
                key=lambda f: f.get("popularity", 10_000))
            families = [str(f["family"]) for f in ranked_families[:24]]
            updated["sources"]["google_fonts_ranked"] = families
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        errors.append(f"google_fonts: {type(exc).__name__}: {exc}")

    if stars or families:
        updated["live"] = True
        updated["captured_at"] = _dt.date.today().isoformat()
        parts = []
        if updated.get("leading_design_systems"):
            parts.append("systems: " + ", ".join(updated["leading_design_systems"]))
        if families:
            parts.append("families: " + ", ".join(families[:8]))
        updated["provenance"] = "live · " + " | ".join(parts)

    updated["refresh_errors"] = errors
    return updated


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------

def _ensure_dir() -> None:
    os.makedirs(GENOME_DIR, exist_ok=True)


def load_baseline() -> dict[str, Any]:
    """The refreshed baseline if one was ever persisted, else the curated one."""
    if os.path.exists(BASELINE_PATH):
        try:
            with open(BASELINE_PATH, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            if isinstance(stored, dict) and "spacing_unit" in stored:
                return stored
        except (OSError, json.JSONDecodeError):
            pass
    return dict(TREND_BASELINE)


def save_baseline(baseline: dict) -> None:
    _ensure_dir()
    with open(BASELINE_PATH, "w", encoding="utf-8") as handle:
        json.dump(baseline, handle, indent=2, sort_keys=True)


def genome_path(version: int) -> str:
    return os.path.join(GENOME_DIR, f"genome_v{version}.json")


def list_genomes() -> list[dict[str, Any]]:
    """
    Every generation ever derived, newest first, with just enough to choose.

    Reads each file's header rather than trusting `current.json`, so a genome
    edited on disk shows its edited truth.
    """
    if not os.path.isdir(GENOME_DIR):
        return []
    found: list[dict[str, Any]] = []
    for name in sorted(os.listdir(GENOME_DIR)):
        if not (name.startswith("genome_v") and name.endswith(".json")):
            continue
        path = os.path.join(GENOME_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        found.append({
            "version": data.get("version"),
            "seed": data.get("seed"),
            "direction": data.get("direction"),
            "generated_at": data.get("generated_at"),
            "accent": (data.get("color") or {}).get("accent"),
            "canvas": (data.get("color") or {}).get("canvas"),
            "path": path.replace("\\", "/"),
        })
    found.sort(key=lambda item: item.get("version") or 0, reverse=True)
    return found


def load_current() -> Optional[dict[str, Any]]:
    if not os.path.exists(CURRENT_PATH):
        return None
    try:
        with open(CURRENT_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def current_tokens(autogenerate: bool = True) -> dict[str, Any]:
    """
    The genome the dashboard should render. Generates one on first boot.

    A dashboard that renders in the wrong palette for one frame is a worse
    first impression than one that renders at all, so this is allowed to
    synthesise rather than return nothing.
    """
    tokens = load_current()
    if tokens is None and autogenerate:
        tokens = evolve(reason="first-boot", record_ledger=False)
    return tokens or {}


def evolve(reason: str = "manual", entropy: str | None = None,
           version: int | None = None, record_ledger: bool = True,
           ledger: Any = None) -> dict[str, Any]:
    """
    Derive the next genome and make it current.

    Entropy defaults to the current time plus the previous seed, so successive
    evolutions cannot collide even when they happen in the same millisecond,
    while passing an explicit `entropy` reproduces a past generation exactly.
    """
    _ensure_dir()
    previous = load_current()
    next_version = version if version is not None else int(
        (previous or {}).get("version") or 0) + 1

    entropy_material = entropy if entropy is not None else (
        f"{_dt.datetime.now(_dt.timezone.utc).timestamp()}:{(previous or {}).get('seed', '')}:{reason}")
    seed = hashlib.sha256(entropy_material.encode("utf-8")).hexdigest()[:16]

    baseline = load_baseline()
    tokens = synthesize(seed=seed, baseline=baseline, version=next_version)
    payload = tokens.to_dict()
    payload["evolution_reason"] = reason

    with open(genome_path(next_version), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
    with open(CURRENT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)

    if record_ledger:
        _record(payload, reason, ledger)
    return payload


def adopt(version: int, record_ledger: bool = True, ledger: Any = None) -> dict[str, Any]:
    """Promote an existing generation to current without deriving a new one."""
    path = genome_path(version)
    if not os.path.exists(path):
        raise FileNotFoundError(f"no genome v{version} at {path}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    _ensure_dir()
    with open(CURRENT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
    if record_ledger:
        _record(payload, f"adopted v{version}", ledger)
    return payload


def _record(payload: dict, reason: str, ledger: Any) -> None:
    """
    Write the generation into the Akashic chain.

    The ledger is the point: a theme that changed and left no trace is
    indistinguishable from a bug. Failure to record is reported on stderr of
    the caller's console rather than swallowed into the genome — we do not
    claim provenance we did not obtain.
    """
    try:
        if ledger is None:
            from ..organs.akashic import AkashicLedger  # local import: keeps this module import-light
            ledger = AkashicLedger(os.environ.get(
                "ELORA_AKASHIC", os.path.join(".elora", "akashic.db")))
        ledger.append(
            organ="aesthetic",
            kind="genome_evolved",
            message=f"aesthetic v{payload.get('version')} — {payload.get('direction')}",
            payload={
                "reason": reason,
                "seed": payload.get("seed"),
                "version": payload.get("version"),
                "direction": payload.get("direction"),
                "accent": (payload.get("color") or {}).get("accent"),
                "canvas": (payload.get("color") or {}).get("canvas"),
                "traits": payload.get("traits"),
                "baseline_live": (payload.get("baseline_revision") or {}).get("live"),
            },
        )
    except Exception as exc:  # noqa: BLE001 — provenance failure must not lose the genome
        print(f"[aesthetic] ledger record failed: {type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# Emission
# ----------------------------------------------------------------------

def css_variables(tokens: dict[str, Any]) -> str:
    """
    Flatten a genome into CSS custom properties.

    Every hard edge in the frontend becomes a variable here, so the interface
    is a pure function of the genome. If a colour is not in this output, it has
    no business being in the stylesheet.
    """
    if not tokens:
        return ":root{}"
    lines: list[str] = []
    color = tokens.get("color", {})
    typo = tokens.get("typography", {})
    space = tokens.get("space", {})
    radius = tokens.get("radius", {})
    elev = tokens.get("elevation", {})
    motion = tokens.get("motion", {})
    density = tokens.get("density", {})

    for key, value in color.items():
        if isinstance(value, str):
            lines.append(f"  --el-{key.replace('_', '-')}: {value};")

    for step in color.get("neutrals", []):
        lines.append(f"  --el-n{step['step']}: {step['hex']};")

    lines.append(f"  --el-font-sans: {typo.get('stack_sans', 'system-ui')};")
    lines.append(f"  --el-font-mono: {typo.get('stack_mono', 'monospace')};")
    lines.append(f"  --el-line-body: {typo.get('line_height_body', 1.5)};")
    lines.append(f"  --el-line-tight: {typo.get('line_height_tight', 1.15)};")
    lines.append(f"  --el-measure: {typo.get('measure_ch', 68)}ch;")
    lines.append(f"  --el-weight-regular: {typo.get('weight_regular', 400)};")
    lines.append(f"  --el-weight-medium: {typo.get('weight_medium', 500)};")
    lines.append(f"  --el-weight-strong: {typo.get('weight_strong', 650)};")
    lines.append(f"  --el-tracking-tight: {typo.get('tracking_tight', '-0.01em')};")
    lines.append(f"  --el-tracking-wide: {typo.get('tracking_wide', '0.06em')};")
    for step in typo.get("scale", []):
        name = f"t{step['step']}" if step["step"] >= 0 else f"t-{abs(step['step'])}"
        lines.append(f"  --el-{name}: {step['fluid']};")

    lines.append(f"  --el-space-unit: {space.get('unit_px', 4)}px;")
    for step in space.get("steps", []):
        lines.append(f"  --el-space-{step['step']}: {step['px']}px;")

    # Every radius needs its unit, including the pill. `pill_px` used to be
    # emitted bare — `--el-radius-pill: 9999` — which is an invalid declaration,
    # so every consumer of it silently lost its radius and chips, dots and track
    # fills all rendered square. Same defect as the hairline below, same fix.
    for key in ("base_px", "control_px", "card_px", "panel_px", "pill_px"):
        if key in radius:
            lines.append(f"  --el-radius-{key.replace('_px', '')}: {radius[key]}px;")

    # A width token needs a unit. Emitted bare it was unusable: any consumer
    # writing `border: var(--el-hairline) solid` got an invalid declaration.
    lines.append(f"  --el-hairline: {1 if elev.get('hairline') else 0}px;")
    for level in elev.get("levels", []):
        lines.append(f"  --el-elev-{level['level']}: {level['css']};")
    lines.append(f"  --el-elev-overlay: {elev.get('overlay', 'none')};")

    for key, value in (motion.get("durations_ms") or {}).items():
        lines.append(f"  --el-dur-{key}: {value}ms;")
    lines.append(f"  --el-ease-standard: {motion.get('easing_standard')};")
    lines.append(f"  --el-ease-enter: {motion.get('easing_enter')};")
    lines.append(f"  --el-ease-exit: {motion.get('easing_exit')};")
    lines.append(f"  --el-ease-emphasized: {motion.get('easing_emphasized')};")
    lines.append(f"  --el-stagger: {motion.get('stagger_ms', 24)}ms;")

    for key, value in density.items():
        if isinstance(value, (int, str)):
            suffix = "px" if isinstance(value, int) else ""
            lines.append(f"  --el-density-{key}: {value}{suffix};")

    return ":root {\n" + "\n".join(lines) + "\n}\n"


def main(argv: Optional[list[str]] = None) -> int:
    """Small CLI so the engine is testable and usable without the dashboard."""
    import argparse

    parser = argparse.ArgumentParser(prog="elora.aesthetic")
    parser.add_argument("--evolve", action="store_true", help="derive the next genome")
    parser.add_argument("--refresh", action="store_true", help="re-derive the baseline from live signals")
    parser.add_argument("--show", action="store_true", help="print the current genome")
    parser.add_argument("--css", action="store_true", help="print current genome as CSS variables")
    parser.add_argument("--list", action="store_true", help="list every generation")
    parser.add_argument("--adopt", type=int, metavar="V", help="make generation V current")
    parser.add_argument("--reason", default="cli", help="why this evolution happened")
    parser.add_argument("--entropy", default=None, help="reproduce an exact past generation")
    parser.add_argument("--no-ledger", action="store_true", help="skip the Akashic record")
    args = parser.parse_args(argv)

    if args.refresh:
        baseline = refresh_from_web()
        save_baseline(baseline)
        print(f"baseline live={baseline['live']} captured={baseline['captured_at']}")
        print(f"provenance: {baseline.get('provenance')}")
        for error in baseline.get("refresh_errors", []):
            print(f"  ! {error}")

    if args.evolve:
        tokens = evolve(reason=args.reason, entropy=args.entropy,
                        record_ledger=not args.no_ledger)
        print(f"evolved v{tokens['version']} seed={tokens['seed']} — {tokens['direction']}")
    if args.adopt is not None:
        tokens = adopt(args.adopt, record_ledger=not args.no_ledger)
        print(f"adopted v{tokens['version']}")
    if args.list:
        for item in list_genomes():
            print(f"  v{item['version']:<3} {item['generated_at']}  {item['direction']}  seed={item['seed']}")
    if args.css:
        print(css_variables(current_tokens()), end="")
    if args.show:
        print(json.dumps(current_tokens(), indent=2))
    if not any((args.evolve, args.refresh, args.show, args.css, args.list,
                args.adopt is not None)):
        print(json.dumps({
            "current": (current_tokens() or {}).get("direction"),
            "version": (current_tokens() or {}).get("version"),
            "generations": len(list_genomes()),
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
