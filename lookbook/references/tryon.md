# Try-on photos with Codex

## Why editing works and generating does not

In the first run, fully generated images, which showed the person three times in one picture, drifted visibly from their face and figure. The user found them not useful. Editing the person's own photo keeps the face, body, pose and room, and changes only the clothes.

Codex's image tool takes only a few reference images. With more than three, images were dropped or collaged differently on every run. So every job sends exactly three images:

1. the base photo for the pose (`photos/<pose>.jpg`)
2. the face close-up (`photos/face.jpg`)
3. the outfit's product sheet (`sheets/<OUTFIT>.jpg`), with numbered panels

`lookbook.py prompts` builds the sheet and the prompt. `lookbook.py tryon` runs:

```bash
codex exec --skip-git-repo-check -C <dir> -s workspace-write \
  -i photos/<pose>.jpg -i photos/face.jpg -i sheets/<OUTFIT>.jpg -- "<prompt>"
```

The prompt tells Codex to copy the final PNG to `tryon/<OUTFIT>_<pose>.png`. The log goes next to it, in `tryon/<OUTFIT>_<pose>.log`.

## Base photos

- Full body, head to feet, plain background, even daylight.
- Fitted, plain clothes, so that new clothes can replace them cleanly.
- The same framing for every pose. The dashboard skips any result whose shape differs from its base photo by more than 12 percent, because that usually means Codex cropped or recomposed the image.
- Name anything that must stay, such as a watch or glasses, in `keep` in `lookbook.json`. Name anything that must change, such as socks that the shoes replace, in `base_note`.

## Writing good styling text

The `styling` field of an outfit goes into the prompt as "How it is worn". Make it concrete:

- Say tucked, half-tucked or loose for tops.
- Say open or closed for cardigans, shirts and jackets, and how many buttons are open at the collar.
- Say rolled or full length for trousers.
- Say which layer is on top.

Rules that apply to every outfit, such as necklines, go in `rules` in `lookbook.json`, not in each outfit.

## Reviewing results

Look at every image. Crop the face and view it at full size, because small differences are invisible in a thumbnail:

```bash
magick tryon/CA1_front.png -crop 40%x22%+30%+2% +repage /tmp/face_check.png
```

Adjust the crop to where the face is in the base photo. Check:

- **Face.** Is it the same person, with the same expression, skin and hair? Reject any change.
- **Body.** Is the body the same shape and size? Reject slimming or reshaping.
- **Garments.** Do colour, fabric, length and neckline match the product sheet? Is anything from a panel's model, such as a bag or scarf, wrongly added?
- **Rules.** Does every rule hold? Necklines are the most common failure: collars come out buttoned up and V-necks come out shallow.
- **Shoes and background.** Are they right, and is the room unchanged?

To redo a job, make `styling` more precise, then:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/lookbook.py" reject <dir> SC6_front SC6_threequarter
python3 "${CLAUDE_SKILL_DIR}/scripts/lookbook.py" prompts <dir> SC6
python3 "${CLAUDE_SKILL_DIR}/scripts/lookbook.py" tryon <dir> SC6_front SC6_threequarter
```

`reject` keeps the old images in `archive/rejected/` for comparison.

## Shared basics in photos

When outfits share basics (see `data-format.md`), basics with `in_photo: true` are added to every sheet, so the shoes appear in every photo. When any basic has `in_photo: false`, the prompt says that the person wears no coat or jacket. To show the basics together, add an extra outfit such as `BASICS` with a simple outfit plus the outer layer, try it on, and set `"photo": "BASICS_front"` in `basics.json`. Use it as a rough check of proportions, such as where a long cardigan ends under a coat. It is not a fitting.

## Cost and time

Each job takes a few minutes and uses Codex credits. Four jobs in parallel worked well. Run `tryon` in the background, and do not wait in a sleep loop. `tryon` skips jobs whose output exists, so it is safe to run again after a failure.
