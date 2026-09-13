"""Harvest JWE3 material-parameter blocks out of RenderDoc captures.

WHY. The whole dinosaur colour model is solved except one lookup:
`(seed, complexity) -> twelve signed 10-bit cosine-gradient coefficients`. The game bakes those
on the CPU, so they are not in any shader or asset -- but they ARE in the GPU material buffer,
and a .rdc stores that buffer uncompressed. This pulls them out.

HOW WE FIND A BLOCK. Words 4 and 5 are circulant hue-rotation matrices, and every such matrix
has rows summing to 1 -- so each packed triple sums to 511 regardless of the angle. Two
independent triples both summing to 511 is a ~1-in-millions coincidence, which makes it a cheap
structural filter over gigabytes. Candidates are then IDENTIFIED by matching six known f16 values
(brightness x2, saturation x2, palette scale, palette offset) against the shipped-variant table,
and CONFIRMED by predicting both hue matrices from the FGM's rotation values.

These correlated checks provide evidence, not proof of identity. Contradictory
observations are quarantined, and sweep tables must be associated with each capture.

Verified end to end on Albertosaurus_Juvenile variant 4 (seed 29, complexity 3).
"""
import json
import os
import struct
import sys

import numpy as np
import harvest_integrity as integrity

HERE = os.path.dirname(os.path.abspath(__file__))
import _hpaths  # noqa: E402  (puts the package and its vendor/ folder on sys.path)
import material_block as mb  # noqa: E402

import jwe3_config  # noqa: E402  (_hpaths above put the package on sys.path)

# The capture folder is a SETTING, not a constant -- see jwe3_config.detect_captures_dir. As a
# hardcoded %TEMP%\RenderDoc it worked on one machine and left anyone whose RenderDoc writes
# elsewhere with "no matching .rdc captures" and nothing they could change. Detection still returns
# the historical path, so existing setups are unaffected.
# `audit_captures.py` takes its CAPS from here, so both agree by construction.
CAPS = jwe3_config.get("captures_dir") or os.path.join(os.environ.get("TEMP", ""), "RenderDoc")
# Harvested rows go straight into YOUR coefficient table, which the editor layers over the shipped
# one -- so a capture shows up in the preview immediately, and survives updating the tool.
OUT = _hpaths.coeff_out()


def _f16w(lo, hi):
    return (struct.unpack("<H", struct.pack("<e", lo))[0] |
            (struct.unpack("<H", struct.pack("<e", hi))[0] << 16))


def _f16_encodings(x):
    """Every f16 bit pattern the game might plausibly have written for a float32 `x`.

    THE GAME ROUNDS TOWARD ZERO. `struct.pack("<e", ...)` rounds to nearest, so for any value the
    two disagree on -- roughly half of them -- the fingerprint was one ULP off and the block was
    silently discarded. FGM 1.44 encodes to 0x3dc3 nearest, but every capture holds 0x3dc2.

    Measured, not assumed: of the twelve brightness/saturation values across the five unattributed
    blocks in the first audited capture, twelve of twelve match truncation and the ones that used
    to match are exactly those that are representable outright (1.5, 2.5, 3.0). This was costing
    most of the yield -- see `audit_captures.py`.

    Returns both encodings, so a match is accepted either way. Widening the key does weaken it, but
    the hue matrices still have to confirm afterwards, and those are an independent ~10-value test.
    """
    n = struct.unpack("<H", struct.pack("<e", x))[0]
    v = struct.unpack("<e", struct.pack("<H", n))[0]
    if abs(v) > abs(x) and n & 0x7FFF:
        # the nearest encoding overshot: step one ULP toward zero. Within a sign, decrementing the
        # bit pattern is exactly the next-smaller magnitude, denormals included.
        return (n, n - 1)
    return (n,)


def _fingerprints(row):
    """The (word6, word7) keys a row could produce, over both rounding modes."""
    out = []
    for b0 in _f16_encodings(row["u_globalColourBrightnessBase"]):
        for b1 in _f16_encodings(row["u_globalColourBrightnessPalette"]):
            for s0 in _f16_encodings(row["u_globalColourSaturationBase"]):
                for s1 in _f16_encodings(row["u_globalColourSaturationPalette"]):
                    out.append((b0 | (b1 << 16), s0 | (s1 << 16)))
    return out


