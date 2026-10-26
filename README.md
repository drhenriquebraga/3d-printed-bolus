# 3D Printed Bolus

**Part of the Radioterapia.AI Local Suite. 3D Printed Bolus: bolus, mould and surface brachytherapy applicator STL files from a box on the MPR and a layer over the skin, for research, phantoms and teaching — teaching and research material, not a medical device.**

`License: Apache-2.0` · `Component of: Radioterapia.AI Local Suite` · `Platform: Windows 10 and 11, 64-bit`

> **Teaching and research material. This is not a medical device, and it is
> not for clinical use.**
> It is **not** validated for clinical use, and it has no ANVISA registration,
> no CE mark and no FDA clearance. Every STL it exports is a **draft subject
> to physics and medical review**, and nothing in it is approved. The
> density of a printed part varies with the filament: the attenuation of the
> material has to be measured before any use, and the program does not know
> it. A planning system accounts for a bolus only through a CT taken with it
> in place. Every structure in the suite is an **unapproved suggestion**;
> reviewing and approving it is a physician's act, in the planning system.

## What it does

The CT is chosen in the Suite's series pop‑up, which opens on the *Point to
a folder* tab — the folder is read in the background by the Suite's reader,
with a filter by date and the favourite folder's star; an MR arrives refused,
with the reason —; the *Local archive* tab lists the series this workstation
has contoured, opened by a ticket and never by a path in the URL. On a recent
diagnostic CT, you draw a box on the MPR over the region of the
skin, and the program builds a layer over the skin inside it:

- **Bolus** — of anatomical thickness, following the skin, or a block in the
  shape of the box, projected onto the skin; 1 to 30 mm thick (5 mm by
  default).
- **Mould**, if you ask — a shell (1 to 4 mm) around the bolus, with an
  opening, for filling with wax.
- **Surface applicator for brachytherapy** — a third option: a body over the
  skin with channels for catheters, where the source runs inside the catheter.

The skin is ContourLab's, and the 3D view shows the patient opaque and the
bolus translucent. Each piece is exported as its own STL.

**The export is a declared act, every time.** The person ticks a statement
that the file is a draft subject to physics and medical review; the act is
written to `radai_bolus_atos.log` before the file leaves, and the STL header
itself says `DRAFT UNAPPROVED`. No RTSTRUCT is written: a bolus structure is
of direct dosimetric use, the same family as the `BODY` contour that this
suite does not deliver.

### The surface applicator

An applicator is a treatment accessory, and it weighs more than a bolus: a
badly drawn channel can trap the catheter or shift the dwell position of the
source. So every parameter comes with a suggested default and a «?» that
explains it and gives its references (six papers on printed surface
applicators, and the published bend radii), and some limits **block**:

- Defaults: a 6F flexible catheter, a channel 1.0 mm wider than the catheter,
  the channel axis 5 mm from the skin, 10 mm between channels, a 10 mm body,
  an open path (tip and connector leave the body), and a funnelled entrance.
  A blind‑ended channel is an option, with an alert: none of the papers
  describes or tests one.
- **The minimum bend radius** is chosen by afterloader and by catheter, from
  menus that show each published number and where it comes from. The
  suggested default, for all of them, is the safest radius found in the
  literature (35 mm). Below the floor of the chosen equipment, the program
  **does not generate** the applicator and proposes a wider arc, a thicker
  body, two channels, or ending the channel before the curve. Between the
  floor and the default it generates, with a yellow alert and four more
  requirements. The curvature is measured on the resampled centre line, not
  only at the vertices of the STL.
- The curvature follows the skin found at the partial‑volume edge of the
  voxels where the CT crosses −300 HU, which does not shift with where the
  skin falls inside a slice: on a 65 mm dome the minimum radius comes out
  within 3% of the true one on slices of 1, 2 and 3 mm, always on the safe
  side, and a tight 8 mm crest still blocks.
- Crossing channels, and a channel narrower than the catheter, also block.
  So does a channel that drops out in the middle with channels accepted on
  both sides: the centre would be left without a catheter, a risk of
  under‑covering the target. A channel dropped at the edge is a warning.
- When no channel fits, the refusal says the placement chosen (and whether
  the program chose it), the direction of the channels, the best channel
  (the one with the least path without skin), how much of its path has skin
  under it, and the separate causes — missing skin on one side, skin at the
  top of the box, something above the skin —, each with its own proposal.
  When the box gives no usable channel, the refusal also proposes a trimmed
  box, checked by tracing the channels in it again, with a **Use the
  suggested box** button: the box changes only on that click, and the
  applicator comes out only when you generate again. If the automatic
  placement would change direction in the trimmed box, no box is proposed
  and the refusal says so in one line: set the placement in the form and
  generate again to see the suggestion for it.
- With the channel direction on automatic, the program traces the channels
  along both axes perpendicular to the placement and keeps the one that
  holds more channels (the default one on a tie), and the warning and the
  sheet say which it chose. A blind‑ended channel needs skin only up to its
  end.
- The export is a `.zip` with the STL and a sheet of every parameter, with
  requirements that do not go away: a second CT with the applicator in place
  and a new plan before treating, a pass test with the check cable in each
  channel and the pre‑plan run on the afterloader, and dosimetry at
  commissioning. It is a declared act, plus a second one when a curve is
  yellow, and both are logged before the file leaves.

