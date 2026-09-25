# References and Further Reading

These sources provide the technical and production context for AOVGuard.
They are starting points for further exploration; the MSc thesis should cite
the exact editions and access dates required by the university APA guidance.

## OpenEXR and image IO

- Academy Software Foundation. *OpenEXR Technical Introduction*.
  https://openexr.com/en/latest/TechnicalIntroduction.html
  Describes HDR storage, arbitrary channels, channel naming, layers,
  multipart files, and deep data.
- Academy Software Foundation. *The OpenEXR Python Module*.
  https://openexr.com/en/latest/python.html
  Documents the Python API used by the production reader.
- Academy Software Foundation. *OpenEXR File Layout*.
  https://openexr.com/en/latest/OpenEXRFileLayout.html
  Provides additional detail about parts, chunks, scanlines, tiles, and deep
  storage.
- OpenImageIO contributors. *OpenImageIO Python Bindings*.
  https://openimageio.readthedocs.io/en/latest/pythonbindings.html
  Documents the alternative backend investigated during the reader spike.
- OpenImageIO contributors. *ImageCache*.
  https://openimageio.readthedocs.io/en/latest/imagecache.html
  Explains cached and demand-driven access to large image collections.
- OpenCV contributors. *Image file reading and codecs*.
  https://docs.opencv.org/4.x/d4/da8/group__imgcodecs.html
  Provides context for the legacy simple-image path and its limitations for
  named EXR channels.

## AOV and renderer workflows

- Autodesk. *Arnold for Maya: AOVs*.
  https://help.autodesk.com/cloudhelp/2024/ENU/AR-Maya/files/am-Arnold_for_Maya_User_Guide/render-settings/arnold_for_maya_render_settings_aovs_html.html
  Introduces Arnold AOVs and merged multilayer EXR output.
- Autodesk. *Arnold EXR driver*.
  https://help.autodesk.com/cloudhelp/ENU/AR-Core/files/ac-output-aovs/arnold_user_guide_ac_output_aovs_ac_exr_html.html
  Covers EXR precision, layers, metadata, scanline/tiled output, and multipart
  behaviour.

## Colour, luminance, and scene-linear data

- International Telecommunication Union. (2015). *Recommendation ITU-R
  BT.709-6: Parameter values for the HDTV standards for production and
  international programme exchange*.
  https://www.itu.int/rec/R-REC-BT.709
- International Telecommunication Union. (2011). *Recommendation ITU-R
  BT.601-7: Studio encoding parameters of digital television for standard 4:3
  and wide-screen 16:9 aspect ratios*.
  https://www.itu.int/rec/R-REC-BT.601
- Academy of Motion Picture Arts and Sciences. *ACES Documentation*.
  https://docs.acescentral.com/
  Provides production context for scene-referred colour and display output
  transforms.

## VFX software and reproducibility

- Visual Effects Society Technology Committee. *VFX Reference Platform*.
  https://vfxplatform.com/
  Defines annually coordinated versions of Python, Qt, OpenEXR, OpenColorIO,
  and other common VFX dependencies.
- Python Software Foundation. *typing.Protocol*.
  https://docs.python.org/3/library/typing.html#typing.Protocol
  Provides the structural typing mechanism used by the reader boundary.
- pytest contributors. *pytest documentation*. https://docs.pytest.org/
- pytest-cov contributors. *pytest-cov documentation*.
  https://pytest-cov.readthedocs.io/

## Academic and production methodology

- Ammann, P., & Offutt, J. (2017). *Introduction to software testing*
  (2nd ed.). Cambridge University Press.
  https://doi.org/10.1017/9781316771273
- Kalibera, T., & Jones, R. E. (2013). Rigorous benchmarking in reasonable
  time. *Proceedings of the 2013 International Symposium on Memory Management*,
  63-74. ACM. https://doi.org/10.1145/2464157.2464160
- Kurtz, M., Murphy, E., & Kilshaw, C. (2025). Integrated quality control:
  Improving production efficiency to achieve scale at DNEG Animation.
  *Proceedings of the Digital Production Symposium*. ACM.
  https://doi.org/10.1145/3744199.3744629
- Pearsall, C., Hardie, A., Sakr, M., & Bigda, J. (2026, July 18). Automating
  the handoff: From hardcoded QC scripts to a multi-agent architecture for
  layout-to-animation reviews [Conference talk]. Digital Production Symposium.
  https://digiproconf.org/program/
- Wohlin, C., Runeson, P., Höst, M., Ohlsson, M. C., Regnell, B., & Wesslén, A.
  (2024). *Experimentation in software engineering* (2nd ed.). Springer.
  https://doi.org/10.1007/978-3-662-69306-3
- Okun, J. A., Zwerman, S., & Thurmond O'Neal, S. (Eds.). (2025). *The VES
  handbook of visual effects: Industry standard VFX practices and procedures*
  (4th ed.). Routledge.
  https://www.routledge.com/The-VES-Handbook-of-Visual-Effects-Industry-Standard-VFX-Practices-and-Procedures/OkunVES-ZwermanVES-ThurmondONeal/p/book/9781032853697

## Referencing note

Documentation pages establish implementation behaviour, but they do not
replace peer-reviewed related work. The thesis literature review should
critically compare format design, scene-linear imaging, render-pass workflows,
validation strategies, and pipeline reproducibility rather than presenting
this list without analysis.