def variant_table(sweep_rows=()):
    """{(word6, word7): [variant rows]} -- the identifying f16 fingerprint per variant.

    A row is registered under every encoding it could have produced (see `_f16_encodings`), so one
    row appears under up to sixteen keys.

    DO NOT add word3 (instancePaletteScale/Offset) to this key. Those are *instance* parameters --
    the game varies them per animal, so the GPU block never matches the FGM value and the whole
    fingerprint fails. That bug cut the yield from dozens of blocks to two. Brightness and
    saturation are material-level and do match; the hue matrices then confirm.
    """
    rows = json.load(open(_hpaths.all_seeds()))
    # Fingerprints are reused between sweeps. The latest table cannot identify an
    # older capture safely; callers must supply that capture's immutable snapshot.
    rows = rows + list(sweep_rows)
    tab = {}
    for r in rows:
        try:
            keys = _fingerprints(r)
        except (KeyError, OverflowError, struct.error, TypeError):
            continue
        for key in keys:
            tab.setdefault(key, []).append(r)
    return tab


def plausible(blk):
    """Reject degenerate blocks that pass the structural filter but are not real palettes.

    A material slot that was allocated but never used reads back as a block whose hue matrices
    still satisfy `sum == 511` (so `candidates` accepts it) while the gradient is all zeros. Every
    genuine row harvested so far has amplitude in 128..307 and frequency from a small discrete set
    {20, 51, 102, 153, 204, 307, 460, 476, 497, 511}, so a zero or a negative in either is out of
    family.

    Caught by the user pointing out they had never spawned a Dimorphodon, only hovered it in the
    spawner -- the block was real memory, never filled in, and it had reported three mutually
    contradictory values across runs.

    HONEST CAVEAT: an all-zero gradient is ALSO what a variant with the palette legitimately
    disabled would look like (PALETTE.md: bit 17 of word 2 is the gradient enable). This filter
    cannot tell the two apart. Excluding both is still right for this file's purpose -- it exists to
    learn `(seed, complexity) -> coefficients`, and a zero gradient teaches nothing either way --
    but do not read "rejected" as "false positive".

    RETRACTED 2026-08-01 -- this used to end "a capture taken in the species viewer still contains
    no MATCHING block, so capture in the park". That was measured with the broken f16 fingerprint
    (see `_f16_encodings`), which failed to identify roughly 82% of blocks. "No matching block" was
    evidence about the matcher, not about the species viewer.

    After the fix, ALL 29 captures on hand yield blocks where 17 of 28 previously yielded none. The
    park advice may still be right -- the viewer draws one animal, so it can only ever hold one
    block -- but it is no longer supported by that experiment. Re-test before repeating it.
    """
    if blk.get("gradientEnabled") is False:
        return False
    amp = blk["gradAmplitude"]
    frq = blk["gradFreq"]
    if not any(amp) or not any(frq):
        return False
    if not (all(a >= 0 for a in amp) and all(f >= 0 for f in frq)):
        return False
    # gradOffset is the base level the cosine swings about: `(offset + amp*cos(...))/511`, clamped
    # to 0..1. A negative offset means that channel is pinned near black over most of the cycle,
    # which no genuine palette does -- all 123 clean rows sit in 100..409, i.e. 0.2..0.8.
    #
    # This caught a false positive that survived the full fingerprint AND both hue matrices:
    # chasmosaurus variants 01_07 and 01_08 BOTH carry seed 30 complexity 5, so the model says they
    # must decode to the same coefficients, and they did not. The 01_08 block had
    # off(192,-128,-97) with a flat amp(307,307,307) -- out of family on two counts. Ten agreeing
    # values is strong evidence but it is not proof, and this is the cheap check that spots the
    # residue.
    return all(o >= 0 for o in blk["gradOffset"])


def candidates(words):
    """Vectorised structural filter: both hue-matrix words must have triples summing to 511."""
    def triple_sum(a):
        lo = (a & 0x3FF).astype(np.int32)
        mid = ((a >> 10) & 0x3FF).astype(np.int32)
        hi = ((a >> 20) & 0x3FF).astype(np.int32)
        for v in (lo, mid, hi):
            v[v >= 512] -= 1024
        return lo + mid + hi
    n = len(words) - 11
    if n <= 0:
        return np.array([], dtype=np.int64)
    w4 = words[4:4 + n]
    w5 = words[5:5 + n]
    ok = (np.abs(triple_sum(w4) - 511) <= 2) & (np.abs(triple_sum(w5) - 511) <= 2)
    return np.nonzero(ok)[0]


