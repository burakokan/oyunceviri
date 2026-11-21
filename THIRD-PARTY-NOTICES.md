# Third-party notices / Üçüncü taraf bileşenler

Oyun Çeviri is licensed under the GNU AGPL-3.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)). Its full source code is
in this repository: <https://github.com/burakokan/oyunceviri>. The Windows setup and the in-place updates
(GitHub Releases) contain the third-party components below, unmodified unless stated otherwise. Each one stays
under its own license.

> Türkçe özet: Program GNU AGPL-3.0 lisanslıdır. Kurulumda ve güncellemelerde aşağıdaki başka projelerin dosyaları
> vardır, her biri kendi lisansıyla dağıtılır. Oyun paketlerinin kaynakları en alttadır. Oyunların adları, karakterleri
> ve diyalogları sahiplerine aittir. Paketler yalnızca kişisel, ticari olmayan kullanım içindir.

## Remote Play library (in git and in the setup)

| Component | License | Source |
|---|---|---|
| `vendor/couchsubs_native.dll`: the native Remote Play library of CouchSubs, unmodified binary | GNU AGPL-3.0, Copyright (C) 2026 Sinan Yorulmaz | <https://github.com/yorulmazsinan/couchsubs> (`windows/native/`) |

According to CouchSubs' own notices, this library contains:

| Component | License | Source |
|---|---|---|
| chiaki-ng (`libchiaki`, PlayStation Remote Play protocol) | AGPL-3.0 with OpenSSL exception | <https://github.com/chiaki-ng/chiaki-ng> |
| FFmpeg 7.1.2 (`libavcodec` H.264 decoder, `libswscale`; statically linked) | LGPL-2.1-or-later | <https://ffmpeg.org> |
| nanopb | zlib | <https://github.com/nanopb/nanopb> |
| Jerasure | BSD-3-Clause | <https://github.com/ceph/jerasure> |
| GF-Complete | BSD-3-Clause | <https://github.com/ceph/gf-complete> |
| curl | curl license (MIT/X derivative) | <https://curl.se> |
| OpenSSL 3 | Apache-2.0 | <https://www.openssl.org> |
| json-c | MIT | <https://github.com/json-c/json-c> |
| libevent | BSD-3-Clause | <https://libevent.org> |
| miniupnpc | BSD-3-Clause | <https://miniupnp.tuxfamily.org> |

## Other programs shipped with the app

| Component | License | Source |
|---|---|---|
| Android SDK Platform-Tools `adb` (`vendor/adb/`) | Apache-2.0 and others, see `vendor/adb/NOTICE.txt` | <https://developer.android.com/tools/releases/platform-tools> |
| llama.cpp / ggml (b12100, `vendor/llama/`, setup only) | MIT | <https://github.com/ggml-org/llama.cpp> |
| LLVM OpenMP runtime (`libomp.dll`, setup only) | Apache-2.0 with LLVM Exceptions, see `vendor/llama/LICENSE-LLVM-OpenMP` | <https://openmp.llvm.org> |
| NVIDIA CUDA runtime and cuBLAS DLLs (`cudart64_12.dll`, `cublas64_12.dll`, `cublasLt64_12.dll`, setup only) | NVIDIA CUDA Toolkit EULA, redistributable runtime files | <https://docs.nvidia.com/cuda/eula/> |
| Python 3.13 runtime (setup only) | Python Software Foundation License | <https://www.python.org> |
| PyInstaller bootloader (setup only) | GPL-2.0-or-later with the PyInstaller bootloader exception | <https://pyinstaller.org> |
| Inno Setup (builds the installer) | Inno Setup License | <https://jrsoftware.org/isinfo.php> |

## Python libraries (setup only)

