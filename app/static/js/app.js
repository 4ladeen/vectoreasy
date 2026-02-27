/**
 * VectorEasy — app.js
 * Comprehensive vanilla JS (ES6+) frontend for the VectorEasy image vectorizer.
 */

'use strict';

/* ── Utilities ──────────────────────────────────────────────────────────────── */
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const fmt = n => (n >= 1e6 ? (n / 1e6).toFixed(1) + ' MB' : n >= 1e3 ? (n / 1e3).toFixed(0) + ' KB' : n + ' B');

/* ── Toast ──────────────────────────────────────────────────────────────────── */
class Toast {
  constructor() {
    this.container = document.createElement('div');
    this.container.className = 'toast-container';
    document.body.appendChild(this.container);
  }
  show(msg, type = 'info', duration = 3500) {
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.innerHTML = `<span>${msg}</span>`;
    this.container.appendChild(t);
    setTimeout(() => {
      t.classList.add('hiding');
      t.addEventListener('animationend', () => t.remove());
    }, duration);
  }
  info(msg)    { this.show(msg, 'info'); }
  success(msg) { this.show(msg, 'success'); }
  error(msg)   { this.show(msg, 'error', 5000); }
}

/* ── ProgressBar ────────────────────────────────────────────────────────────── */
class ProgressBar {
  constructor(wrap) {
    this.wrap  = wrap;
    this.fill  = wrap.querySelector('.progress-fill');
    this.pct   = wrap.querySelector('.progress-pct');
    this.stage = wrap.querySelector('.progress-stage');
  }
  show(msg = 'Processing…', pct = 0) {
    this.wrap.classList.add('visible');
    this.update(msg, pct);
  }
  update(msg, pct) {
    if (this.stage) this.stage.textContent = msg;
    if (this.fill)  this.fill.style.width = clamp(pct, 0, 100) + '%';
    if (this.pct)   this.pct.textContent  = Math.round(pct) + '%';
    this.fill.classList.remove('complete', 'error');
  }
  complete(msg = 'Done!') {
    this.update(msg, 100);
    this.fill.classList.add('complete');
  }
  error(msg = 'Error') {
    this.update(msg, 100);
    this.fill.classList.add('error');
  }
  hide() { this.wrap.classList.remove('visible'); }
}

/* ── ImageUploader ──────────────────────────────────────────────────────────── */
class ImageUploader {
  constructor(zone, onFile) {
    this.zone   = zone;
    this.onFile = onFile;
    this._bind();
  }
  _bind() {
    this.zone.addEventListener('click', () => this._openPicker());
    this.zone.addEventListener('dragover', e => { e.preventDefault(); this.zone.classList.add('drag-over'); });
    this.zone.addEventListener('dragleave', () => this.zone.classList.remove('drag-over'));
    this.zone.addEventListener('drop', e => {
      e.preventDefault();
      this.zone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file) this._handle(file);
    });
    document.addEventListener('paste', e => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith('image/')) {
          this._handle(item.getAsFile());
          break;
        }
      }
    });
  }
  _openPicker() {
    const inp = document.createElement('input');
    inp.type = 'file';
    inp.accept = 'image/png,image/jpeg,image/webp,image/gif,image/bmp,image/tiff,image/svg+xml';
    inp.onchange = () => { if (inp.files[0]) this._handle(inp.files[0]); };
    inp.click();
  }
  _handle(file) {
    if (!file.type.startsWith('image/')) { toast.error('Not an image file.'); return; }
    if (file.size > 100 * 1024 * 1024) { toast.error('File too large (max 100 MB).'); return; }
    const reader = new FileReader();
    reader.onload = e => this.onFile(file, e.target.result);
    reader.readAsDataURL(file);
  }
}

