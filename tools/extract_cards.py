#!/usr/bin/env python3
"""Pull the Pajama Man trading cards out of the game at native resolution.

The cards live in rooms.he under trading_cards/.  Each one ships three ways:

  <name>cu.mng       the close-up the game shows when you look at a card --
                     the full card art, ~294x405, this is the one you want
  <name>.mng         the 55x74 thumbnail used in the album
  <name>_hilite.mng  a highlight overlay for the album

Display names ("The Evil Underwear", "Dr. Scott Bruvvers") come from the layer
names inside cards.mng, so the output is named the way the game names them
rather than after the asset filenames.

A <name>cu.mng holds only the printed content -- title, art panel, body text --
on transparency.  About a third of it is fully transparent, including the whole
text area, because the card itself (white margin, black rounded border, light
blue body rgb(113,186,244) and drop shadow) is a separate layer, cardcu.mng,
drawn underneath.  So this writes two versions:

  fronts/      the card as the game shows it: cardcu.mng with the art composited
               on top, a uniform 329x451
  art-only/    just the <name>cu layer, transparent where the blue card shows
               through, if you want to recolour or reframe it

Extracting from the data files avoids both problems with screenshotting them:
no yellow selection arrow drawn over the art, and no recompression from the
game's print function.  What comes out is the artwork as shipped.
"""

from __future__ import annotations

import csv
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaga import he, mng, render

HERE = os.path.dirname(os.path.abspath(__file__))
# The workspace the repo sits in: the game and the card output live beside
# the repo, not inside it (see yaga_extract.py).
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "stock-game-files", "program files", "Atari")
OUT = os.path.join(ROOT, "pajama-man-cards")

# Not characters: the card frame, the close-up backdrop, the print template.
NOT_A_CARD = {"cardcu", "bg_cardcu", "print_card_cu", "bigass card"}

# cards.mng labels this one "Container Unit", but the card art itself -- and
# every other source -- says "Containment Unit".  Trust the artwork.
NAME_OVERRIDES = {
    "Portable Bad-Guy Container Unit": "Portable Bad-Guy Containment Unit",
}

EXTRAS = {
    "trading_cards/payoff_poster_open.mng": ("poster.png", -1),
    "trading_cards/cardcu.mng": ("card_frame.png", 0),
    "trading_cards/bg_cardcu.mng": ("closeup_backdrop.png", 0),
    "trading_cards/bg_trading_cards.mng": ("album_page.png", 0),
    # The print path uses its own card -- same blue and white, drop shadow
    # removed, 317x436 instead of 329x451 -- over a white page with a gray
    # dashed cut line.  The yellow arrow that lands on screenshots is a
    # separate sprite at 169,22, which is why it never touches the art.
    "trading_cards/print_card_cu.mng": ("print_card_frame.png", 0),
    "trading_cards/tra_print_dotted_line.mng": ("print_dotted_line.png", 0),
    "trading_cards/tra_white_bg.mng": ("print_white_bg.png", 0),
    "trading_cards/tra_small_arrow.mng": ("screen_yellow_arrow.png", 0),
}