| Library | License | Source |
|---|---|---|
| PySide6 / Qt 6.12 (Essentials, Addons, WebEngine), shiboken6 | LGPL-3.0 (Qt WebEngine includes Chromium, under BSD-3-Clause and other licenses) | <https://pyside.org> |
| NumPy | BSD-3-Clause (and bundled 0BSD, MIT, Zlib, CC0-1.0 parts) | <https://numpy.org> |
| OpenCV (`opencv-python`) | Apache-2.0 | <https://github.com/opencv/opencv-python> |
| windows-capture | MIT | <https://github.com/NiiightmareXD/windows-capture> |
| RapidOCR | Apache-2.0 | <https://github.com/RapidAI/RapidOCR> |
| ONNX Runtime | MIT | <https://onnxruntime.ai> |
| CTranslate2 | MIT | <https://github.com/OpenNMT/CTranslate2> |
| SentencePiece | Apache-2.0 | <https://github.com/google/sentencepiece> |
| nvidia-cublas-cu12 (cuBLAS for CTranslate2) | NVIDIA proprietary (CUDA EULA, redistributable) | <https://developer.nvidia.com/cuda-zone> |
| huggingface_hub, hf-xet | Apache-2.0 | <https://github.com/huggingface/huggingface_hub> |
| websockets | BSD-3-Clause | <https://github.com/python-websockets/websockets> |
| RapidFuzz | MIT | <https://github.com/rapidfuzz/RapidFuzz> |
| requests | Apache-2.0 | <https://github.com/psf/requests> |
| urllib3, charset-normalizer, truststore | MIT | PyPI |
| certifi | MPL-2.0 | <https://github.com/certifi/python-certifi> |
| idna, psutil, pycparser, shapely, fsspec, click, protobuf, httpx2 / httpcore2 | BSD-3-Clause | PyPI |
| paramiko (LG TV connection) | LGPL-2.1 | <https://github.com/paramiko/paramiko> |
| cryptography | Apache-2.0 or BSD-3-Clause | <https://github.com/pyca/cryptography> |
| bcrypt, PyNaCl, flatbuffers | Apache-2.0 | PyPI |
| cffi | MIT-0 | <https://github.com/python-cffi/cffi> |
| pyclipper, PyYAML, colorlog, six, filelock, anyio, h11, winrt (Python/WinRT projections) | MIT | PyPI |
| Pillow | MIT-CMU (HPND) | <https://python-pillow.org> |
| omegaconf, colorama, invoke | BSD | PyPI |
| tqdm | MPL-2.0 and MIT | <https://tqdm.github.io> |
| packaging | Apache-2.0 or BSD-2-Clause | <https://github.com/pypa/packaging> |
| typing_extensions | PSF-2.0 | <https://github.com/python/typing_extensions> |

The LGPL libraries (Qt / PySide6, paramiko) are used as separate, replaceable files in the app folder.

## Models (setup only)

| Model | License | Source |
|---|---|---|
| OPUS-MT `opus-mt-tc-big-en-tr` (converted to CTranslate2) | CC-BY-4.0, Helsinki-NLP / Language Technology Research Group, University of Helsinki | <https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-tr> |
| quickmt `quickmt-en-tr` | CC-BY-4.0 | <https://huggingface.co/quickmt/quickmt-en-tr> |
| Gemma 4 E2B (Q4_0 GGUF) | Gemma Terms of Use | <https://ai.google.dev/gemma/terms> |
| PP-OCR text detection / recognition models (in RapidOCR) | Apache-2.0 | <https://github.com/PaddlePaddle/PaddleOCR> |
| `assets/ocr/game_rec_tiny_en.onnx`: PP-OCRv6 tiny recognizer fine-tuned by this project on recorded game subtitle rows, output cut to English characters and Turkish letters (a modified version of the PP-OCRv6 tiny model) | Apache-2.0 | <https://github.com/PaddlePaddle/PaddleOCR> |

Gemma is provided under and subject to the Gemma Terms of Use found at <https://ai.google.dev/gemma/terms>.

## TV apps

| Component | License | Source |
|---|---|---|
| OkHttp / Okio (Android TV app) | Apache-2.0 | <https://square.github.io/okhttp/> |
| Kotlin standard library (Android TV app) | Apache-2.0 | <https://kotlinlang.org> |
| TizenSdb.Core 1.1.9 (Samsung TV connection and package signing, `tools/SamsungHelper`) | MIT, Copyright (c) Patrick Stel | <https://github.com/PatrickSt1991/tizen-sdb> |
| .NET runtime (Samsung helper) | MIT | <https://github.com/dotnet/runtime> |

