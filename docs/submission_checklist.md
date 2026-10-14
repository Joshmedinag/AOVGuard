# MSc Submission Checklist

## Practical project

- [ ] Repository opens at the folder containing `pyproject.toml`.
- [ ] `uv sync --locked --python 3.12 --extra dev` succeeds in a clean environment.
- [ ] `examples/` contains only `.gitkeep`; real EXRs remain outside the repository.
- [ ] CLI inspection, analysis and sequence commands succeed.
- [ ] `uv run --extra gui aovguard-ui` launches and can analyze file/folder sources.
- [ ] Base wheel CLI runs without Qt or OpenCV; the GUI wheel extra is optional.
- [ ] Flat multipart parts retain separate identities, views and windows.
- [ ] Any deep part or partial decode fails the whole frame explicitly.
- [ ] JSON and HTML exports open correctly.
- [ ] `uv run --locked --extra dev pytest --cov-fail-under=95` passes.
- [ ] Benchmark command and raw results are included.
- [ ] `README.md`, licence, citation, changelog and references are current.
- [ ] ZIP excludes `.venv`, caches, build artifacts and every EXR file.

## Website

- [ ] Open `website/index.html` on desktop and mobile-width windows.
- [ ] Confirm that the hero screenshot loads.
- [ ] Confirm all local documentation/report links work.
- [ ] Include the complete `website` folder in the submission.

## Video

- [ ] Record at readable resolution with clean audio.
- [ ] Demonstrate authorised real EXRs, inspection, GUI, sequence check and reports.
- [ ] Show tests and benchmark evidence.
- [ ] State limitations clearly.
- [ ] Verify the final exported video from start to finish.

## Presentation

- [ ] Keep the prepared presentation within 15 minutes.
- [ ] Use measured evidence rather than unsupported performance claims.
- [ ] Include architecture, before/after comparison and critical reflection.
- [ ] Rehearse the live demo and keep screenshots as a fallback.

## Written report

- [ ] Submit the thesis as PDF.
- [ ] Check citations, bibliography, figure numbering and captions.
- [ ] Connect each research question to evidence and a conclusion.
- [ ] Include critical limitations and threats to validity.
- [ ] Proofread the final exported PDF, not only the source document.

## Final archive

- [ ] Use a clear release filename and include the project root only once.
- [ ] The ZIP version comes from `pyproject.toml`, matching wheel/citation metadata.
- [ ] Preview package selection with `python scripts/create_release.py --list` and review included files for private content.
- [ ] Use a new destination; keep released artifacts separate from development snapshots.
- [ ] Verify the new ZIP with `python scripts/create_release.py --verify path/to/snapshot.zip` and record its overall SHA-256.
- [ ] Extract the ZIP into a temporary folder and repeat installation/tests.
- [ ] Confirm the video, website files, practical project and thesis are present
  in the required submission locations before the deadline.