/* ── PreviewPanel ───────────────────────────────────────────────────────────── */
class PreviewPanel {
  constructor(container) {
    this.container = container;
    this.wrap = container.querySelector('.preview-canvas-wrap');
    this.img  = null;
    this.scale = 1;
    this.tx = 0;
    this.ty = 0;
    this._dragging = false;
    this._last = {};
    this._bindEvents();
  }
  load(src, isSvg = false) {
    this.wrap.innerHTML = '';
    const el = isSvg ? document.createElement('object') : document.createElement('img');
    if (isSvg) {
      el.type = 'image/svg+xml';
      el.data = src;
    } else {
      el.src = src;
    }
    el.style.cssText = 'position:absolute;top:0;left:0;max-width:none;max-height:none;pointer-events:none;user-select:none;';
    this.wrap.appendChild(el);
    this.img = el;
    el.onload = () => this.fitToScreen();
    if (isSvg) setTimeout(() => this.fitToScreen(), 80);
  }
  loadSvgString(svgStr) {
    this.wrap.innerHTML = '';
    const blob = new Blob([svgStr], { type: 'image/svg+xml' });
    const url  = URL.createObjectURL(blob);
    this.load(url, true);
  }
  clear() {
    this.wrap.innerHTML = `<div class="preview-empty"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9l4-4 5 5 4-4 5 5"/></svg><div>No image</div></div>`;
    this.img = null;
  }
  fitToScreen() {
    if (!this.img) return;
    const cw = this.wrap.clientWidth, ch = this.wrap.clientHeight;
    const iw = this.img.naturalWidth  || this.img.offsetWidth  || 400;
    const ih = this.img.naturalHeight || this.img.offsetHeight || 400;
    this.scale = Math.min(cw / iw, ch / ih, 1) * 0.95;
    this.tx = (cw - iw * this.scale) / 2;
    this.ty = (ch - ih * this.scale) / 2;
    this._apply();
  }
  zoom(factor, cx, cy) {
    if (!this.img) return;
    cx = cx ?? this.wrap.clientWidth / 2;
    cy = cy ?? this.wrap.clientHeight / 2;
    const prev = this.scale;
    this.scale = clamp(this.scale * factor, 0.05, 30);
    const r = this.scale / prev;
    this.tx = cx - (cx - this.tx) * r;
    this.ty = cy - (cy - this.ty) * r;
    this._apply();
  }
  _apply() {
    if (!this.img) return;
    const iw = this.img.naturalWidth  || this.img.offsetWidth  || 400;
    const ih = this.img.naturalHeight || this.img.offsetHeight || 400;
    this.img.style.width  = (iw * this.scale) + 'px';
    this.img.style.height = (ih * this.scale) + 'px';
    this.img.style.transform = `translate(${this.tx}px, ${this.ty}px)`;
    this._updateIndicator();
  }
  _updateIndicator() {
    const ind = this.container.querySelector('.zoom-indicator');
    if (ind) ind.textContent = Math.round(this.scale * 100) + '%';
  }
  _bindEvents() {
    this.wrap.addEventListener('wheel', e => {
      e.preventDefault();
      const r   = this.wrap.getBoundingClientRect();
      const cx  = e.clientX - r.left;
      const cy  = e.clientY - r.top;
      const dir = e.deltaY < 0 ? 1.12 : 0.9;
      this.zoom(dir, cx, cy);
    }, { passive: false });

    this.wrap.addEventListener('mousedown', e => {
      if (e.button !== 0) return;
      this._dragging = true;
      this._last = { x: e.clientX, y: e.clientY };
      this.wrap.style.cursor = 'grabbing';
    });
    window.addEventListener('mousemove', e => {
      if (!this._dragging) return;
      this.tx += e.clientX - this._last.x;
      this.ty += e.clientY - this._last.y;
      this._last = { x: e.clientX, y: e.clientY };
      this._apply();
    });
    window.addEventListener('mouseup', () => {
      this._dragging = false;
      this.wrap.style.cursor = '';
    });

    // Touch
    let lastDist = null;
    this.wrap.addEventListener('touchstart', e => {
      if (e.touches.length === 1) {
        this._dragging = true;
        this._last = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      }
    }, { passive: true });
    this.wrap.addEventListener('touchmove', e => {
      if (e.touches.length === 2) {
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        const d  = Math.hypot(dx, dy);
        if (lastDist !== null) this.zoom(d / lastDist);
        lastDist = d;
      } else if (this._dragging && e.touches.length === 1) {
        this.tx += e.touches[0].clientX - this._last.x;
        this.ty += e.touches[0].clientY - this._last.y;
        this._last = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        this._apply();
        e.preventDefault();
      }
    }, { passive: false });
    this.wrap.addEventListener('touchend', () => { this._dragging = false; lastDist = null; });
  }
}

