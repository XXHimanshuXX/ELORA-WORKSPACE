"""Verify the aesthetic engine: both modes, semantic hue, contrast, reproducibility."""
import colorsys
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elora.core.aesthetic import (  # noqa: E402
    GENOME_DIR, TREND_BASELINE, contrast_ratio, css_variables,
    list_genomes, synthesize,
)

failures = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def hue_of(hex_color):
    raw = hex_color.lstrip("#")
    r, g, b = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)[0] * 360


def lum(hex_color):
    raw = hex_color.lstrip("#")
    parts = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def exercise(mode, seed):
    baseline = dict(TREND_BASELINE, default_mode=mode)
    t = synthesize(seed=seed, baseline=baseline, version=1)
    c = t.color
    print(f"\n=== {mode.upper()}  seed={seed}  ->  {t.direction} ===")
    print(f"  canvas={c['canvas']} surface={c['surface']} raised={c['surface_raised']} "
          f"sunken={c['surface_sunken']} border={c['border']} ink={c['ink']} accent={c['accent']}")
    print(f"  ok={c['ok']} warn={c['warn']} danger={c['danger']} info={c['info']}")
    print(f"  audit={t.contrast_audit}")

    canvas_ok = lum(c["canvas"]) < 0.22 if mode == "dark" else lum(c["canvas"]) > 0.55
    check(f"{mode}: canvas matches declared mode", canvas_ok,
          f"canvas luminance {lum(c['canvas']):.3f}")

    check(f"{mode}: ink on canvas >= 7:1", contrast_ratio(c["ink"], c["canvas"]) >= 7.0,
          f"{contrast_ratio(c['ink'], c['canvas']):.2f}:1")
    check(f"{mode}: ink on surface >= 4.5:1", contrast_ratio(c["ink"], c["surface"]) >= 4.5,
          f"{contrast_ratio(c['ink'], c['surface']):.2f}:1")
    check(f"{mode}: muted ink >= 4.5:1", contrast_ratio(c["ink_muted"], c["canvas"]) >= 4.5,
          f"{contrast_ratio(c['ink_muted'], c['canvas']):.2f}:1")

    ink_tokens = [c["ink_strong"], c["ink"], c["ink_muted"], c["ink_faint"]]
    check(f"{mode}: ink tokens are a distinct progression",
          len(set(ink_tokens)) == 4, f"{len(set(ink_tokens))} distinct of 4: {ink_tokens}")
    check(f"{mode}: ink_strong >= ink (tonal order holds)",
          contrast_ratio(c["ink_strong"], c["canvas"]) >= contrast_ratio(c["ink"], c["canvas"]) and
          contrast_ratio(c["ink"], c["canvas"]) >= contrast_ratio(c["ink_muted"], c["canvas"]) and
          contrast_ratio(c["ink_muted"], c["canvas"]) >= contrast_ratio(c["ink_faint"], c["canvas"]),
          " > ".join(f"{contrast_ratio(x, c['canvas']):.1f}" for x in ink_tokens))

    border_ratio = contrast_ratio(c["border"], c["canvas"])
    check(f"{mode}: border is a hairline (1.05-3.5:1)", 1.05 <= border_ratio <= 3.5,
          f"{border_ratio:.2f}:1")
    check(f"{mode}: sunken differs from canvas", c["surface_sunken"] != c["canvas"],
          f"sunken={c['surface_sunken']}")
    check(f"{mode}: sunken is darker than canvas",
          lum(c["surface_sunken"]) < lum(c["canvas"]),
          f"sunken {lum(c['surface_sunken']):.3f} vs canvas {lum(c['canvas']):.3f}")

    ok_h, warn_h, danger_h, info_h = (hue_of(c["ok"]), hue_of(c["warn"]),
                                      hue_of(c["danger"]), hue_of(c["info"]))
    check(f"{mode}: ok reads green (90-175 deg)", 90 <= ok_h <= 175, f"hue {ok_h:.0f}")
    check(f"{mode}: warn reads amber (40-100 deg)", 40 <= warn_h <= 100, f"hue {warn_h:.0f}")
    check(f"{mode}: danger reads red (<45 or >335)", danger_h < 45 or danger_h > 335,
          f"hue {danger_h:.0f}")
    check(f"{mode}: info reads blue (200-280 deg)", 200 <= info_h <= 280, f"hue {info_h:.0f}")
    check(f"{mode}: accent ink legible on accent",
          contrast_ratio(c["accent_ink"], c["accent"]) >= 4.5,
          f"{contrast_ratio(c['accent_ink'], c['accent']):.2f}:1")

    for step in c["neutrals"]:
        how = step["hex"]
        if not (how.startswith("#") and len(how) == 7):
            failures.append(f"{mode}: malformed hex {how}")
    check(f"{mode}: all {len(c['neutrals'])} ramp steps are valid hex",
          all(len(s["hex"]) == 7 and s["hex"].startswith("#") for s in c["neutrals"]))

    check(f"{mode}: emits CSS variables", "--el-canvas:" in css_variables(t.to_dict()))
    return t


print("=== AESTHETIC ENGINE VERIFICATION ===")
dark = exercise("dark", "verify-dark-001")
light = exercise("light", "verify-light-001")

print("\n=== REPRODUCIBILITY ===")
again = synthesize(seed="verify-dark-001", baseline=dict(TREND_BASELINE, default_mode="dark"), version=1)
same = again.color == dark.color and again.traits == dark.traits
check("same seed reproduces identical genome", same)
other = synthesize(seed="verify-dark-002", baseline=dict(TREND_BASELINE, default_mode="dark"), version=1)
check("different seed yields a different genome", other.color["accent"] != dark.color["accent"],
      f"{other.color['accent']} vs {dark.color['accent']}")

print("\n=== PERSISTENCE ===")
if os.path.isdir(GENOME_DIR):
    shutil.rmtree(GENOME_DIR)
for reason in ("v1", "v2", "v3"):
    from elora.core.aesthetic import evolve
    evolve(reason=reason, entropy=f"verify-{reason}", record_ledger=False)
gens = list_genomes()
check("three generations persisted", len(gens) == 3, f"got {len(gens)}: {[g['version'] for g in gens]}")
check("genomes have distinct seeds", len({g["seed"] for g in gens}) == 3)
check("distinct accent per generation", len({g["accent"] for g in gens}) == 3,
      str([g["accent"] for g in gens]))
check("directions differ across generations", len({g["direction"] for g in gens}) > 1,
      str([g["direction"] for g in gens]))

print("\n" + "=" * 52)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