def norm(s):
    """Fold to bare letters, dropping a leading article: the asset for
    "The Evil Underwear" is evilunderwearcu.mng."""
    s = re.sub(r"^the\s+", "", s.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_rooms_archive():
    for path in he.find_archives(DATA):
        if os.path.basename(path).lower() == "rooms.he":
            return path
    sys.exit("rooms.he not found under %s" % DATA)


def display_names(zf):
    """Card display names, in album order, from the layer names in cards.mng."""
    anim = mng.load(zf.read("trading_cards/cards.mng"), "cards.mng")
    names = []
    for frame in anim.frames:
        for layer in frame.layers:
            if "ignore" in layer.name.lower():
                continue
            if layer.name not in names:
                names.append(layer.name)
    return names


def match(stem, names):
    """Map an asset stem (evilunderwear) to a display name (The Evil Underwear)."""
    n = norm(stem)
    best = None
    for name in names:
        d = norm(name)
        if d == n:
            return name
        if d.startswith(n) or n.startswith(d):
            # Longest overlap wins: portablebadguycontainer vs
            # "Portable Bad-Guy Container Unit", earthquake vs "Earthquaker".
            if best is None or len(norm(best)) < len(d):
                best = name
    return best


def save(anim, path, frame_index=0):
    images, box = render.compose(anim)
    if not images:
        return None
    images[frame_index].save(path)
    return box


def main():
    path = find_rooms_archive()
    zf = zipfile.ZipFile(path)
    names = display_names(zf)
    print("%d card names from cards.mng" % len(names))

    fronts = os.path.join(OUT, "fronts")
    artonly = os.path.join(OUT, "art-only")
    thumbs = os.path.join(OUT, "thumbnails")
    extras = os.path.join(OUT, "extras")
    for d in (fronts, artonly, thumbs, extras):
        os.makedirs(d, exist_ok=True)

    # The blank card the art sits on, and where it sits on the 640x480 screen.
    blank_anim = mng.load(zf.read("trading_cards/cardcu.mng"), "cardcu.mng")
    blank_layer = blank_anim.frames[0].layers[0]
    blank = blank_layer.image
    blank_x, blank_y = blank_layer.x, blank_layer.y

    members = {i.filename for i in zf.infolist()}
    rows = []
    unmatched = []
    for member in sorted(members):
        if not member.startswith("trading_cards/") or not member.endswith("cu.mng"):
            continue
        stem = os.path.basename(member)[:-len("cu.mng")]
        if stem in NOT_A_CARD or os.path.basename(member)[:-4] in NOT_A_CARD:
            continue
        display = match(stem, names)
        if not display:
            unmatched.append(member)
            continue
        display = NAME_OVERRIDES.get(display, display)

        from PIL import Image
        anim = mng.load(zf.read(member), member)
        art_layer = anim.frames[0].layers[0]

        # As the game shows it: the blank card with the art composited on top,
        # each placed at its own screen position.
        card = blank.copy()
        card.alpha_composite(art_layer.image,
                             (art_layer.x - blank_x, art_layer.y - blank_y))
        card.save(os.path.join(fronts, display + ".png"))

        # The bare art layer, transparent where the card shows through.
        art = os.path.join(artonly, display + ".png")
        box = save(anim, art)
        w, h = Image.open(art).size

        thumb_member = "trading_cards/%s.mng" % stem
        tw = th = 0
        if thumb_member in members:
            tanim = mng.load(zf.read(thumb_member), thumb_member)
            tpath = os.path.join(thumbs, display + ".png")
            save(tanim, tpath)
            tw, th = Image.open(tpath).size

        rows.append({
            "card": display,
            "card_width": blank.width, "card_height": blank.height,
            "art_width": w, "art_height": h,
            "thumb_width": tw, "thumb_height": th,
            "source": member,
            "screen_x": box[0] if box else "", "screen_y": box[1] if box else "",
        })
        print("  %-34s %dx%-4d  <- %s" % (display, w, h, member))

    for member, (outname, frame_index) in EXTRAS.items():
        if member not in members:
            continue
        anim = mng.load(zf.read(member), member)
        if not anim.frames:
            continue
        save(anim, os.path.join(extras, outname), frame_index)
        print("  extra: %-24s <- %s" % (outname, member))

    with open(os.path.join(OUT, "cards.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n%d cards -> %s" % (len(rows), OUT))
    written = {r["card"] for r in rows}
    missing = [n for n in names if NAME_OVERRIDES.get(n, n) not in written]
    if missing:
        print("card names with no close-up asset: %s" % missing)
    if unmatched:
        print("close-ups with no card name: %s" % unmatched)


if __name__ == "__main__":
    main()