/* ── ComparisonSlider ───────────────────────────────────────────────────────── */
class ComparisonSlider {
  constructor(container) {
    this.container = container;
    this.fg = container.querySelector('.comparison-fg');
    this.divider = container.querySelector('.comparison-divider');
    this._pct = 50;
    this._dragging = false;
    this._bind();
  }
  _bind() {
    const start = e => {
      this._dragging = true;
      this._move(e);
      e.preventDefault();
    };
    const move = e => {
      if (!this._dragging) return;
      this._move(e);
    };
    const stop = () => { this._dragging = false; };

    this.divider.addEventListener('mousedown', start);
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', stop);
    this.divider.addEventListener('touchstart', start, { passive: false });
    window.addEventListener('touchmove', e => { if (this._dragging) { this._move(e); e.preventDefault(); } }, { passive: false });
    window.addEventListener('touchend', stop);
  }
  _move(e) {
    const r = this.container.getBoundingClientRect();
    const cx = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
    this._pct = clamp((cx / r.width) * 100, 2, 98);
    this._apply();
  }
  _apply() {
    if (this.fg)      this.fg.style.width       = this._pct + '%';
    if (this.divider) this.divider.style.left    = this._pct + '%';
  }
  set(pct) { this._pct = pct; this._apply(); }
}

/* ── SettingsPanel ──────────────────────────────────────────────────────────── */
class SettingsPanel {
  constructor(el, onChange) {
    this.el = el;
    this.onChange = onChange;
    this._initSliders();
    this._initModes();
    this._initAccordions();
    this._initToggles();
  }
  _initSliders() {
    $$('input[type="range"]', this.el).forEach(slider => {
      const display = slider.closest('.ctrl-section, .accordion-inner')
                        ?.querySelector('.val[data-for="' + slider.id + '"]')
                   || slider.parentElement.querySelector('.val');
      const update = () => {
        if (display) {
          const isAuto = slider.closest('.ctrl-section')?.querySelector('input[type="checkbox"]')?.checked;
          display.textContent = isAuto ? 'Auto' : slider.value;
        }
        this.onChange?.(this.values());
      };
      slider.addEventListener('input', update);
      update();
    });
  }
  _initModes() {
    $$('.mode-btn', this.el).forEach(btn => {
      const inp = btn.querySelector('input[type="radio"]');
      btn.addEventListener('click', () => {
        $$('.mode-btn', this.el).forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
        if (inp) inp.checked = true;
        this.onChange?.(this.values());
      });
      if (inp?.checked) btn.classList.add('selected');
    });
  }
  _initAccordions() {
    $$('.accordion-header', this.el).forEach(hdr => {
      hdr.addEventListener('click', () => {
        const body = hdr.nextElementSibling;
        const open = hdr.classList.toggle('open');
        if (body) body.classList.toggle('open', open);
      });
    });
  }
  _initToggles() {
    $$('input[type="checkbox"]', this.el).forEach(cb => {
      cb.addEventListener('change', () => this.onChange?.(this.values()));
    });
  }
  values() {
    const v = {};
    const modeEl = $('.mode-btn.selected', this.el);
    v.mode = modeEl?.querySelector('input')?.value || 'color';
    const colorCount = $('#color-count', this.el);
    const autoColor  = $('#auto-colors', this.el);
    v.colors = autoColor?.checked ? 'auto' : (colorCount?.value || 16);
    v.detail    = $('#detail-level', this.el)?.value    || 3;
    v.smoothing = $('#smoothing', this.el)?.value       || 50;
    v.removeBg  = $('#remove-bg', this.el)?.checked     || false;
    v.despeckle = $('#despeckle', this.el)?.value       || 2;
    v.pathOpt   = $('#path-optimize', this.el)?.value   || 3;
    v.cornerThresh = $('#corner-thresh', this.el)?.value || 60;
    return v;
  }
}

/* ── ColorPalette ───────────────────────────────────────────────────────────── */
class ColorPalette {
  constructor(row, onSelect) {
    this.row = row;
    this.onSelect = onSelect;
  }
  render(colors) {
    this.row.innerHTML = '';
    if (!colors?.length) {
      this.row.innerHTML = '<span class="text-dim text-xs">No colors yet</span>';
      return;
    }
    colors.forEach((c, i) => {
      const sw = document.createElement('div');
      sw.className = 'swatch';
      sw.style.background = c;
      sw.title = c;
      sw.dataset.index = i;
      sw.addEventListener('click', () => {
        $$('.swatch', this.row).forEach(s => s.classList.remove('active'));
        sw.classList.add('active');
        this.onSelect?.(i, c);
      });
      this.row.appendChild(sw);
    });
  }
}

