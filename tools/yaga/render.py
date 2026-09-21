"""Turn a decoded Anim into images on disk."""

from __future__ import annotations

from PIL import Image

from .anim import Anim, PHONEME_REST, layer_visible


def visible_layers(frame, phoneme=PHONEME_REST):
    return [l for l in frame.layers if l.image is not None and layer_visible(l, phoneme)]


def compose(anim: Anim, box=None, phoneme=PHONEME_REST, pad=0):
    """Composite every frame onto a shared canvas.

    Returns (images, box).  A shared canvas keeps sprites registered across
    frames, which is what you want for a sheet or an animation.
    """
    if box is None:
        box = anim.bbox(phoneme)
    if box is None:
        return [], None
    x1, y1, x2, y2 = box
    w, h = max(1, x2 - x1 + pad * 2), max(1, y2 - y1 + pad * 2)
    out = []
    for frame in anim.frames:
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for layer in visible_layers(frame, phoneme):
            canvas.alpha_composite(layer.image, (layer.x - x1 + pad, layer.y - y1 + pad))
        out.append(canvas)
    return out, box


def sheet(images, columns=None, background=(0, 0, 0, 0)):
    """Lay frames out in a grid, roughly square unless `columns` is given."""
    if not images:
        return None
    n = len(images)
    if not columns:
        columns = max(1, int(n ** 0.5 + 0.5))
    rows = (n + columns - 1) // columns
    w, h = images[0].size
    out = Image.new("RGBA", (w * columns, h * rows), background)
    for i, im in enumerate(images):
        out.paste(im, ((i % columns) * w, (i // columns) * h))
    return out


def save_apng(images, path, fps=15):
    if not images:
        return False
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=int(1000 / fps), loop=0, disposal=2)
    return True


def save_gif(images, path, fps=15):
    """GIF with a single transparent index; alpha is thresholded, not blended."""
    if not images:
        return False
    frames = []
    for im in images:
        alpha = im.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
        p = im.convert("RGB").quantize(colors=255, method=Image.Quantize.FASTOCTREE)
        p.paste(255, mask=alpha.point(lambda a: 255 - a))
        pal = p.getpalette() or []
        pal = (pal + [0] * 768)[:768]
        pal[255 * 3:255 * 3 + 3] = [0, 0, 0]
        p.putpalette(pal)
        p.info["transparency"] = 255
        frames.append(p)
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=int(1000 / fps), loop=0, disposal=2, transparency=255)
    return True
