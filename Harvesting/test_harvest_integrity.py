"""Offline regressions; synthetic captures never touch game files or user tables."""
import contextlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import harvest_blocks as hb
import harvest_integrity as hi


def row(seed=29):
    return dict(u_globalPaletteSeed=seed, u_globalPaletteMaximumComplexity=1,
                u_globalColourBrightnessBase=1.5, u_globalColourBrightnessPalette=2.0,
                u_globalColourSaturationBase=2.5, u_globalColourSaturationPalette=3.0,
                u_globalColourRotationOffsetBase=0.322,
                u_globalColourRotationOffsetPalette=-0.75, ovl='Test.ovl', fgm='test.fgm')


def record(seed=29, complexity=1, offset=200):
    return dict(seed=seed, complexity=complexity, gradOffset=[offset]*3,
                gradAmplitude=[150]*3, gradFreq=[51, 102, 51], gradPhase=[100]*3)


def pack3(values):
    return sum((v & 1023) << (i*10) for i, v in enumerate(values))


def block(enabled=True, offset=200):
    r = row()
    w = [0, 0, 0x20000 if enabled else 0, 0,
         pack3(hb.mb.hue_matrix_from_rotation(r['u_globalColourRotationOffsetBase'])),
         pack3(hb.mb.hue_matrix_from_rotation(r['u_globalColourRotationOffsetPalette'])),
         *hb._fingerprints(r)[0], pack3([offset]*3), pack3([150]*3),
         pack3([51, 102, 51]), pack3([100]*3)]
    return struct.pack('<12I', *w)


class HarvestTests(unittest.TestCase):
    def test_every_alignment_boundary_and_eof_exactly_once(self):
        tab = {key: [row()] for key in hb._fingerprints(row())}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'test.rdc'
            for offset in range(128):
                path.write_bytes(bytes(offset) + block())
                for chunk in (48, 64, 128):
                    self.assertEqual([h[0] for h in hb.scan(path, tab, chunk)], [offset])

    def test_disabled_gradient_and_small_capture(self):
        tab = {key: [row()] for key in hb._fingerprints(row())}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'test.rdc'
            path.write_bytes(block(False))
            self.assertEqual(list(hb.scan(path, tab)), [])
            self.assertEqual(len(list(hb.scan(path, tab, filter_degenerate=False))), 1)
            path.write_bytes(block()[:47])
            self.assertEqual(list(hb.scan(path, tab)), [])
            with self.assertRaises(ValueError):
                list(hb.scan(path, tab, chunk=32))

    def test_each_coefficient_conflict_preserves_incumbent(self):
        for field in hi.FIELDS:
            old, new = record(), record()
            new[field][0] += 1
            saved, conflicts = hi.reconcile({'29_1': old}, {}, {'29_1': [new]})
            self.assertEqual(saved, {'29_1': old})
            self.assertIn('29', conflicts)

    def test_new_conflicts_are_order_independent(self):
        a, b = record(), record(offset=201)
        for sequence in ([a, b], [b, a]):
            saved, conflicts = hi.reconcile({}, {}, {'29_1': sequence})
            self.assertEqual(saved, {})
            self.assertIn('29', conflicts)

    def test_cross_complexity_and_bundled_conflicts(self):
        new = record(complexity=2, offset=201)
        saved, conflicts = hi.reconcile({}, {'29_1': record()}, {'29_2': [new]})
        self.assertEqual(saved, {})
        self.assertIn('29', conflicts)
        new['gradOffset'] = [200]*3
        new['gradFreq'] = [51, 153, 51]
        saved, conflicts = hi.reconcile({}, {'29_1': record()}, {'29_2': [new]})
        self.assertEqual(saved, {'29_2': new})
        self.assertEqual(conflicts, {})

    def test_invalid_schema_and_damaged_json(self):
        for key, bad in [('wrong', record()), ('29_1', dict(record(), gradPhase=None)),
                         ('29_1', dict(record(), gradFreq=[1, 2, 9999]))]:
            with self.assertRaises(ValueError):
                hi.validate(bad, key)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'bad.json'
            p.write_text('{')
            with self.assertRaises(ValueError):
                hi.read_table(p)

    def test_capture_mapping_is_explicit_and_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            p, table = Path(td)/'test.rdc', Path(td)/'seeds.json'
            p.write_bytes(block())
            table.write_text(json.dumps([row()]))
            self.assertEqual(hi.capture_mapping(p, td), [])
            self.assertEqual(hi.capture_mapping(p, td, table), [row()])
            table.write_text(json.dumps([row(30)]))
            self.assertEqual(hi.capture_mapping(p, td), [row()])
            with self.assertRaises(ValueError):
                hi.capture_mapping(p, td, table)

    def test_atomic_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'out.json'
            p.write_text('{"old": 1}')
            with patch.object(hi.os, 'replace', side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    hi.atomic_json(p, {'new': 2})
            self.assertEqual(json.loads(p.read_text()), {'old': 1})
            self.assertEqual(list(Path(td).glob('*.tmp')), [])

    def test_end_to_end_conflicting_capture(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)/'data'; data.mkdir()
            (data/'gradient_coefficients.json').write_text('{}')
            cap = Path(td)/'frame.RDC'
            cap.write_bytes(block() + block(offset=201))
            out = str(Path(td)/'out.json')
            tab = {key: [row()] for key in hb._fingerprints(row())}
            with patch.object(hb, 'CAPS', td), patch.object(hb, 'OUT', out), \
                 patch.object(hb._hpaths, 'DATA', str(data)), \
                 patch.object(hb._hpaths, 'work_dir', return_value=td), \
                 patch.object(hb, 'variant_table', return_value=tab), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(hb.main(), 2)
                # A later single-value scan must not forget the contradiction.
                cap.write_bytes(block())
                self.assertEqual(hb.main(), 2)
            self.assertEqual(hi.read_table(out), {})
            evidence = json.loads(Path(out+'.harvest-report.json').read_text())
            self.assertIn('29', evidence['conflicts'])

    def test_ambiguous_seed_is_never_banked(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)/'data'; data.mkdir()
            (data/'gradient_coefficients.json').write_text('{}')
            (Path(td)/'frame.rdc').write_bytes(block())
            out = str(Path(td)/'out.json')
            tab = {key: [row(), row(30)] for key in hb._fingerprints(row())}
            with patch.object(hb, 'CAPS', td), patch.object(hb, 'OUT', out), \
                 patch.object(hb._hpaths, 'DATA', str(data)), \
                 patch.object(hb._hpaths, 'work_dir', return_value=td), \
                 patch.object(hb, 'variant_table', return_value=tab), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(hb.main(), 0)
            self.assertEqual(hi.read_table(out), {})


if __name__ == '__main__':
    unittest.main()
