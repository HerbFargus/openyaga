# Pajama Sam 4 XML data

The game's data files are 137 XML documents: 110 under `rooms/`, 17 under
`menus/`, 10 under `data/`. They are plain text, so nothing here is *decoded*
— what follows is the schema, and what each element actually does.

The room and menu files declare a schema that was never shipped:

```xml
<room xmlns="x-schema:room_layout.xsd" value="scene_bedroom">
```

There is no `room_layout.xsd` or `menu_layout.xsd` on the disc. Two better
sources survive, though, and this document is built from both:

- **the loader classes**, recovered from the executable
  (`python_shared/adventure/xml_loader_classes.py`), where each tag is a class
  whose `__init__` defaults *are* the permitted children;
- **`data/proposal.xml`**, a developers' design document for the inventory
  schema, left on the disc and annotated with its own defaults and
  requirements.

## Two idioms in one game

Most documents put the payload in a `value` attribute, one element per field:

```xml
<scene>
    <name value="bedroom"/>
    <module value="scene_bedroom"/>
    <class value="C_SCENE_Bedroom"/>
</scene>
```

The dialogue script does the ordinary thing instead:

```xml
<talkie speaker="SAM" file="pj4pc_sam_00031a.mp3" text="Gee! That was an exciting episode!"/>
```

They are read by different code, which is presumably how that happened.

## How the room loader reads a document

Every tag maps to a `C<Name>Tag` class. `__init__` sets a default for each
permitted child, and `SetData` fills it in:

```python
def SetData(self, attr, data):
    if attr in self.c_SpecialMemberFns.keys():
        data = self.c_SpecialMemberFns[attr](data)
    if type(self.__dict__[attr]) == type([]):
        self.__dict__[attr].append(data)
    else:
        self.__dict__[attr] = data
```

So **a default of `[]` means the element may repeat** and anything else means
it may appear once. `c_SpecialMemberFns` holds per-field converters — that is
where `boundingRect` becomes a rectangle and `delay` becomes a number.
`Build()` then constructs the runtime object.

That makes the schema readable straight out of the code:

| tag class | repeatable children | single children |
|---|---|---|
| `CRoomTag` | `aSprites`, `ambientSounds`, `ambients`, `characters`, `clickpoints`, `doors`, `inventories` | `background`, `interfaceFlag`, `name`, `roomName` |
| `CClickpointTag` | `animations`, `clickpoints`, `newboundingRect`, `region`, `soundTags` | `behavior`, `boundingRect`, `frameDelay`, `name`, `offset`, `order` |
| `CCharacterTag` | `animations` | `animMode`, `animSpeed`, `behavior`, `derivedclass`, `displayed`, `name`, `order` |
| `CAmbientTag` | `animations` | `active`, `animMode`, `animSpeed`, `behavior`, `delay`, `derivedclass`, `displayed`, `name`, `order`, `rootAnim`, `sequential` |
| `CDoorTag` | `region` | `boundingRect`, `cursorDirection`, `name`, `nextRoom` |
| `CASpriteTag` | — | `active`, `derivedclass`, `image`, `name`, `opacity`, `order` |
| `CSoundsTag` | `sound` | `name` |
| `CAmbientSoundTag` | — | `callback`, `maxDelay`, `minDelay`, `name`, `pan`, `path`, `type` |
| `CRoomMusicTag` | `songInfo` | `name`, `startNew`, `usePads` |
| `CPadsMusicTag` | `path` | `name` |
| `CIfaceTag` | `aSprites`, `characters` | `background`, `base_order`, `default_button`, `init_delta`, `name` |

**Every element in the 39 shipped room documents is one the loader knows.**
Nothing in the data is unexplained. The traffic runs the other way: the loader
accepts a number of things the game never uses.

| tag | accepted, never used in shipped data |
|---|---|
| `<room>` | `interfaceFlag`, `inventories`, `roomName` |
| `<clickpoint>` | `clickpoints` (nesting), `newboundingRect`, `offset` |
| `<ambient>` | `active`, `animMode`, `animSpeed`, `behavior`, `derivedclass`, `displayed`, `sequential` |
| `<asprite>` | `opacity` |
| `<ambientSound>` | `callback` |

## The documents

| root | files | what it is |
|---|---|---|
| `<preload>` | 71 | per-room preload lists (`*_pre.xml`, `*_post.xml`) |
| `<room>` | 39 | room layout |
| `<menu>` | 17 | menu and dialog layout |
| `<act>` | 3 | the dialogue script |
| `<inventory_items>` | 3 | inventory, plus the design proposal |
| `<scenes>` | 1 | the scene registry |
| `<music>` | 1 | room music |
| `<fonts>` | 1 | bitmap fonts |
| `<credits>` | 1 | end credits |

### `data/scenes.xml` — the scene registry

36 entries, each binding a scene name to the Python module and class that
implement it. This is how a room name in the data reaches code:

```xml
<scene>
    <name value="bedroom"/>
    <module value="scene_bedroom"/>
    <class value="C_SCENE_Bedroom"/>
</scene>
```

Loaded by `g_SceneManager.LoadScenes('data/scenes.xml')`.

### `rooms/<name>/<name>.xml` — room layout

The room's contents, in the vocabulary tabulated above. A clickpoint pairs
each animation with the sounds that go with it, and carries the rectangle you
have to be inside to click it:

```xml
<clickpoint value="Fishtank">
    <animations value="rooms/bedroom/clickpoints/bed_fishtank1.mng"/>
        <sounds value="bdrmfishtank_aljee">
            <sound frame="1" name="rooms/bedroom/bdrmfishtank_aljee"/>
        </sounds>
    <boundingRect x="570" y="190" width="200" height="160"/>
    <order value="10"/>
    <behavior value="unique"/>
</clickpoint>
```

