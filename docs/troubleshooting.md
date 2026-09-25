# Troubleshooting

## `pip: command not found`

Use:

```powershell
python -m pip install uv
```

or install uv with:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Python 3.9 is not supported

Install Python 3.12 using uv:

```powershell
uv python install 3.12
uv sync --python 3.12 --extra dev
```

## `OpenEXR codec is disabled`

This message belongs to the legacy OpenCV reader and related tests. Set this
environment variable before running the full test suite or a legacy command:

```powershell
$env:OPENCV_IO_ENABLE_OPENEXR="1"
```

Then run:

```powershell
uv run pytest
```

## `No RGB AOV groups found in the EXR files`

This message belongs to the legacy multilayer command. Use the automatic
inspector to see the actual structure:

```powershell
uv run aovguard inspect-structure path\to\frame.exr
```

Try one of the following:

- check that **Merge AOVs** was enabled when exporting from Maya/Arnold;
- check whether the named layers expose identifiable R, G and B channels.

## `0 AOVs analyzed`

The automatic backend rejects a folder containing no discoverable EXRs. If the
report contains detected AOVs but zero analyzed AOVs, the file may contain only
technical, unknown, deep or unsupported multipart data.

## The UI freezes or seems slow

The analysis now runs in a worker thread and updates a progress bar. Large EXRs can still take time to read, especially multilayer files, but the progress indicator should show that the tool is working.
