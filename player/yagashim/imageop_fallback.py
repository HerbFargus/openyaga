"""imageop.scale, for Python 2.7 builds that leave imageop out.

The game imports imageop in utility.py and uses one function of it: scale,
to shrink the room photo into a save's thumbnail (ScaleImage, from
saveload.py).  imageop is an old C module that 64-bit builds may omit --
conda-forge's Linux Python 2.7 does -- and then the game cannot even start,
since the import is at the top of utility.py.

run_game.py installs this as `imageop` only when the real one is missing.
It is CPython's imageop.scale, nearest-neighbour, pixel for pixel:

    oix = ix * x / newx;   oiy = iy * y / newy;
"""


def scale(image, psize, width, height, newwidth, newheight):
    if psize not in (1, 2, 4, 3):
        raise ValueError("Size should be 1, 2 or 4")
    if len(image) != width * height * psize:
        raise ValueError("String has incorrect length")
    row = width * psize
    out = []
    for iy in range(newheight):
        base = (iy * height // newheight) * row
        for ix in range(newwidth):
            start = base + (ix * width // newwidth) * psize
            out.append(image[start:start + psize])
    return "".join(out)
