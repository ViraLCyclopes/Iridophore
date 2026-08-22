"""Lossless-enough editor model for dinosaur layer and swatch FGMs.

The editor owns only attribute value text and texture array indices. Unknown XML
nodes are retained so newly discovered shader fields survive an edit/save cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import xml.etree.ElementTree as ET


SUPPORTED = {"DinosaurLayered_Layer", "DinosaurLayered_Swatch_Opaque"}

MEANINGS = {
    "pDiffuseContrast": ("confirmed", "Per-layer diffuse contrast around perceptual luma."),
    "pDiffuseSaturation": ("confirmed", "Per-layer diffuse saturation."),
    "pGlobalColouringWeight": ("confirmed", "Weight/veto for global variant recolouring; 0 protects the swatch."),
    "pHeightBlendScaleA": ("confirmed", "Weight of accumulated previous height in the layer blend."),
    "pHeightBlendScaleB": ("confirmed", "Weight of incoming layer height in the layer blend."),
    "pHeightOffset": ("confirmed", "Baseline height; JWE3 shader applies value * 0.01."),
    "pHeightScale": ("confirmed", "Swatch height amplitude, also normalised by reciprocal maximum UV tile."),
    "pRemapLutIndex": ("confirmed", "Remap-LUT row; -1 disables the remap."),
    "pUVEnableProjection": ("confirmed", "0 uses mesh UVs; 1 uses three rotated projection planes blended by sharpened object-normal weights."),
    "pUVOffset": ("confirmed", "UV offset before tiling."),
    "pUVRotationAngle": ("confirmed", "Rotation as a fraction of 180 degrees."),
    "pUVRotationPosition": ("confirmed", "Rotation pivot; shader uses (x, y - 1)."),
    "pUVTile": ("confirmed", "UV repetition count; larger values produce smaller details."),
    "pEnablePainterObjectSpace": ("inferred", "Switch for painter/object-space data used by global material effects."),
    "pAshColour": ("inferred", "Tint used by the global ash material effect."),
    "pAshSmoothStepMax": ("inferred", "Upper edge of the ash response transition."),
    "pAshSmoothStepMin": ("inferred", "Lower edge of the ash response transition."),
    "pGlobalEffectModifier": ("inferred", "Allows global environmental material effects on the swatch."),
    "pLayered_AshUpwards": ("inferred", "Up-facing bias for ash accumulation."),
    "pLayered_AshWeight": ("inferred", "Swatch ash contribution."),
    "pMaximumDustAmount": ("inferred", "Maximum dust response."),
    "pMaximumPorosity": ("inferred", "Porosity ceiling used by weathering/material effects."),
    "pMaximumSnowAmount": ("inferred", "Maximum snow response."),
    "pSnowOnSlopesOffset": ("inferred", "Slope threshold offset for snow."),
    "pSnowOpacity": ("inferred", "Snow opacity multiplier."),
    "pPerturbationViewFlag": ("unresolved", "View/perturbation mode flag; exact bit semantics not traced."),
}


@dataclass
class Attribute:
    name: str
    dtype: str
    value: str


@dataclass
class Texture:
    name: str
    dtype: str
    dependency: str
    array_index: int


class MaterialFgm:
    def __init__(self, path, tree):
        self.path, self.tree = path, tree
        self.root = tree.getroot()
        self.shader = self.root.get("shader_name", "")

    @classmethod
    def load(cls, path):
        obj = cls(path, ET.parse(path))
        if obj.shader not in SUPPORTED:
            raise ValueError("unsupported material FGM shader %r" % obj.shader)
        return obj

    def attributes(self):
        return [Attribute(n.get("name", ""), n.get("dtype", ""),
                          (n.findtext("value") or "").strip())
                for n in self.root.findall("./attributes/attribinfo")]

    def textures(self):
        out = []
        for n in self.root.findall("./textures/textureinfo"):
            ti = n.find("./value/texindex")
            out.append(Texture(n.get("name", ""), n.get("dtype", ""),
                               (n.findtext("dependency_name") or "").strip(),
                               int(ti.get("array_index", "0")) if ti is not None else 0))
        return out

    def set_attribute(self, name, value):
        for n in self.root.findall("./attributes/attribinfo"):
            if n.get("name") == name:
                n.find("value").text = value.strip()
                return
        raise KeyError(name)

    def set_texture_index(self, name, index):
        for n in self.root.findall("./textures/textureinfo"):
            if n.get("name") == name:
                n.find("./value/texindex").set("array_index", str(int(index)))
                return
        raise KeyError(name)

    def save(self, path=None):
        path = path or self.path
        ET.indent(self.tree, space="\t")
        self.tree.write(path, encoding="utf-8", xml_declaration=False)
        self.path = path
        return path

    def clone(self):
        return MaterialFgm(self.path, copy.deepcopy(self.tree))


def meaning(name):
    return MEANINGS.get(name, ("unresolved", "Preserved exactly; shader role has not been mapped."))


def validate_value(dtype, text):
    """Return canonical whitespace-separated text or raise ValueError.

    FGM XML is permissive enough that a typo otherwise survives Save and only fails later during
    Cobra injection. Validate at the editor boundary while still retaining every unknown field.
    """
    values = text.replace(",", " ").split()
    kind = dtype.rsplit(".", 1)[-1].upper()
    counts = {"FLOAT": 1, "FLOAT_2": 2, "FLOAT_3": 3, "FLOAT_4": 4,
              "INT": 1, "BOOL": 1}
    expected = counts.get(kind)
    if expected is not None and len(values) != expected:
        raise ValueError("%s requires %d value(s), got %d" % (dtype, expected, len(values)))
    if kind == "BOOL":
        if values[0].lower() in ("true", "1"): return "1"
        if values[0].lower() in ("false", "0"): return "0"
        raise ValueError("BOOL must be 0/1 or true/false")
    if kind == "INT":
        return str(int(values[0], 0))
    if kind.startswith("FLOAT"):
        [float(v) for v in values]
    return " ".join(values)
