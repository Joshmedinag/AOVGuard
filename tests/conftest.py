from __future__ import annotations

import os

# OpenCV disables EXR I/O by default in many builds. Set it before cv2 is imported
# by tests that create/read temporary EXR files.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