/* ── LayerPanel ─────────────────────────────────────────────────────────────── */
class LayerPanel {
  constructor(list, onToggle, onSelect) {
    this.list = list;
    this.onToggle = onToggle;
    this.onSelect = onSelect;
    this._hidden = new Set();
  }
  render(layers) {
    this.list.innerHTML = '';
    if (!layers?.length) {
      this.list.innerHTML = '<li style="padding:.6rem .75rem;color:var(--text-dim);font-size:.78rem">No layers</li>';
      return;
    }
    layers.forEach((layer, i) => {
      const li = document.createElement('li');
      li.className = 'layer-item' + (this._hidden.has(i) ? ' hidden' : '');
      li.dataset.index = i;
      li.innerHTML = `
        <button class="layer-eye${this._hidden.has(i) ? ' hidden' : ''}" data-i="${i}" title="Toggle visibility">
          ${this._hidden.has(i) ? '🙈' : '👁'}
        </button>
        <span class="layer-swatch" style="background:${layer.color}"></span>
        <span class="layer-name">${layer.name || ('Layer ' + (i + 1))}</span>
        <span class="layer-pct">${layer.pct ? layer.pct.toFixed(1) + '%' : ''}</span>`;
      li.querySelector('.layer-eye').addEventListener('click', e => {
        e.stopPropagation();
        if (this._hidden.has(i)) this._hidden.delete(i);
        else this._hidden.add(i);
        this.onToggle?.(i, !this._hidden.has(i));
        this.render(layers);
      });
      li.addEventListener('click', () => {
        $$('.layer-item', this.list).forEach(el => el.classList.remove('active'));
        li.classList.add('active');
        this.onSelect?.(i, layer);
      });
      this.list.appendChild(li);
    });
  }
}

/* ── SegmentEditor ──────────────────────────────────────────────────────────── */
class SegmentEditor {
  constructor(app) {
    this.app = app;
    this.selectedLayer = null;
  }
  selectLayer(idx) { this.selectedLayer = idx; }
  async recolor(idx, color) {
    if (!this.app.jobId) return;
    try {
      await fetch('/api/segment/recolor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: this.app.jobId, layer: idx, color })
      });
      this.app.refreshResult();
    } catch (e) { toast.error('Recolor failed: ' + e.message); }
  }
  async mergeLayers(idx1, idx2) {
    if (!this.app.jobId) return;
    try {
      await fetch('/api/segment/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: this.app.jobId, layer1: idx1, layer2: idx2 })
      });
      this.app.refreshResult();
    } catch (e) { toast.error('Merge failed: ' + e.message); }
  }
  async deleteLayer(idx) {
    if (!this.app.jobId) return;
    try {
      await fetch('/api/segment/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: this.app.jobId, layer: idx })
      });
      this.app.refreshResult();
    } catch (e) { toast.error('Delete failed: ' + e.message); }
  }
}

/* ── ExportBar ──────────────────────────────────────────────────────────────── */
class ExportBar {
  constructor(bar, getJobId) {
    this.bar = bar;
    this.getJobId = getJobId;
    this._bind();
  }
  _bind() {
    $$('[data-export]', this.bar).forEach(btn => {
      btn.addEventListener('click', () => this._download(btn.dataset.export));
    });
  }
  async _download(fmt) {
    const jobId = this.getJobId();
    if (!jobId) { toast.error('Nothing to export yet.'); return; }
    const extras = {};
    if (fmt === 'png') {
      const res = $('#png-resolution', this.bar);
      if (res) extras.resolution = parseInt(res.value, 10);
    }
    if (fmt === 'jpg' || fmt === 'jpeg') {
      const q = $('#jpg-quality', this.bar);
      if (q) extras.quality = parseInt(q.value, 10);
    }
    const url = `/api/export?job_id=${jobId}&format=${fmt}` +
      (extras.resolution ? `&resolution=${extras.resolution}` : '') +
      (extras.quality    ? `&quality=${extras.quality}`       : '');
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `vectoreasy-result.${fmt}`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast.success(`Downloaded as ${fmt.toUpperCase()}`);
    } catch (e) { toast.error('Export failed: ' + e.message); }
  }
  setEnabled(enabled) {
    $$('[data-export]', this.bar).forEach(b => b.disabled = !enabled);
  }
}

