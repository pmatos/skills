# Colour and shape analysis

The aim is a short, practical palette and a few shape rules that guide the shopping. It is not a diagnosis. Say what the photos show, and say where the evidence is weak.

## Colouring

Look at the daylight face photos without filters. Note:

- **Skin undertone.** Is it cool (pink or rosy), warm (golden or peachy), neutral, or olive? Check the cheeks, the neck, and how gold and silver look if visible.
- **Eyes.** Note the colour and whether it is soft or clear and bright.
- **Hair.** Note the colour at the roots and the lengths. Note whether it is ash or golden, and any highlights.
- **Contrast.** Are hair, skin and eyes close in value (low contrast) or far apart (high contrast)?
- **Evidence from clothes.** Which colours, in the photos the user sent, make the face look clear and healthy? Which make it look tired, sallow or washed out? Trust this evidence more than theory.

Map these to a seasonal family as a starting point, for example a soft, cool, light or deep variant of summer, winter, spring or autumn. Say when the person sits between two families, and choose colours that work on that border.

## The palette

Write `data/palette.json` (see `data-format.md`):

- `best`: six to nine colours with hex values. Mark the one or two strongest as the hero colours in `note`. Include one or two richer colours for festive outfits.
- `neutrals`: four to six base colours for trousers, coats and shoes.
- `avoid`: one or two sentences about colours to keep away from the face, and why.
- `summary`: two or three sentences about their colouring in plain words.

Choose hex values for real fabric colours, not screen-bright ones. Check that the swatch strip in the dashboard reads as one family.

## Shape

Use neutral words and say what works, not what is wrong. Note:

- the balance of shoulders and hips
- where the waist is and how defined it is
- which features are good to show, such as ankles or collarbones
- height and leg proportion, in broad terms only

Turn this into a few rules in `shape`, for example "Structured layers and straight trousers suit them best." Put the user's hard limits from the intake, such as "no shorts", into `rules`. The dashboard shows both.

## Checking with the user

Show the summary, the palette swatches and the shape rules before you shop. Ask:

- whether the colours feel right to the person
- which listed colours they dislike
- whether anything in the shape notes feels wrong or unkind

Change the palette when the person disagrees. Their taste matters more than the theory.