## What it does not do

- **It is not for clinical use.** It does not know the material, and it does
  not calculate dose.
- It writes no RTSTRUCT. For the plan to consider the bolus, the physicist
  takes a CT with it in place.
- It is not for a simulation CT with a mask: the bolus sits on the skin, on a
  recent diagnostic CT. MR is refused — without Hounsfield units there is no
  skin to measure.

## What is ours, and what is not

No model and no weight: this module does not use AI. Reading and resampling
use [SimpleITK][sitk] (Apache‑2.0); the distance field and the smoothing use
`scipy.ndimage` (BSD‑3) and NumPy. The surface, the mould, the applicator and
the STL files are written in this program. The 3D view was ported from the
reconstructor of DeFace RT, a project by the same author. These libraries are
installed by the Suite's preparer and do not travel in this repository.

## Privacy

Everything runs locally. The STL files carry no name and no UID, but **the
inner face of a bolus or an applicator is the patient's skin surface**, and
the inside of the mould is the bolus: for a head or face piece, the file is
biometric data and must be treated as patient data. The screen says so before
each export.

## Part of the Local Suite

3D Printed Bolus does not run on its own. The shared shell — the entrance
page, the menus, the twelve languages, the Terms and the Privacy Policy, the
configuration, the case archive, DICOM reading, the viewers and the queue —
lives in the [Suite][suite], and on the workstation the suite is one program:
one process, one port, one `app` folder, assembled by the Suite's installer
from the seven repositories. Its surface and STL writer are also used by the
3D Reconstructions module.

To use it, install the Suite with its light installer, from the
[releases of radioterapia-ai/local-suite][rel] (the permanent link to the
newest one is [`RADIOTERAPIA_AI_LOCAL_SUITE_SETUP_LATEST.zip`][latest]);
requirements and installation are in the Suite README.

This repository has no build of its own. The Suite's packager
(`build/empacotar_instalador.py --dos-repositorios`) downloads each component
at the tag pinned in `build/componentes.lock.json`, checks the SHA‑256 of its
extracted tree against the lock and
assembles the installer — see *Build from source* in the Suite README.

## Running the batteries

The batteries (`tools/test_*.py`, listed in `componente.json`) run over
synthetic phantoms. **No patient data is used anywhere in this repository, and
none may be committed to it.**

1. Put the [Suite][suite] and the six component repositories side by side in
   one folder. Folder names do not matter: the Suite is the folder with
   `tools/_componentes.py`, and each component is found by its
   `componente.json` (or set `RADAI_COMPONENTES_DIR` to the folder that holds
   the components). The batteries import modules of the Suite and of the
   other components, so all seven are needed.
2. Create the Suite's development environment: a Python virtual environment
   in `.venv` at the Suite root, as its README describes.
3. Run every battery of this component:

   ```
   <suite>\.venv\Scripts\python.exe <suite>\tools\_componentes.py --verificar <this folder>
   ```

   or a single one, with `--rodar test_<name>.py`. Each battery ends with an
   `OK:` or a `FALHOU:` footer, and `--verificar` ends with how many failed.
   `verify.cmd`, in this folder, does the same in two clicks once
   `_python.txt` (ignored by Git) holds the path of that `python.exe`.

4. **Turn on the pre‑commit hook** (once per clone):
   `git config core.hooksPath .githooks`. It runs the Suite's
   patient‑data scan over what is staged and refuses the commit that
   carries DICOM (with or without extension), a medical volume or a run
   log — and refuses it too when the scan cannot run, without the Suite
   beside this folder or without Python.

## Reporting a problem

A problem that is not a vulnerability goes through
**[radioterapia.ai](https://radioterapia.ai)**. Include the Local Suite
version, the Windows version, the screen language and the step that
failed — and **never patient data**: no DICOM series, no screenshot of a
patient image, no log with a patient ID, a UID or a series path. A problem
reproduced with the synthetic phantoms of the batteries is the quickest to
fix.

## Security

Found something that exposes patient data or lets the program act where it
should not? **Do not report it in public.** Use GitHub's private
vulnerability reporting on this repository, described in
[SECURITY.md](SECURITY.md).

## Licence and name

The code is licensed under the [Apache License 2.0](LICENSE). As section 6
says, the licence grants no permission to use the trade names of the
Licensor — "Radioterapia.AI", "Local Suite" and "3D Printed Bolus" included —
except as required to describe the origin of the work. A build you adapt is
yours: name it as yours.

| | Published code | A service's own build |
|---|---|---|
| What it is | Teaching and research material | An in‑house tool the service adapts, validates and registers in its own jurisdiction |
| Medical device? | **No.** Not validated for clinical use | Whatever that service's validation and registration make it |
| Who answers for it | Whoever downloads, modifies and deploys it answers for their own build, made with the Suite's build path | The service that deploys it |

Built by Dr. Henrique Braga, radiation oncologist —
**[radioterapia.ai](https://radioterapia.ai)**.

[sitk]: https://simpleitk.org
[suite]: https://github.com/radioterapia-ai/local-suite
[rel]: https://github.com/radioterapia-ai/local-suite/releases
[latest]: https://github.com/radioterapia-ai/local-suite/releases/latest/download/RADIOTERAPIA_AI_LOCAL_SUITE_SETUP_LATEST.zip
