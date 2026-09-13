# Harvesting algorithm and evidence

The GPU block decoder is unchanged. The scanner finds known brightness/saturation
fingerprints, checks both hue matrices, rejects disabled or implausible gradients,
and accepts identity only when every matching FGM agrees on seed and complexity.
These checks are correlated evidence, not mathematical proof of identity.

The new scanner examines all four byte alignments and reads 47 bytes beyond each
chunk. Every starting offset belongs to one chunk, preventing overlap duplicates.
Small half-float lookup tables prefilter brightness values before full fingerprint
and hue checks. Repeated buffer copies are not treated as independent votes.

## Swept captures: associate before harvesting

Fingerprints are reused across sweeps. Never identify an old capture using a newer
sweep's seed table. New sweep generation archives `seedsweep_seeds.json` in that
run's backup directory. This small file must be kept with the capture's records.

In the harvesting GUI, click **Associate sweep...**, select a capture, then select
the seed table used when it was taken. Harvest normally afterward. The tool stores
an immutable copy in the harvesting configuration folder, separate from the mutable
current sweep table. Association does not alter the capture or any game files.

Equivalent CLI, from this directory:

```powershell
python harvest_blocks.py frame12345 --sweep-table "D:\MySweep\seedsweep_seeds.json"
```

The selection must match exactly one capture. `--captures-dir "D:\Captures"`
overrides the capture directory for one run. Later runs reuse the saved association.
Without an association, only shipped variant fingerprints are used. Old captures
with an unknown sweep history cannot safely be attributed by guessing a table.

Association uses absolute path, file size and modification time, not a full content
hash. Moving/replacing a capture requires a new association. Users must choose the
correct historical table; the tool cannot independently prove that choice.

## Conflicts and storage

All four coefficient triples must agree for an equal seed/complexity pair. Offset,
amplitude and phase must also agree across complexities of the same seed. This
second rule follows the existing measured seed-only model; contrary observations
are retained as unresolved evidence, not forced to fit a frequency formula.

The comparison includes bundled coefficients, existing user coefficients and every
distinct result in this scan. A contradictory seed's new rows are quarantined;
existing rows remain unchanged. No first-hit or majority-vote winner is chosen.
Unresolved conflicts carry forward across runs in
`gradient_coefficients.json.harvest-report.json`, which includes source records.
Review the evidence before manually resolving a conflict; an incumbent is not
necessarily correct merely because it was recorded first. Preserve the report
before editing it. A later agreeing capture alone does not clear a contradiction.

JSON writes use a flushed temporary file and atomic replacement. Malformed existing
tables cause a failure rather than an empty-table fallback. If a capture changes
size or modification time during its scan, no coefficients are saved from the run.
Do not run concurrent coefficient imports/harvests: atomic replacement protects
against partial writes but is not a transaction across multiple writers.

Exit code 0 means the scan completed; it does not imply that any seeds were found.
Exit code 2 means non-conflicting results were saved and conflicts were quarantined.

## Verification and limits

Tool-verified: ten offline regressions cover chunk boundaries, byte alignment, EOF,
disabled blocks, ambiguity, all coefficient conflicts, cross-complexity conflicts,
persistent quarantine, immutable capture associations and failed atomic replacement.
The existing scanner, capture audit and headless GUI self-tests also pass. All 146
bundled rows pass structural validation; this does not authenticate their values.

On one 16 MiB random synthetic buffer, the new complete scanner took about 0.10 s
versus 0.27 s for the old aligned structural filter alone. This is a microbenchmark,
not a prediction of real capture throughput. No real captures were available in the
configured directory for a yield comparison during this change.

Raw scanning cannot recover compressed, omitted or transformed buffers. The
nonnegative offset/amplitude/frequency plausibility checks remain empirical
assumptions inherited from the old scanner, not a proven description of all seeds.
An unidentified or rejected block is not proof that a seed is absent. The legacy
audit uses an aligned structural scan and is diagnostic, not an exhaustive census.
Actual draw-call/resource attribution would provide stronger evidence, but is not
implemented here. Game staging/restore safety is a separate issue and is unchanged
apart from archiving each completed sweep's identification table.