The Samsung sign-in and certificate request flow of `tools/SamsungHelper` follows the way CouchSubs and GameTranslator
do it, which is adapted from Apps2Samsung (MIT, Copyright (c) 2025 Patrick Stel,
<https://github.com/Jellyfin2Samsung/Samsung-Jellyfin-Installer>).

The Samsung developer CA certificates in `tools/SamsungHelper/ca/` (`author_ca`, `public2`, `vd_tizen_dev_author_ca`,
`vd_tizen_dev_public2`) are redistributed unmodified from Tizen Studio, only so that the TV app can be signed for the
user's own Samsung TV. They are the property of Samsung Electronics Co., Ltd. and are not covered by this project's
license.

MIT License text (TizenSdb.Core, Apps2Samsung, and the other MIT components above): Permission is hereby granted, free
of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to
do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
OR OTHER DEALINGS IN THE SOFTWARE.

## Online services (only with the user's own keys)

The app can send English subtitle lines to DeepL (DeepL API), Groq (Qwen models) and Google Gemini, with API keys
the user enters on their own PC. Their own terms of service apply. No keys are part of this repository or the setup.

## Game packs (`packs/`)

The packs are Turkish translations of game dialogue, made for the user's own, non-commercial use together with games
they own. Game titles, characters and dialogue are the property of their publishers and developers. This project is
not affiliated with them. To have a pack removed, open an issue in this repository.

### From CouchSubs

The following packs are taken from CouchSubs (<https://github.com/yorulmazsinan/couchsubs>, GNU AGPL-3.0) or from its
pack server, unchanged. They hold only hashed keys and Turkish text, with no English game text. The sources below are
CouchSubs' own records.

| Pack | Source of the text, as CouchSubs records it |
|---|---|
| `assassins-creed-shadows`, `call-of-duty-modern-warfare-2019`, `death-stranding-2`, `mafia-the-old-country`, `red-dead-redemption-2` | Translated with Claude by CouchSubs |
| `death-stranding-directors-cut` | Translated with Claude from the fan transcript at Game Scripts Wiki |
| `elden-ring` | Translated with Claude from the Carian Archive and Impaler's Archive text dumps. Terminology from the Elden Ring Turkish fan translation by mehmetkrn (MIT) |
| `marvels-spider-man-2` | Translated with Claude from the Marvel's Spider-Man Wiki script (Fandom, CC BY-SA 3.0) and the CouchSubs subtitle pool |
| `gta-v` | GTA TR (TechnoGame) and Claude |
| `gta-6` | CouchSubs shared subtitle pool and Workers AI. Also CouchSubs PR #387 by lones8888: lines read from a YouTube playthrough, translated with Codex and Gemma |

### From GameTranslator

`final-fantasy-vii-remake`, `final-fantasy-vii-rebirth` and `watch-dogs` are taken from GameTranslator by sefflex
(<https://gitlab.com/sefflex/GameTranslator>, GNU AGPL-3.0; community / user patches). The FF7 packs were converted
from its plain English-Turkish lists.

### Made for this project

These packs were translated with Google Gemini, with the speaker and the lines around each line as context. They also
contain the English source text, so that lines read with small OCR errors can still be matched. The English text comes
from the community wikis and transcripts below. Where a source is under CC BY-SA, the pack's English text and its
Turkish translation are shared under the same license (CC BY-SA 3.0) with credit to that source's contributors.

| Pack | English source |
|---|---|
| `assassins-creed-*` (Valhalla, Odyssey, Origins, Mirage, Unity, Syndicate, Black Flag, Rogue, III, Ezio Collection) | Mission dialogue pages of the Assassin's Creed Wiki (<https://assassinscreedwiki.accesstheanimus.com>), by its contributors |
| `far-cry-6` | Subtitle text extracted from the game's files, as published on the Far Cry Wiki (<https://farcry.fandom.com>, CC BY-SA 3.0) |
| `marvels-spider-man-remastered`, `marvels-spider-man-miles-morales` | Scripts on the Marvel's Spider-Man Wiki (<https://marvels-spider-man.fandom.com>, CC BY-SA 3.0) |
| `resident-evil-village`, `resident-evil-4-remake` | Transcripts on the Resident Evil Wiki (<https://residentevil.fandom.com>, CC BY-SA 3.0) |
| `metal-gear-solid-delta` | MGS3 Snake Eater game script collected at <https://github.com/amio/mgs-scripts> |

`packs/build/<pack>/` holds the English source text (`source.jsonl`) and the translation work files of these packs, from the same sources and under the same terms. `packs/fixes/` holds corrections made for this project.

## Trademarks

PlayStation, PS5, PSN and Remote Play are trademarks of Sony Interactive Entertainment Inc. Android TV and Google TV
are trademarks of Google LLC. Samsung and Tizen are trademarks of Samsung Electronics Co., Ltd. LG and webOS are
trademarks of LG Electronics. Game titles are trademarks of their respective owners. They are used here only to name
the games, consoles and TVs the app works with.
