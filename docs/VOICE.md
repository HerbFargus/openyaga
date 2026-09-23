# Re-voicing a character with their original voice

A sequel recasts a character, and the new voice never quite sounds right.
This is a write-up of putting the old voice back: training a voice
conversion model on the character's lines from the earlier games, then
running the sequel's lines through it -- its dialogue files and the voices
buried in its cutscene soundtracks.

The worked example throughout is Pajama Sam: the voice from Pajama Sam 1-3
(1996-2001) replacing the one in Pajama Sam 4 (2003), played back through
openyaga's `--voice-pack`. Nothing in the method is specific to it. The same
steps apply to any character with a few hours of old recordings and a set of
new lines to replace.

No models, datasets or converted audio come with this document. Read the
next section before making any.

## First: whose voice is this?

A voice model is a copy of a real person's voice. That person is the voice
actor, and they did not agree to have their voice say new things. Several
jurisdictions now have laws about exactly this ("digital replica" and
voice-likeness statutes), and most RVC communities forbid sharing models of
real people made without consent.

The recordings also belong to whoever owns the games, and the retrieval
index RVC builds (below) is essentially a database of features taken
straight from those recordings.

So keep it personal. Use the model and its output on your own machine, with
games you own. Don't publish the model, the index, the dataset or the
converted lines. If you want to share results, ask the actor first. This
document is the shareable part.

## What it takes

| | |
|---|---|
| GPU | Any recent NVIDIA card with 8 GB. Measured here on an RTX 3060 Ti |
| Disk | ~5 GB for the Python environment, ~1 GB of models, a few GB of working audio |
| Time | An evening of machine time; the listening is the slow part |
| Ears | Yours. Every step that matters ends with a human listening |

The tools are all open source:

