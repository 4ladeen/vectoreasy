# VectorEasy — The Ultimate Image Vectorizer

> **Transform raster images into crisp, scalable vectors in seconds — right in your browser.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED)](Dockerfile)

---

## ✨ Features

- 🎨 **Multi-mode vectorization** — Color, Grayscale, Black & White, Logo, and Sketch modes
- 🖼️ **Side-by-side preview** — Original vs. vectorized with zoom & pan
- 🔀 **Comparison slider** — Drag to compare original and result interactively
- 🎛️ **Fine-grained controls** — Color count, detail level, smoothing, corner threshold
- 🤖 **Auto color detection** — Let the engine choose the optimal color count
- 🧹 **Background removal** — One-click transparent background extraction
- 🗂️ **Layer panel** — View, isolate, and toggle individual color layers
- 🎭 **Segment editor** — Recolor, merge, or delete individual segments
- 🖌️ **Color palette** — Click swatches to highlight corresponding layers
- 📤 **10 export formats** — SVG, EPS, PDF, DXF, PNG, JPG, GIF, BMP, TIFF + ZIP batch
- 📦 **Batch processing** — Upload multiple files, process in parallel, download ZIP
- ⌨️ **Keyboard shortcuts** — Ctrl+S (SVG), +/- (zoom), 0 (fit), Space (toggle view)
- 🖱️ **Drag to desktop** — Drag the SVG result directly out of the browser
- 📋 **Clipboard paste** — Ctrl+V / Cmd+V to paste images directly
- 🌐 **WebSocket + polling** — Real-time progress via WebSocket with polling fallback
- 🐳 **Docker-ready** — Single `docker compose up` to run
- ⚡ **Fast backend** — FastAPI + potrace + Cairo pipeline
- 🌙 **Dark theme UI** — Polished dark interface with glass-morphism effects
- 📱 **Responsive** — Works on desktop, tablet, and mobile
- 🔒 **No data retention** — Files processed and discarded; nothing stored permanently
- 🆓 **100% open source** — MIT licensed

---

## 🚀 Quick Start

### Docker (recommended)

```bash
git clone https://github.com/your-org/vectoreasy.git
cd vectoreasy
docker compose up
```

Open **http://localhost:8000** in your browser.

### Local (Python)

```bash
# Prerequisites: potrace, libcairo2-dev
pip install -r requirements.txt
python run.py
```

---

## 🖥️ Usage

1. **Upload** — Drag & drop, click to browse, or paste (Ctrl+V) an image
2. **Configure** — Choose mode, color count, detail, smoothing in the side panel
3. **Convert** — Vectorization starts automatically on upload
4. **Review** — Inspect layers, toggle visibility, recolor segments
5. **Export** — Click any format button in the export bar to download

---

## 🔌 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/vectorize` | Upload image and start vectorization job |
| `GET`  | `/api/status/{job_id}` | Poll job status and progress |
| `GET`  | `/api/export` | Download result (`?job_id=…&format=svg`) |
| `POST` | `/api/segment/recolor` | Recolor a specific layer |
| `POST` | `/api/segment/merge` | Merge two layers |
| `POST` | `/api/segment/delete` | Delete a layer |
| `POST` | `/api/batch/download-zip` | Download multiple results as ZIP |
| `WS`   | `/ws` | WebSocket for real-time progress |

### POST `/api/vectorize` — form fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | File | required | Image file |
| `mode` | string | `color` | `color`, `bw`, `grayscale`, `logo`, `sketch` |
| `colors` | int / `auto` | `auto` | Number of colors (2–64) |
| `detail` | int | `3` | Detail level 1–5 |
| `smoothing` | int | `50` | Path smoothing 0–100 |
| `remove_bg` | bool | `false` | Remove background |

---

## 📁 Supported Formats

### Input
| Format | Notes |
|--------|-------|
| PNG | Transparency supported |
| JPEG / JPG | |
| WebP | |
| GIF | First frame used |
| BMP | |
| TIFF | |
| SVG | Re-traces the raster preview |

### Output
| Format | Notes |
|--------|-------|
| **SVG** | Scalable Vector Graphics (default) |
| **EPS** | Encapsulated PostScript |
| **PDF** | Portable Document Format |
| **DXF** | AutoCAD / CNC |
| **PNG** | Configurable resolution (1×–4×) |
| **JPG** | Configurable quality (60–100) |
| **GIF** | Animated-safe output |
| **BMP** | Uncompressed bitmap |
| **TIFF** | High-quality raster |

---

## 🏗️ Architecture

```
vectoreasy/
├── app/
│   ├── main.py              # FastAPI app, routes, WebSocket
│   ├── vectorizer/
│   │   ├── engine.py        # Orchestrates the pipeline
│   │   ├── preprocessor.py  # Image pre-processing
│   │   ├── color_quantizer.py
│   │   ├── segmentation.py
│   │   ├── tracer.py        # potrace integration
│   │   ├── optimizer.py     # SVG path optimization
│   │   └── exporter.py      # Multi-format export
│   ├── batch/
│   │   └── processor.py     # Batch job queue
│   ├── templates/
│   │   └── index.html       # Single-page app
│   └── static/
│       ├── css/style.css
│       ├── js/app.js
│       └── favicon.svg
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── run.py
```

---

## 📄 License

[MIT License](LICENSE) — Copyright © 2024 VectorEasy Contributors
