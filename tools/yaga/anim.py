"""Shared animation model for the Yaga engine's two sprite formats.

Both .mng and .rle decode to the same shape: an animation is a list of frames,
a frame is a list of layers, a layer is an RGBA image placed at (x, y).

Layer.mask is the lipsync/phoneme mask from the MNG flAG chunk (or the matching
field in .rle).  The engine draws a layer when mask == 0, or when
(mask & current_phoneme_mask) != 0 -- see Animation_Draw/is_phoneme in linyaga.

A talking character splits into an unmasked body plus masked mouth shapes named
after their phoneme, and masked head shapes that cover several of them at once,
e.g. in aqu_diver_talkie.mng: ROOT 0x1, A 0x2, EE 0x4, OH 0x8, U 0x10, C 0x20,
M 0x80, TH 0x100, F 0x200, UH 0x400, with ROOT_HEAD 0x531, STRETCH 0xA and
SQUASH 0x284 grouping them.  So picking no phoneme at all leaves the character
without a head: PHONEME_REST (bit 0) is the neutral pose to render by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PHONEME_REST = 0x1   # closed-mouth / neutral pose
PHONEME_ALL = -1     # draw every layer, phonemes stacked on top of each other
PHONEME_NONE = 0     # unmasked layers only (usually a headless character)

PHONEME_NAMES = {
    0x001: "ROOT", 0x002: "A", 0x004: "EE", 0x008: "OH", 0x010: "U",
    0x020: "C", 0x040: "?", 0x080: "M", 0x100: "TH", 0x200: "F", 0x400: "UH",
}


def layer_visible(layer, phoneme=PHONEME_REST, blink=False) -> bool:
    """The engine's rule, from is_phoneme()/Animation_Draw() in linyaga --
    plus the part linyaga does not have.

    "mask == 0 means always draw" is not the whole story.  An idle pose also
    carries BLINK1 (eyes half closed) and BLINK2 (eyes shut) as mask 0
    layers, and drawing them is how a character ends up staring out of the
    picture with their eyes glued shut.  No game script ever touches them:
    the engine blinks characters by itself, so a still frame wants them off.

    Pass blink=True to get them back -- they are the blink artwork, and worth
    having if that is what you are after.
    """
    if not blink and layer.name.upper().startswith("BLINK"):
        return False
    if layer.mask == 0:
        return True
    if phoneme == PHONEME_ALL:
        return True
    return (layer.mask & phoneme) != 0


@dataclass
class Layer:
    name: str = ""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    mask: int = 0
    image: object = None  # PIL.Image in RGBA, or None if it failed to decode
    note: str = ""        # decode warning, if any

    @property
    def is_phoneme(self) -> bool:
        return self.mask != 0


@dataclass
class Frame:
    layers: list = field(default_factory=list)

    def bbox(self, phoneme=PHONEME_REST):
        """(x1, y1, x2, y2) covering this frame's layers, or None if empty."""
        boxes = [
            (l.x, l.y, l.x + l.w, l.y + l.h)
            for l in self.layers
            if l.image is not None and layer_visible(l, phoneme)
        ]
        if not boxes:
            return None
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )


@dataclass
class Anim:
    frames: list = field(default_factory=list)
    kind: str = ""        # "mng" or "rle"
    source: str = ""      # archive member path
    notes: list = field(default_factory=list)

    def bbox(self, phoneme=PHONEME_REST):
        boxes = [b for b in (f.bbox(phoneme) for f in self.frames) if b]
        if not boxes:
            return None
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