/* ── BatchProcessor ─────────────────────────────────────────────────────────── */
class BatchProcessor {
  constructor(container, settings) {
    this.container = container;
    this.settings  = settings;
    this.files     = [];
    this.jobs      = new Map();
    this._bindDrop();
  }
  _bindDrop() {
    const drop = this.container.querySelector('.batch-drop');
    if (!drop) return;
    drop.addEventListener('click', () => {
      const inp = document.createElement('input');
      inp.type = 'file';
      inp.accept = 'image/*';
      inp.multiple = true;
      inp.onchange = () => this.addFiles([...inp.files]);
      inp.click();
    });
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag-over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('drag-over'));
    drop.addEventListener('drop', e => {
      e.preventDefault();
      drop.classList.remove('drag-over');
      this.addFiles([...e.dataTransfer.files].filter(f => f.type.startsWith('image/')));
    });

    const startBtn = this.container.querySelector('#batch-start');
    if (startBtn) startBtn.addEventListener('click', () => this.processAll());

    const zipBtn = this.container.querySelector('#batch-download-zip');
    if (zipBtn) zipBtn.addEventListener('click', () => this._downloadZip());
  }
  addFiles(newFiles) {
    newFiles.forEach(f => {
      if (!this.files.find(x => x.name === f.name && x.size === f.size)) this.files.push(f);
    });
    this._renderTable();
  }
  _renderTable() {
    const tbody = this.container.querySelector('#batch-tbody');
    if (!tbody) return;
    tbody.innerHTML = this.files.map((f, i) => {
      const job  = this.jobs.get(i);
      const stat = job?.status || 'queued';
      const pct  = job?.progress || 0;
      return `<tr>
        <td class="batch-filename" title="${f.name}">${f.name}</td>
        <td class="batch-size">${fmt(f.size)}</td>
        <td><span class="batch-status ${stat}">${stat}</span></td>
        <td class="batch-progress-cell">
          <div class="batch-progress-mini"><div class="batch-progress-mini-fill" style="width:${pct}%"></div></div>
        </td>
        <td>${job?.jobId ? `<a href="/api/export?job_id=${job.jobId}&format=svg" class="btn btn-sm btn-outline">SVG</a>` : ''}</td>
      </tr>`;
    }).join('');
  }
  async processAll() {
    for (let i = 0; i < this.files.length; i++) {
      if (this.jobs.get(i)?.status === 'done') continue;
      this.jobs.set(i, { status: 'processing', progress: 0 });
      this._renderTable();
      try {
        const fd = new FormData();
        fd.append('file', this.files[i]);
        const s = this.settings?.values?.() || {};
        Object.entries(s).forEach(([k, v]) => fd.append(k, v));
        const resp = await fetch('/api/vectorize', { method: 'POST', body: fd });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || resp.statusText);
        const jobId = data.job_id;
        await this._poll(i, jobId);
      } catch (e) {
        this.jobs.set(i, { status: 'error', progress: 0, error: e.message });
        this._renderTable();
      }
    }
  }
  async _poll(idx, jobId) {
    return new Promise((resolve, reject) => {
      const iv = setInterval(async () => {
        try {
          const r = await fetch(`/api/status/${jobId}`);
          const d = await r.json();
          this.jobs.set(idx, { status: d.status === 'done' ? 'done' : d.status === 'error' ? 'error' : 'processing', progress: d.progress || 0, jobId });
          this._renderTable();
          if (d.status === 'done')       { clearInterval(iv); resolve(); }
          else if (d.status === 'error') { clearInterval(iv); reject(new Error(d.error || 'Failed')); }
        } catch (e) { clearInterval(iv); reject(e); }
      }, 600);
    });
  }
  async _downloadZip() {
    const jobIds = [...this.jobs.values()].filter(j => j.status === 'done').map(j => j.jobId);
    if (!jobIds.length) { toast.error('No completed jobs to download.'); return; }
    const resp = await fetch('/api/batch/download-zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_ids: jobIds })
    });
    if (!resp.ok) { toast.error('ZIP download failed.'); return; }
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'vectoreasy-batch.zip';
    a.click();
    URL.revokeObjectURL(a.href);
  }
}

/* ── VectorEasyApp (main) ───────────────────────────────────────────────────── */
class VectorEasyApp {
  constructor() {
    this.jobId       = null;
    this.currentFile = null;
    this.currentDataUrl = null;
    this.resultSvg   = null;
    this.layers      = [];
    this.colors      = [];
    this._ws         = null;
    this._pollTimer  = null;

    this._initComponents();
    this._bindKeyboard();
    this._bindButtons();
    this._bindViewToggle();
    this._bindWebSocket();
  }

