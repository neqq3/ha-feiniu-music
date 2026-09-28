# Frontend asset provenance

The layout was measured from the user's accessible FeiNiu Music web UI: sidebar,
album grids, album/artist/playlist details, floating transport bar and lyrics view.
The HA card implements those views using HA media browsing and the existing queue
APIs. It does not embed or execute the vendor's application bundle.

Navigation and transport controls are now hand-authored in `card-icons.js`, using
standard music-player symbols, a 24-unit grid, rounded strokes and solid transport
shapes. They were constructed from basic geometry rather than extracted or traced
from vendor SVGs. The former copied-path module has been removed from the candidate
and its build. Historical reference material remains outside this repository.

The separate brand mark in `card-brand.js` and HA `brand/icon.png` / `icon@2x.png`
comes from the existing colour/monochrome SVG redraw based on the FeiNiu Music app
icon. The project owner confirms these reference SVGs were drawn for their own
provider project and explicitly elects to retain the mark. It is a brand-referential
adaptation, not one of the independent navigation/transport icons above. Redrawing
does not establish permission to redistribute the original brand design, and this
project does not claim that permission, official endorsement, or an Apache-2.0 grant
over third-party brand rights. The same mark also exists in early Git history.

Montserrat is independently distributed under SIL OFL 1.1. Its Latin variable subset
is embedded in `card-font.js`, avoiding runtime CDN requests. The complete license
is in `Montserrat-OFL.txt` and is retained in the built single-file card.
Source: https://github.com/google/fonts/tree/main/ofl/montserrat

Research captures, measurements and original frontend bundles stay outside the
integration repository. Synthetic browser screenshots stay in ignored artifacts.
