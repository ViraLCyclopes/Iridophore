"""Harvest evidence handling. Does not infer or change the GPU block layout."""
import hashlib
import json
import math
import os
import tempfile

FIELDS = ('gradOffset', 'gradAmplitude', 'gradFreq', 'gradPhase')
SEED_FIELDS = ('gradOffset', 'gradAmplitude', 'gradPhase')


def signature(row, fields=FIELDS):
    return tuple(tuple(row[name]) for name in fields)


def validate(row, key=None):
    if not isinstance(row, dict):
        raise ValueError('coefficient row must be an object')
    for name in ('seed', 'complexity'):
        if type(row.get(name)) is not int or row[name] < 0:
            raise ValueError('invalid ' + name)
    if row['seed'] > 255:
        raise ValueError('seed outside 0..255')
    if key is not None and key != f"{row['seed']}_{row['complexity']}":
        raise ValueError('key does not match seed/complexity')
    for name in FIELDS:
        v = row.get(name)
        if (not isinstance(v, (list, tuple)) or len(v) != 3 or
                any(type(x) is not int or not -512 <= x <= 511 for x in v)):
            raise ValueError('invalid signed 10-bit triple: ' + name)


def read_table(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        table = json.load(fh)
    if not isinstance(table, dict):
        raise ValueError('coefficient table must be an object: ' + path)
    for key, row in table.items():
        validate(row, key)
    return table


def atomic_json(path, value):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.harvest-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(value, fh, indent=1, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def reconcile(existing, bundled, observations):
    """Reject every new observation of a contradictory seed; never choose by order.

    Incumbents are retained, with disagreements reported for manual investigation.
    Seed-only coefficients must agree across complexities. Frequency is compared only
    at equal complexity; no inferred frequency formula is used as measurement proof.
    """
    groups = {}
    for source, table in (('bundled', bundled), ('existing', existing),
                          ('observed', observations)):
        for key, value in table.items():
            for row in (value if source == 'observed' else [value]):
                validate(row, key)
                groups.setdefault(row['seed'], []).append((source, key, row))
    result, rejected = dict(existing), {}
    for seed, entries in groups.items():
        if not any(source == 'observed' for source, _, _ in entries):
            continue
        pairs = {}
        for _, key, row in entries:
            pairs.setdefault(key, set()).add(signature(row))
        conflict = (len({signature(r, SEED_FIELDS) for _, _, r in entries}) > 1 or
                    any(len(sigs) > 1 for sigs in pairs.values()))
        if conflict:
            rejected[str(seed)] = [dict(source=s, key=k, row=r) for s, k, r in entries]
            continue
        for source, key, row in entries:
            if source == 'observed' and key not in result:
                result[key] = row
    return result, rejected


def capture_mapping(path, work_dir, supplied=None):
    """Explicit, immutable sweep snapshot for one capture, never the latest sweep.

    Path, size and mtime identify the capture locally (not a cryptographic file
    identity). Replacing or moving it requires an explicit new association.
    """
    stat = os.stat(path)
    identity = [os.path.normcase(os.path.abspath(path)), stat.st_size, stat.st_mtime_ns]
    token = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    target = os.path.join(work_dir, 'capture_tables', token + '.json')
    saved = None
    if os.path.isfile(target):
        with open(target, encoding='utf-8') as fh:
            saved = json.load(fh)
    if supplied:
        with open(supplied, encoding='utf-8') as fh:
            rows = json.load(fh)
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError('sweep table must be a list of variant rows')
        numeric = ('u_globalPaletteSeed', 'u_globalPaletteMaximumComplexity',
                   'u_globalColourBrightnessBase', 'u_globalColourBrightnessPalette',
                   'u_globalColourSaturationBase', 'u_globalColourSaturationPalette',
                   'u_globalColourRotationOffsetBase', 'u_globalColourRotationOffsetPalette')
        for row in rows:
            if any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k])
                   for k in numeric):
                raise ValueError('sweep row has missing or invalid fingerprint fields')
            seed, cx = row[numeric[0]], row[numeric[1]]
            if seed != int(seed) or not 0 <= seed <= 255 or cx != int(cx) or cx < 0:
                raise ValueError('invalid sweep seed/complexity')
            if any(not isinstance(row.get(k), str) for k in ('ovl', 'fgm')):
                raise ValueError('sweep row requires ovl and fgm provenance')
        if saved is not None and saved['rows'] != rows:
            raise ValueError('capture already bound to a different sweep table')
        if saved is None:
            atomic_json(target, {'capture': identity, 'rows': rows})
        return rows
    return saved['rows'] if saved is not None else []
