# EXR Backend Spike Summary

This spike compares the candidate image backends for AOVGuard 2.0 without
adding a new production dependency.

## Scope

The experiment generates tiny float EXR fixtures and compares:

- OpenEXR
- OpenCV
- OpenImageIO, if importable

The script is intentionally a smoke benchmark rather than a final performance
benchmark. Timing values are useful for comparison during development, but they
are not statistically rigorous.

## Command

```powershell
uv --cache-dir .uv-cache run --python 3.12 --extra dev python experiments\exr_backend_spike.py
```

Optional OpenImageIO attempt:

```powershell
uv --cache-dir .uv-cache run --python 3.12 --extra dev --with OpenImageIO python experiments\exr_backend_spike.py --output-dir experiments\_spike_output_oiio
```

## Confirmed Results

### OpenEXR

OpenEXR is available in the current project environment.

Confirmed:

- reads EXR headers;
- exposes named channels;
- can read named RGB AOV channels such as `diffuse.R`, `diffuse.G`, `diffuse.B`;
- integrates with the new `build_file_inspection()` model;
- supports the MVP requirement for named-channel inspection and AOV extraction.

Observed version during the spike: `3.4.12`.

### OpenCV

OpenCV is available in the current project environment.

Confirmed:

- reads simple RGB EXRs as image arrays;
- loads RGB EXR data in BGR order;
- does not expose EXR named channels through `cv2.imread`;
- is not suitable as the primary backend for multilayer/named-AOV inspection.

Observed version during the spike: `4.13.0`.

### OpenImageIO

OpenImageIO was tested as an optional dependency using `uv --with OpenImageIO`.

Confirmed:

- the package can be downloaded and installed by `uv`;
- import fails in this Windows environment before any EXR read can occur.

Observed failure:

```text
ImportError: DLL load failed while importing OpenImageIO:
El nombre del archivo o la extension es demasiado largo.
```

The same import failure occurred when using a shorter temporary virtual
environment path:

```text
C:\path\to\oiio_spike_venv
```

## Preliminary Decision

OpenImageIO should **not** be added as a production dependency yet.

For the MVP, the safest backend path is:

1. use OpenEXR as the primary backend for structured EXR inspection and named
   channel reading;
2. keep OpenCV only as a simple-image fallback or compatibility path;
3. keep OpenImageIO as future work until the Windows import/DLL issue is
   understood and resolved.

## Implemented Reader Update

The production reader now uses the modern `OpenEXR.File` API with separate
named channels. During analysis, structure and pixels come from the same file
object, reducing the application-level reader construction count to one per
frame. The API also exposes part count and storage type, allowing multipart and
deep files to be detected and rejected explicitly by the MVP backend.

## Generated Evidence

The spike writes JSON output to:

```text
experiments/_spike_output/backend_spike_results.json
experiments/_spike_output_oiio/backend_spike_results.json
experiments/_spike_output_oiio_shortenv/backend_spike_results.json
```

Generated EXR fixtures are not intended to be committed as source fixtures.