def confirm(blk, rows):
    """Rows whose FGM rotations predict this block's two hue matrices. Empty if none.

    Returns EVERY confirming row, not the first. The fingerprint is matched over two rounding
    modes, so up to sixteen keys point at a row and more rows now arrive here per block -- taking
    the first match on faith would let a widened key quietly attribute a gradient to the wrong seed,
    and a wrong row in the coefficient table is invisible downstream: the editor just renders the
    wrong colours. `main` refuses to record a block whose confirming rows disagree.
    """
    out = []
    for r in rows:
        pb = mb.hue_matrix_from_rotation(r["u_globalColourRotationOffsetBase"])
        pp = mb.hue_matrix_from_rotation(r["u_globalColourRotationOffsetPalette"])
        if (max(abs(x - y) for x, y in zip(pb, blk["hueMatrixBase"])) <= 2 and
                max(abs(x - y) for x, y in zip(pp, blk["hueMatrixPalette"])) <= 2):
            out.append(r)
    return out


def seed_pair(row):
    return (round(row["u_globalPaletteSeed"]), round(row["u_globalPaletteMaximumComplexity"]))


def scan(path, tab, chunk=32 << 20, filter_degenerate=True):
    """Yield (byte_offset, variant_row, decoded_block, confirming_rows) for every confirmed block.

    Several variants of the same species share a seed (female/juvenile/male of one variant index),
    so more than one confirming row is normal and harmless. What matters is whether they AGREE on
    the (seed, complexity) pair -- the caller decides.
    """
    if chunk < 48 or chunk % 4:
        raise ValueError("chunk must be a multiple of four and at least 48 bytes")
    if not tab:
        return
    # Small half-word lookup tables avoid sorting millions of uint32s for isin.
    # This is only a coarse filter; the complete two-word dictionary still decides.
    low, high = np.zeros(65536, dtype=bool), np.zeros(65536, dtype=bool)
    for first, _ in tab:
        low[first & 65535] = True
        high[first >> 16] = True
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        for base in range(0, size, chunk):
            fh.seek(base)
            buf = fh.read(chunk + 47)
            # A block can occur at any byte offset in the capture container. Each
            # starting offset belongs to exactly one chunk; overlap is read-only.
            for alignment in range(4):
                count = (len(buf) - alignment) // 4
                if count < 12:
                    continue
                a = np.frombuffer(buf, dtype="<u4", count=count, offset=alignment)
                n = min(count - 11, (chunk - 1 - alignment) // 4 + 1)
                brightness = a[6:6+n]
                possible = low[brightness & 65535] & high[brightness >> 16]
                for i in np.flatnonzero(possible):
                    rows = tab.get((int(a[i+6]), int(a[i+7])))
                    if not rows:
                        continue
                    blk = mb.decode([int(x) for x in a[i:i+12]])
                    if not (mb.is_hue_matrix(blk["hueMatrixBase"]) and
                            mb.is_hue_matrix(blk["hueMatrixPalette"])):
                        continue
                    if filter_degenerate and not plausible(blk):
                        continue
                    hits = confirm(blk, rows)
                    if hits:
                        yield base + alignment + int(i)*4, hits[0], blk, hits


def main(only=(), sweep_table=None):
    """Reconcile a complete scan before saving. No game files are modified."""
    if not os.path.isdir(CAPS):
        sys.exit(f"no capture folder at {CAPS}")
    caps = sorted(f for f in os.listdir(CAPS) if f.lower().endswith(".rdc"))
    if only:
        caps = [c for c in caps if any(o in c for o in only)]
    if not caps:
        sys.exit(f"no matching .rdc captures in {CAPS}")
    if sweep_table and len(caps) != 1:
        sys.exit("--sweep-table requires exactly one selected capture")
    integrity.read_table(OUT)  # fail before scanning if the user's table is damaged
    bundled = integrity.read_table(os.path.join(_hpaths.DATA, "gradient_coefficients.json"))
    observations, reports = {}, []
    for cap in caps:
        path = os.path.join(CAPS, cap)
        start = os.stat(path)
        sweep = integrity.capture_mapping(path, _hpaths.work_dir(), sweep_table)
        tab = variant_table(sweep)
        print(f"{cap}: {start.st_size/1e9:.2f} GB; {len(sweep)} capture-bound sweep rows", flush=True)
        if not sweep:
            print("  No sweep association: shipped variants only. For a swept capture, "
                  "select it with --sweep-table <its-seeds.json>.", flush=True)
        n = ambiguous = 0
        for off, row, blk, hits in scan(path, tab):
            pairs = {seed_pair(h) for h in hits}
            if len(pairs) != 1:
                ambiguous += 1
                continue
            seed, complexity = next(iter(pairs))
            key = f"{seed}_{complexity}"
            rec = dict(seed=seed, complexity=complexity,
                       **{f: list(blk[f]) for f in integrity.FIELDS})
            rec.update({"from": [row["ovl"].replace(chr(92), "/").split("/")[-1], row["fgm"]],
                        "capture": cap, "offset": off})
            integrity.validate(rec, key)
            variants = observations.setdefault(key, [])
            # Repeated buffer copies are not independent votes.
            if not any(r["capture"] == cap and integrity.signature(r) == integrity.signature(rec)
                       for r in variants):
                variants.append(rec)
            n += 1
        end = os.stat(path)
        if (start.st_size, start.st_mtime_ns) != (end.st_size, end.st_mtime_ns):
            raise RuntimeError("capture changed during scan; no coefficients saved: " + cap)
        reports.append(dict(capture=cap, confirmed=n, ambiguous=ambiguous))
        print(f"  {n} enabled, plausible, unambiguous blocks; {ambiguous} ambiguous skipped", flush=True)

    existing = integrity.read_table(OUT)
    report_path = OUT + ".harvest-report.json"
    # Unresolved contradictions stay quarantined across runs, even if a later
    # targeted scan happens to contain only one of the contradictory values.
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8") as fh:
            previous = json.load(fh)
        for entries in previous.get("conflicts", {}).values():
            for entry in entries:
                if entry['source'] == 'observed':
                    values = observations.setdefault(entry['key'], [])
                    if entry['row'] not in values:
                        values.append(entry['row'])
    found, conflicts = integrity.reconcile(existing, bundled, observations)
    integrity.atomic_json(report_path, {"captures": reports, "conflicts": conflicts,
                                       "observations": observations})
    integrity.atomic_json(OUT, found)
    print(f"{len(found)-len(existing)} new pairs; {len(conflicts)} conflicting seeds quarantined")
    print(f"coefficients -> {OUT}")
    print(f"scan evidence -> {report_path}")
    return 2 if conflicts else 0


def selftest():
    """The structural filter must accept real hue matrices and reject arbitrary words."""
    good = []
    for rot in (0.0, 0.322, -0.75, 1.0, 0.5):
        p, q, r = mb.hue_matrix_from_rotation(rot)
        good.append((p & 0x3FF) | ((q & 0x3FF) << 10) | ((r & 0x3FF) << 20))
    for w in good:
        assert mb.is_hue_matrix(mb.s10x3(w)), (w, mb.s10x3(w))
    # a full synthetic block must be picked up at the right index
    words = np.array([0] * 4 + [good[0], good[1]] + [0] * 6, dtype=np.uint32)
    assert list(candidates(words)) == [0], list(candidates(words))
    # noise must not pass -- 5000 random words, expect no hits
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 2**32, size=5000, dtype=np.uint64).astype(np.uint32)
    assert len(candidates(noise)) == 0, len(candidates(noise))

    # THE ROUNDING-MODE REGRESSION. The game truncates float32 -> f16; Python rounds to nearest.
    # Spinosaurus variant 01_02 has brightnessBase 1.44, which nearest-rounds to 0x3dc3 while every
    # capture holds 0x3dc2 -- so the table must offer both, or the block is discarded. This one
    # value cost most of the harvest yield, so it gets pinned explicitly.
    assert _f16_encodings(1.440000057220459) == (0x3dc3, 0x3dc2), _f16_encodings(1.44)
    # values that are exactly representable have a single encoding -- these are the ones that used
    # to match, which is why harvesting worked at all
    for exact in (1.5, 2.5, 3.0, 0.5, 1.0, 2.0):
        assert len(_f16_encodings(exact)) == 1, (exact, _f16_encodings(exact))
    # truncation must move toward zero, and must not corrupt zero
    assert _f16_encodings(0.0) == (0,)
    # values whose nearest encoding OVERSHOOTS -- these are the ones that were being lost. Only
    # about a third of values are affected, but a block needs all four to match, so roughly
    # 0.65**4 ~ 18% of blocks were identifiable. That is the yield gap this fixes.
    for x in (1.44, 1.4, 2.66, 0.828, 0.34, 0.912):
        enc = _f16_encodings(x)
        vals = [struct.unpack("<e", struct.pack("<H", e))[0] for e in enc]
        assert len(enc) == 2 and vals[1] < x < vals[0], (x, vals)
    # values already representable, or whose nearest undershoots, must stay single-encoded --
    # widening every value would double the key count for nothing and weaken the fingerprint
    for x in (1.14, 1.89, 0.76, 0.4, 0.8, 1.176):
        assert len(_f16_encodings(x)) == 1, (x, _f16_encodings(x))
    # negatives truncate toward zero too (magnitude decreases), which is a different bit direction
    enc = _f16_encodings(-1.44)
    assert len(enc) == 2
    v = [struct.unpack("<e", struct.pack("<H", e))[0] for e in enc]
    assert v[0] < -1.44 < v[1], v
    # a row must be reachable under the truncated key, which is the whole point
    row = {"u_globalColourBrightnessBase": 1.440000057220459,
           "u_globalColourBrightnessPalette": 3.0,
           "u_globalColourSaturationBase": 1.5,
           "u_globalColourSaturationPalette": 1.1399999856948853}
    assert (0x42003dc2, 0x3c8f3e00) in _fingerprints(row), [hex(a) for a, _ in _fingerprints(row)]

    # AMBIGUITY. Widening the fingerprint sends more rows into the confirm step, so `confirm` must
    # return all of them and not just the first -- otherwise two variants that agree on brightness,
    # saturation and both rotations but hold DIFFERENT seeds would silently record the wrong one.
    def row(seed, rot=0.322, rotp=-0.75, bright=(1.0, 1.5), sat=(2.0, 2.5)):
        return {"u_globalColourRotationOffsetBase": rot, "u_globalColourRotationOffsetPalette": rotp,
                "u_globalPaletteSeed": seed, "u_globalPaletteMaximumComplexity": 1,
                "u_globalColourBrightnessBase": bright[0], "u_globalColourBrightnessPalette": bright[1],
                "u_globalColourSaturationBase": sat[0], "u_globalColourSaturationPalette": sat[1],
                "ovl": "T.ovl", "fgm": f"t{seed}.fgm"}
    blk = {"hueMatrixBase": mb.hue_matrix_from_rotation(0.322),
           "hueMatrixPalette": mb.hue_matrix_from_rotation(-0.75)}
    same = [row(29), row(29)]
    assert len(confirm(blk, same)) == 2, "confirm must return every match, not the first"
    assert len({seed_pair(h) for h in confirm(blk, same)}) == 1, "same seed is not ambiguous"
    clash = [row(29), row(200)]
    assert len({seed_pair(h) for h in confirm(blk, clash)}) == 2, "disagreement must be visible"
    # a row with the wrong rotation must not confirm at all
    assert confirm(blk, [row(29, rot=0.1)]) == []

    # a never-used material slot must be rejected even though its hue matrices look valid
    assert not plausible({"gradAmplitude": [0, 0, 0], "gradFreq": [0, 0, 0]})
    assert not plausible({"gradAmplitude": [181, 211, 167], "gradFreq": [0, 0, 0]})
    assert not plausible({"gradAmplitude": [0, 65, 372], "gradFreq": [157, 256, -208]})
    # the chasmosaurus false positive: everything in range except a negative gradient offset
    assert not plausible({"gradAmplitude": [307, 307, 307], "gradFreq": [20, 476, 497],
                          "gradOffset": [192, -128, -97]})
    assert plausible({"gradAmplitude": [227, 134, 134], "gradFreq": [204, 51, 204],
                      "gradOffset": [319, 378, 103]})
    # every genuine row already harvested must survive the filter. A failure here means the table
    # holds a row this filter now rejects -- regenerate it rather than loosening the filter.
    if os.path.isfile(OUT):
        stale = [(k, r["from"]) for k, r in json.load(open(OUT)).items() if not plausible(r)]
        assert not stale, f"{len(stale)} stored rows fail the filter, delete {OUT} and re-harvest: {stale[:3]}"
    print("selftest ok")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="*", help="capture filename substring(s)")
    parser.add_argument("--sweep-table", help="bind ONE selected capture to its sweep seed table")
    parser.add_argument("--captures-dir", help="capture folder for this run")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.captures_dir:
        CAPS = os.path.abspath(args.captures_dir)
    if args.selftest:
        selftest()
    else:
        sys.exit(main(only=tuple(args.captures), sweep_table=args.sweep_table))