  /* ── Init ─────────────────────────────────────────────────────────────────── */
  _initComponents() {
    // Progress bar
    const progressWrap = $('#progress-wrap');
    this.progress = progressWrap ? new ProgressBar(progressWrap) : null;

    // Upload
    const zone = $('#upload-zone');
    if (zone) this.uploader = new ImageUploader(zone, (f, dataUrl) => this._onFile(f, dataUrl));

    // Previews
    const origPanel = $('#panel-original');
    const vecPanel  = $('#panel-vectorized');
    this.origPreview = origPanel ? new PreviewPanel(origPanel) : null;
    this.vecPreview  = vecPanel  ? new PreviewPanel(vecPanel)  : null;

    // Comparison
    const compContainer = $('#comparison-container');
    this.comparison = compContainer ? new ComparisonSlider(compContainer) : null;

    // Settings
    const sidePanel = $('#controls-panel');
    this.settings = sidePanel ? new SettingsPanel(sidePanel, () => {}) : null;

    // Palette
    const paletteRow = $('#palette-row');
    this.palette = paletteRow ? new ColorPalette(paletteRow, (i, c) => this._onPaletteSelect(i, c)) : null;

    // Layers
    const layerList = $('#layer-list');
    this.layers_panel = layerList
      ? new LayerPanel(layerList,
          (i, vis) => this._onLayerToggle(i, vis),
          (i, l)   => this._onLayerSelect(i, l))
      : null;

    // Segment editor
    this.segEditor = new SegmentEditor(this);

    // Export bar
    const exportBar = $('#export-bar');
    this.exportBar = exportBar ? new ExportBar(exportBar, () => this.jobId) : null;
    if (this.exportBar) this.exportBar.setEnabled(false);

    // Batch
    const batchPanel = $('#batch-panel');
    this.batch = batchPanel ? new BatchProcessor(batchPanel, this.settings) : null;

    // Init zoom buttons
    this._initZoomButtons();
  }