- **[Applio](https://github.com/IAHispano/Applio)** -- a maintained RVC v2
  (Retrieval-based Voice Conversion) toolkit: training and conversion.
- **[Resemblyzer](https://github.com/resemble-ai/Resemblyzer)** -- turns a
  clip into a 256-number voice fingerprint, for grouping clips by speaker.
- **[Demucs](https://github.com/facebookresearch/demucs)** -- splits a
  soundtrack into voices and everything else (music and effects).
- **ffmpeg** -- decoding. openyaga's `player/get_ffmpeg.py` fetches one on
  Windows.

### Setting up

Applio's own installer puts Miniconda in your user profile. Everything can
instead live in one folder, built with [uv](https://github.com/astral-sh/uv)
and a Python 3.12 environment:

```bash
git clone https://github.com/IAHispano/Applio
cd Applio
uv venv env --python 3.12
uv pip install --python env/Scripts/python.exe -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match
uv pip install --python env/Scripts/python.exe --no-deps resemblyzer
uv pip install --python env/Scripts/python.exe webrtcvad-wheels demucs
```

The extra index is where the CUDA build of PyTorch comes from; without it,
you get a CPU-only build that trains unbearably slowly. Set `UV_CACHE_DIR`
and `UV_PYTHON_INSTALL_DIR` to paths inside the folder if you want nothing
outside it. Resemblyzer is installed with `--no-deps` because its `webrtcvad`
dependency does not build on Windows; `webrtcvad-wheels` is the same module
prebuilt.

Two gotchas worth knowing before you start:

- **Applio needs `assets/config.json`,** which its web UI creates on first
  launch. Driven from scripts, it never exists, and every model export during
  training fails with a one-line error in the log while training carries on.
  Copy `assets/config_template.json` to `assets/config.json` first.
- **Applio downloads models on first use.** Fetch only what you need. For
  32 kHz training that is ContentVec (378 MB, reads the words out of speech),
  RMVPE (181 MB, tracks pitch) and the RVC v2 32 kHz pretrained pair (74 MB +
  143 MB), all from `huggingface.co/IAHispano/Applio`. Demucs fetches its
  `htdemucs` model (~84 MB) itself.

## The pipeline

```
old games' dialogue ─► every line as a WAV ─► group by voice ─► you pick the character
                                                                        │
                                           training set (best ~60 min) ◄┘
                                                                        │
                                                         train RVC ─────┤
                                                                        ▼
new game's dialogue lines ─────────────────────────────────────► convert ─► voice pack
new game's cutscenes ─► split voices/music ─► cut into lines ─► label ─► you review
                                                                        │
                                   convert the character's lines, remix ◄┘
```

## 1. Get the old lines out

You need the character's old recordings as individual clips. For the
Humongous SCUMM games (Pajama Sam 1-3, Putt-Putt, Freddi Fish, Spy Fox)
every line of the game is in one talkie bank, the `.HE2` file, which
openyaga's `tools/he_talkies.py` unpacks:

```bash
python tools/he_talkies.py PAJAMA.HE2 work/ps1/talkies
```

It writes one WAV per line plus an `index.csv`. Pajama Sam 1-3 came to
9,618 lines, 6 hours 13 minutes, every one 8-bit and 11 kHz. For other games
you need that game's own extractor. What matters is ending up with one
spoken line per file.

## 2. Find the character

The bank holds every character's lines, untagged. Voice fingerprints sort
them:

```python
from resemblyzer import VoiceEncoder, preprocess_wav
encoder = VoiceEncoder("cuda")
vec = encoder.embed_utterance(preprocess_wav(path))   # unit-length, 256 values
```

Embed every clip over a second long, then cluster the vectors. Agglomerative
clustering with **Ward** linkage works; average linkage on cosine distance
chains everything into one giant group. The vectors are unit length, so
Euclidean Ward tracks cosine similarity.

**Cluster each game on its own.** Clustering all three games together
grouped the clips by *game*, not by voice: each was recorded and mixed
differently, and the fingerprints hear that first. Per game, with 12 groups
each, the protagonist is the largest group or two.

Then listen. Copy the five clips nearest each big group's centre into a
folder per group and play them. Pajama Sam turned out to be 8 groups across
the 3 games, not 3: shouting, talking and whispering Sam land in different
groups. The fingerprints do the sorting; only a person can say which groups
are the character.

## 3. Build the training set

More is not better. Past about an hour, RVC improves little and trains
slower. Within each game:

1. Average the chosen groups' vectors into the character's centre.
2. Rank the clips by closeness to it, and drop the least similar 10%: those
   are stray other voices and effects that fell into the groups.
3. Keep the most central clips up to the game's share.

Pajama Sam used 20 minutes from each game: 985 clips, 60 minutes, balanced so
no one recording session dominates. Save them as 16-bit WAV at their own
sample rate; Applio resamples.

## 4. Train

Applio's three steps -- preprocess, extract, train -- can run from its
scripts without the web UI:

```bash
python rvc/train/preprocess/preprocess.py logs/NAME DATASET 32000 8 Automatic False False 0.7 3.0 0.3 none
python rvc/train/extract/extract.py logs/NAME rmvpe 8 0 32000 contentvec None 2
python rvc/train/train.py NAME 25 300 rvc/models/pretraineds/hifi-gan/f0G32k.pth \
    rvc/models/pretraineds/hifi-gan/f0D32k.pth 0 8 32000 True True False False HiFi-GAN False
python rvc/train/process/extract_index.py logs/NAME Auto
```

- **Sample rate:** match what the old recordings actually contain. 11 kHz
  source audio has nothing above 5.5 kHz, so a 48 kHz model only learns
  silence up there. 32 kHz was the right choice here. The catch is that the
  output is as muffled as the originals, which is arguably authentic.
- **How long:** watch the generator loss in the log. Here it bottomed out at
  epoch 60 and barely moved after. Epoch 100 is the model in use; past
  ~200 epochs on an hour of data, RVC tends to turn metallic rather than
  better. On the 3060 Ti, an epoch of 1,588 three-second slices took 1.5 to
  2.5 minutes.
- **The index** is built from the extracted features, not the model, so
  it can be made while training runs.
- **Training holds the GPU.** Converting while it trains crawled at 3 lines
  in 10 minutes, and took 1.5 seconds a line once training stopped. Stop
  training to test, then run it again: Applio picks up from its latest
  checkpoint.

If a snapshot export failed (the `config.json` gotcha), the full checkpoint
`logs/NAME/G_2333333.pth` is still there, and Applio's
`rvc.train.process.extract_model.extract_model` turns its `model` state into
the small inference model.

## 5. Choose settings by ear

Three settings matter, and the only way to choose them is side by side:

| Setting | What it does | Used here |
|---|---|---|
| **pitch** | semitones to shift the new actor's pitch | **-4** |
| **index rate** | how hard to pull toward real snippets of the old voice (0-1) | **0.75** |
| **protect** | how much of the new recording's breath and consonants to keep (0-0.5) | **0.2** |

**Pitch can be measured.** RVC keeps the *input's* pitch line, only shifted,
so match the two voices' median pitch:

```python
shift = round(12 * log2(old_median_hz / new_median_hz))   # 289 Hz vs 367 Hz -> -4
```

Take the old median from training's own pitch track
(`logs/NAME/f0_voiced/*.npy`), and the new one from a sample of the lines
to convert (`librosa.pyin`).

For the rest, render the same eight lines several ways -- index 0.5 and 0.75,
protect 0.2 and 0.33, pitch -3/-4/-5 -- on one page with the new actor's
original in the first column, and pick. The higher index was "a little
closer to the original", which settled it.

## 6. Convert the dialogue

Run every line through with the chosen settings. RVC keeps a line's timing,
so lip-sync and subtitle timing still fit: converted lines came out within
13 ms of the originals. Then check for silent outputs, clipping and lengths
that drift.

The last check is someone listening. Expect some lines to fail outright, and
decide early that a failed line falls back to the new actor rather than
being fought. In Pajama Sam 4, 833 of 839 lines were kept:

- **Sounds the old voice never made.** "Ah HAH!", a sub-second squeal far
  above anything in the training data, garbled in every setting and with
  every pitch tracker. No setting teaches the model a sound it never heard.
- **The character doing a voice.** Sam's heroic Pajama Man impression garbled
  in places too. Splitting the clip in two with a speech separation model
  (SpeechBrain's SepFormer) didn't help: both halves scored equally Sam-like,
  so it was one voice with an effect on it, not two people.

And one limit to accept going in: **RVC copies the input's pitch line.** The
original Sam's voice cracks upward about 2½ times as often as the new
actor's. Those cracks are pitch, so they cannot come through. What comes out
is the old voice's timbre with the new actor's performance. Editing
synthetic cracks into the pitch line before conversion was tried; it did not
sound better.

Keep a list of which lines you left out, so a re-run doesn't bring them
back.

## 7. Convert the cutscenes

Movie soundtracks mix every character with the music and effects, and a
converter fed that mix garbles everything in it. The approach is to take out
the character's lines, convert only those, and put everything back.

**Split the voices from the music.** Demucs with `--two-stems vocals` gives
a voices track and a music-and-effects track, which add back up to very
nearly the original:

```bash
python -m demucs -n htdemucs --two-stems vocals -d cuda -o separated soundtrack.wav
```

**Find the character.** Build a reference fingerprint for every speaker,
from the *new* game's own dialogue (averaging ~60 of each speaker's lines,
if the dialogue is sorted by speaker, as Pajama Sam 4's is), so the movies
are matched against the same actors. Then:

1. **Survey:** fingerprint each movie's voices track in overlapping 1.6 s
   windows to see which movies have the character at all. It needs the
   voices track: on the original soundtracks, the music hid most of Sam
   (8 s of him found in the intro, against 58 s once the music was out).
2. **Cut into lines** at the pauses (`librosa.effects.split`, 32 dB below
   peak, joining gaps under 0.25 s), and label each piece by its nearest
   speaker, with the runner-up and how close they were.
3. **Review by hand.** One page per movie: each piece's voice alone, the
   same moment with music, the proposed label, and Convert / Keep / Mixed.
   Pieces where the top two guesses were close get highlighted. Choices
   save in the browser and download as JSON.

**Hand cuts are normal.** Two characters often speak without a pause between
them, and the piece has to be cut by hand -- it happened in 12 of 23 movies.
Pitch usually shows where: print it in 0.2 s steps through the piece. An
adult's voice sits around 100-200 Hz, a child's 300-500 Hz, and a gap where
the pitch vanishes is the natural cut. Offer three or four candidate cut
times as before/after clips, and let the listener choose. When pitch
doesn't separate the voices (two children, or singing), cut the piece at
every silence into lettered chunks and ask which chunks are the character.
Sound effects that leak into the voices track (a zipper, slurps, squeaks)
get cut out the same way and kept as they are.

A short piece that was ambiguous usually fingerprints clearly once it is cut
on its own, which is a good check on a cut. And **don't trust the survey's
zeros:** listening through the movies it scored as having no Sam found him
in four more.

**Rebuild.** For each piece marked Convert:

1. Cut it from the voices track with 50 ms of padding each side -- but no
   padding across a hand cut, where it would reach into the other speaker.
2. Convert it, resample to the track's rate, and scale it to the original
   piece's loudness (RVC normalises its output).
3. Lay it back in place with a 20 ms crossfade at each end.

Then add the music track back, and write the result in the movie's own
format. Every soundtrack should come out exactly as long as the original.

For Pajama Sam 4: 34 of the 41 movies have sound, 23 have Sam, and 113 of
his lines were converted, about four minutes.

## 8. Play it

openyaga plays a voice pack with no change to the game:

```bash
python run_game.py --voice-pack DIR
```

`DIR` mirrors the game's own paths. `DIR/talkies/sam/pj4pc_sam_00055.wav`
replaces `talkies/sam/pj4pc_sam_00055.mp3`, and `DIR/movies/pj_intro.wav`
replaces the soundtrack of `movies/pj_intro.da2` (the picture still comes
from the Bink file). Any line the pack lacks plays as shipped, which is how
the failed lines fall back to the original. See
[player/README.md](../player/README.md).

## Adapting it

Nothing above depends on Pajama Sam.

### Putt-Putt

Putt-Putt was recast for Pep's Birthday Surprise, too, and it is the closest
fit, because openyaga already plays that game (`--game pbs`):

- **The old voice** comes from the SCUMM-era Putt-Putt games, which keep
  their dialogue in the same kind of `.HE2` talkie bank as Pajama Sam 1-3,
  so `tools/he_talkies.py` extracts them as in step 1. Cluster each game on
  its own, and pick Putt-Putt's groups by ear.
- **The new lines** are in Pep's Birthday Surprise's `talkies.he`, a zip
  archive with one folder per speaker. Putt-Putt has his own folder,
  `putt-putt/`, with 1,356 lines, so no speaker sorting is needed on that
  side. The other folders (`kibble/`, `marvin/`, `hank/` and so on) are the
  reference voices for labelling its movies.
- **The voice pack** mirrors that game's paths, e.g.
  `DIR/talkies/putt-putt/p7pc_putt-putt_00009.wav`, and plays with
  `run_game.py --game pbs --voice-pack DIR`.

Putt-Putt is a car with a cartoon voice rather than a child, so expect a
different pitch shift. Measure it the same way.

### Anything else

- **Other Humongous characters** (Freddi Fish, Spy Fox) have the same kind
  of talkie banks.
- **Other games** need an extractor for their dialogue and a way to play
  replacement files back. The middle -- fingerprints, training, settings,
  review -- is the same.
- **Different source quality** changes one choice: train at the sample rate
  the old recordings really have.
- **Less data** works: RVC is usable from about 10 minutes of clean speech.
  The more varied it is (shouting, whispering, laughing), the fewer lines
  will fail.

What can't be automated is the listening. The tools narrow thousands of
clips down to a few dozen decisions, and each of those decisions was made by
someone who knew what the character should sound like.
