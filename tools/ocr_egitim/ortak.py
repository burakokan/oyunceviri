r"""Shared paths of the OCR training scripts (see README.md).

The data (row pictures, labels, trained models) is kept outside the repository: OCR_VERI, or ..\OyunCeviriData next
to the project folder. The recorded pictures are read from the app's logs\ folder."""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PC = REPO / "pc"
LOGS = REPO / "logs"
DATA = Path(os.environ.get("OCR_VERI", REPO.parent / "OyunCeviriData"))
TINY = Path(os.environ.get("TINY_ONNX", REPO / ".venv" / "Lib" / "site-packages" / "rapidocr" / "models"
                           / "PP-OCRv6_rec_tiny.onnx"))
DATA.mkdir(parents=True, exist_ok=True)
if str(PC) not in sys.path:
    sys.path.insert(0, str(PC))