  _initZoomButtons() {
    $$('.zoom-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const panel = btn.closest('.preview-panel');
        const which = panel?.id === 'panel-original' ? this.origPreview : this.vecPreview;
        if (!which) return;
        const action = btn.dataset.action;
        if (action === 'in')  which.zoom(1.25);
        if (action === 'out') which.zoom(0.8);
        if (action === 'fit') which.fitToScreen();
      });
    });
  }

  /* ── File Handling ────────────────────────────────────────────────────────── */
  _onFile(file, dataUrl) {
    this.currentFile   = file;
    this.currentDataUrl = dataUrl;
    this.jobId = null;
    this.resultSvg = null;

    if (this.origPreview) this.origPreview.load(dataUrl);
    if (this.vecPreview)  this.vecPreview.clear();
    if (this.palette)     this.palette.render([]);
    if (this.layers_panel) this.layers_panel.render([]);
    if (this.exportBar)   this.exportBar.setEnabled(false);

    // Hide upload zone, show work area
    const uploadSection = $('#upload-section');
    const workArea      = $('#work-area');
    if (uploadSection) uploadSection.classList.add('hidden');
    if (workArea)      workArea.classList.remove('hidden');

    // Show file info
    const fnEl = $('#current-filename');
    const fsEl = $('#current-filesize');
    if (fnEl) fnEl.textContent = file.name;
    if (fsEl) fsEl.textContent = fmt(file.size);

    this._vectorize();
  }

  /* ── Vectorize ────────────────────────────────────────────────────────────── */
  async _vectorize() {
    if (!this.currentFile) return;
    if (this.progress) this.progress.show('Uploading…', 5);

    const fd = new FormData();
    fd.append('file', this.currentFile);
    const s = this.settings?.values?.() || {};
    Object.entries(s).forEach(([k, v]) => fd.append(k, v));

    try {
      const resp = await fetch('/api/vectorize', { method: 'POST', body: fd });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || resp.statusText);
      this.jobId = data.job_id;
      this._startPolling();
    } catch (e) {
      if (this.progress) this.progress.error('Upload failed: ' + e.message);
      toast.error('Failed: ' + e.message);
    }
  }

  /* ── Polling ──────────────────────────────────────────────────────────────── */
  _startPolling() {
    this._stopPolling();
    this._pollTimer = setInterval(() => this._poll(), 500);
  }
  _stopPolling() {
    if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
  }
  async _poll() {
    if (!this.jobId) { this._stopPolling(); return; }
    try {
      const r = await fetch(`/api/status/${this.jobId}`);
      const d = await r.json();
      if (this.progress) this.progress.update(d.stage || 'Processing…', d.progress || 0);
      if (d.status === 'done') {
        this._stopPolling();
        this._onDone(d);
      } else if (d.status === 'error') {
        this._stopPolling();
        if (this.progress) this.progress.error(d.error || 'Processing failed');
        toast.error(d.error || 'Processing failed');
      }
    } catch (e) { console.warn('Poll error:', e); }
  }

  _onDone(d) {
    if (this.progress) this.progress.complete('Done!');
    this.colors = d.colors || [];
    this.layers = d.layers || [];
    this.resultSvg = d.svg_url || null;

    if (this.palette)      this.palette.render(this.colors);
    if (this.layers_panel) this.layers_panel.render(this.layers);
    if (this.exportBar)    this.exportBar.setEnabled(true);

    if (this.vecPreview && this.resultSvg) {
      this.vecPreview.load(this.resultSvg, true);
    }
    toast.success('Vectorization complete!');
    this._enableDrag();
    setTimeout(() => this.progress?.hide(), 3000);
  }

  async refreshResult() {
    if (!this.jobId) return;
    const r = await fetch(`/api/status/${this.jobId}`);
    const d = await r.json();
    this._onDone(d);
  }

  /* ── Draggable output ─────────────────────────────────────────────────────── */
  _enableDrag() {
    const wrap = $('#panel-vectorized .preview-canvas-wrap');
    if (!wrap || !this.resultSvg) return;
    const img = wrap.querySelector('img, object');
    if (!img) return;
    img.draggable = true;
    img.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/uri-list', this.resultSvg);
      e.dataTransfer.effectAllowed = 'copy';
    });
  }

  /* ── WebSocket (optional) ─────────────────────────────────────────────────── */
  _bindWebSocket() {
    if (!('WebSocket' in window)) return;
    try {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      this._ws = new WebSocket(`${proto}://${location.host}/ws`);
      this._ws.onmessage = e => {
        let d;
        try { d = JSON.parse(e.data); } catch { return; }
        if (!d.job_id || d.job_id !== this.jobId) return;
        if (this.progress) this.progress.update(d.stage || 'Processing…', d.progress || 0);
        if (d.status === 'done')       { this._stopPolling(); this._onDone(d); }
        else if (d.status === 'error') { this._stopPolling(); this.progress?.error(d.error || 'Error'); toast.error(d.error || 'Error'); }
      };
      this._ws.onerror = () => { this._ws = null; }; // fall back to polling
    } catch (_) {}
  }

  /* ── View Toggle ──────────────────────────────────────────────────────────── */
  _bindViewToggle() {
    $$('.view-toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.view-toggle-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const mode = btn.dataset.view;
        const panels = $('#preview-panels');
        const comp   = $('#comparison-container');
        if (mode === 'split') {
          if (panels) panels.classList.remove('hidden');
          if (comp)   comp.classList.remove('active');
        } else if (mode === 'compare') {
          if (panels) panels.classList.add('hidden');
          if (comp)   comp.classList.add('active');
          this._syncComparison();
        } else if (mode === 'original') {
          this._showSingle('original');
        } else if (mode === 'vector') {
          this._showSingle('vector');
        }
      });
    });
  }
  _showSingle(which) {
    const origPanel = $('#panel-original');
    const vecPanel  = $('#panel-vectorized');
    if (which === 'original') {
      if (origPanel) origPanel.style.display = '';
      if (vecPanel)  vecPanel.style.display = 'none';
    } else {
      if (origPanel) origPanel.style.display = 'none';
      if (vecPanel)  vecPanel.style.display = '';
    }
  }
  _syncComparison() {
    const origCont = $('#comparison-bg');
    const vecCont  = $('#comparison-fg-inner');
    if (this.currentDataUrl && origCont) origCont.innerHTML = `<img src="${this.currentDataUrl}" style="width:100%;height:100%;object-fit:contain">`;
    if (this.resultSvg && vecCont)       vecCont.innerHTML  = `<img src="${this.resultSvg}" style="width:100%;height:100%;object-fit:contain">`;
  }

  /* ── Misc event handlers ──────────────────────────────────────────────────── */
  _onPaletteSelect(i, color) {
    this.segEditor.selectLayer(i);
    const li = $(`.layer-item[data-index="${i}"]`);
    if (li) { $$('.layer-item').forEach(el => el.classList.remove('active')); li.classList.add('active'); }
  }
  _onLayerSelect(i, layer) {
    this.segEditor.selectLayer(i);
    const sw = $(`.swatch[data-index="${i}"]`);
    if (sw) { $$('.swatch').forEach(s => s.classList.remove('active')); sw.classList.add('active'); }
  }
  _onLayerToggle(i, visible) {}

  /* ── Buttons ──────────────────────────────────────────────────────────────── */
  _bindButtons() {
    const newImgBtn = $('#btn-new-image');
    if (newImgBtn) newImgBtn.addEventListener('click', () => this._reset());

    const reprocessBtn = $('#btn-reprocess');
    if (reprocessBtn) reprocessBtn.addEventListener('click', () => this._vectorize());

    const batchTabBtn = $('#btn-batch-tab');
    if (batchTabBtn) batchTabBtn.addEventListener('click', () => this._showBatch());

    $$('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.tab;
        $$('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === target));
        $$('.tab-pane').forEach(p => p.classList.toggle('active', p.id === 'tab-' + target));
      });
    });

    // Recolor button
    const recolorBtn = $('#btn-recolor');
    if (recolorBtn) {
      recolorBtn.addEventListener('click', () => {
        const colorPick = $('#recolor-pick');
        if (colorPick && this.segEditor.selectedLayer !== null)
          this.segEditor.recolor(this.segEditor.selectedLayer, colorPick.value);
      });
    }

    // Delete layer
    const delBtn = $('#btn-delete-layer');
    if (delBtn) delBtn.addEventListener('click', () => {
      if (this.segEditor.selectedLayer !== null)
        this.segEditor.deleteLayer(this.segEditor.selectedLayer);
    });

    // Auto-color checkbox
    const autoColors = $('#auto-colors');
    const colorSlider = $('#color-count');
    if (autoColors && colorSlider) {
      autoColors.addEventListener('change', () => {
        colorSlider.disabled = autoColors.checked;
        const val = colorSlider.closest('.ctrl-section')?.querySelector('.val');
        if (val) val.textContent = autoColors.checked ? 'Auto' : colorSlider.value;
      });
    }
  }

  _reset() {
    this.jobId = null;
    this.currentFile = null;
    this.currentDataUrl = null;
    this.resultSvg = null;
    this._stopPolling();
    if (this.origPreview) this.origPreview.clear();
    if (this.vecPreview)  this.vecPreview.clear();
    if (this.palette)     this.palette.render([]);
    if (this.layers_panel) this.layers_panel.render([]);
    if (this.exportBar)   this.exportBar.setEnabled(false);
    if (this.progress)    this.progress.hide();

    const uploadSection = $('#upload-section');
    const workArea      = $('#work-area');
    if (uploadSection) uploadSection.classList.remove('hidden');
    if (workArea)      workArea.classList.add('hidden');
  }

  _showBatch() {
    $$('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === 'batch'));
    $$('.tab-pane').forEach(p => p.classList.toggle('active', p.id === 'tab-batch'));
  }

  /* ── Keyboard Shortcuts ───────────────────────────────────────────────────── */
  _bindKeyboard() {
    document.addEventListener('keydown', e => {
      const tag = document.activeElement.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const ctrl = e.ctrlKey || e.metaKey;

      if (ctrl && e.key === 's') { e.preventDefault(); this._quickDownload('svg'); }
      if (ctrl && e.key === 'v') return; // let paste event handle it
      if (e.key === '+' || e.key === '=') { this.vecPreview?.zoom(1.2); this.origPreview?.zoom(1.2); }
      if (e.key === '-') { this.vecPreview?.zoom(0.83); this.origPreview?.zoom(0.83); }
      if (e.key === '0') { this.vecPreview?.fitToScreen(); this.origPreview?.fitToScreen(); }
      if (e.key === ' ') {
        e.preventDefault();
        const vbtn = $('.view-toggle-btn[data-view="original"]');
        const sbtn = $('.view-toggle-btn[data-view="split"]');
        const active = $('.view-toggle-btn.active');
        if (active?.dataset.view === 'original') sbtn?.click();
        else vbtn?.click();
      }
    });
  }

  async _quickDownload(fmt) {
    if (!this.jobId) { toast.error('Nothing to download yet.'); return; }
    const resp = await fetch(`/api/export?job_id=${this.jobId}&format=${fmt}`);
    if (!resp.ok) { toast.error('Download failed.'); return; }
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `vectoreasy.${fmt}`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
}

/* ── Bootstrap ──────────────────────────────────────────────────────────────── */
const toast = new Toast();

document.addEventListener('DOMContentLoaded', () => {
  window.app = new VectorEasyApp();
});