`behavior` picks the subclass in `clickpoint.py`: `unique` plays one animation
at a time, `multiple` cycles a pick-list, `sequential` steps through in order,
`concurrent` allows one of each at once. `order` is the z position.

Characters name a `derivedclass`, which is the Python class that drives them;
doors carry a `nextRoom` and a `cursorDirection`, which is the compass cursor
you see hovering an exit.

### `rooms/<name>/<name>_pre.xml` and `_post.xml` — preloading

Flat lists of what to load before and after a room appears:

```xml
<preload>
    <animations value="rooms/bedroom/animation/sam/bed_sam_root_cape.mng"/>
    <image value="..."/>
    <background value="..."/>
</preload>
```

1,097 `<animations>` entries across 71 files.

### `data/script/pajamasam4_script.xml` — the dialogue

217 KB, and the most useful document in the game: **300 scenes, 753 events and
1,212 talkies, each with its speaker, its audio file and its full subtitle
text.**

```xml
<act>
  <scene name="TV_ROOM" id="INTRO">
    <event name="pj man show dr. grime">
      <talkie speaker="DRGRIME" file="pj4pc_drgrime_00001a.mp3"
              text="Drat! You have outwitted me again, Pajama Man!"/>
    </event>
  </scene>
</act>
```

By line count the speakers are SAM (792), GUARD (47), GRANDMA (45), SPONGE
(32), FARMER (29) and a long tail.

An `<event>` may hold several talkies and an `<option type="...">` saying how
to choose between them on repeat visits: `OR_SEQUENCE` (61 uses) works
through them in order, `OR_RANDOM` (44) picks at random. This is what makes a
character say something different the second time you click them.

Two mismatches between the script and its loader, both harmless:

- `CScriptHandler.StartElement` reads `direction` and `condition` as
  *attributes of `<talkie>`*. No talkie in the shipped script has either.
  What the script does have is 37 `<direction value="..."/>` *elements*
  (`"turning to look at it"`), which the loader never looks at — they are
  stage directions for the voice session, not data.
- `<scene>` carries an `id` (`"INTRO"`, `"SAM'S BEDROOM"`) which the loader
  ignores; only `name` is used, as the dict key.

The other two `<act>` documents are `sam_audition_script.xml` and
`sam_test_script.xml` — casting and test material, left on the disc.

### `data/inventory_items.xml` — the inventory

70 items. Each names its owners — an "owner" being where the item currently
is, with the image to draw there:

```xml
<ownerList>
    <owner name="inventory" value="interface/peanut_float.mng"/>
    <owner name="cursor" value="interface/cursors/peanut.mng"/>
</ownerList>
```

with `invAnims` (`enter`, `float`, `preview`, `exit`), a `defaultOwner`, and
optional `randomResourceList` / `randomOwnerList` for items whose location
varies between playthroughs — which is how the cape ends up somewhere
different each game.

`inventory_items_e3.xml` is a cut-down set for the E3 demo build.

### `data/proposal.xml` — the schema, documented by its authors

Not a data file: a **design document**, annotated throughout, that survived
onto the disc. It describes the inventory schema with its defaults and
requirements stated outright —

```xml
<!-- NOTE:  All tags would be optional unless noted -->
<missing value="interface\missing.mng"/>
<!-- REQUIRED -->

<itemState value="untouched"/>
<!-- untouched is default -->
<!-- other states:	pickedUp, used, lost, stolen, found, recovered -->
```

— and includes features that never shipped: `dependentItems` ("need to have
these items first before you can get this item"), `memberOfGroup`,
`trackHowMany`, `cursorShift`, and an open question in a comment
(`"what should default be? 0 and 0? Or maybe -320 and -240?"`).

It is **not well-formed**: `<onlyOnGamePath>` on line 76 is never closed, so a
parser stops there. It was never meant to be loaded.

### `menus/*.xml` — menus and dialogs

17 documents, 147 buttons. Each button carries a `background` animation, a
`rollover_frame`, a `flash_frame` and `flash_on_click`; menus carry a
`base_order` and a `text_style` naming font, point size, bold, colour and
kerning. `radio_group`/`includes` ties option buttons together.

### `data/music.xml`, `data/fonts.xml`, `data/credits.xml`

`music.xml` ships its own explanation, in a comment at the top:

> Here's how the music works: we can specify pad lists, then individual rooms
> can use these pads (in the "usePads" tag).

A room either uses named pad lists or adds `songInfo` entries of its own; a
`type` of `theme` stops the music when you leave the room, and `startNew`
stops whatever was playing and begins again.

`fonts.xml` binds six bitmap fonts to a `.mng` and an `ascii_data` range
(`minChar`, `maxChar`, `spaceChar`, `baselineChar`).

`credits.xml` holds 38 credit pages of `titleText` and `itemText`, plus two
named formats (font, colour, justification, position).

## Shipped oddities

- **Two documents do not parse.** `data/proposal.xml` (the design document
  above) and `rooms/finale/finale_preold.xml`, which has an invalid token at
  line 21.
- **Six `*old*.xml` leftovers** sit beside their replacements —
  `bedroom_postold.xml`, `bedroom_preold.xml`, `clean_sock_drawer_postold.xml`,
  `finale_preold.xml`, `putty_cutscene_preold.xml`, `tv_room_preold.xml`.
  Nothing references them.
- The XML is hand-formatted with tabs and comments throughout, including
  working notes. These are working files, shipped as they were.
