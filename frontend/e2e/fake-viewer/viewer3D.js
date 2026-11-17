/*
 * Viewer FALSO para o E2E sem APS. O Playwright serve este arquivo no lugar de
 * .../viewers/7.x/viewer3D.min.js. Implementa só o que o ApsViewerAdapter usa e
 * desenha cada peça (window.__E2E_PIECES = [{dbid, label}]) como um botão
 * "3D" clicável. Selecionadas: aria-pressed="true". Ctrl+clique acumula, como
 * no Viewer real. Cor aplicada por setThemingColor: data-color="#rrggbb" (borda do botão).
 *
 * Coordenadas do eixo: cada peça tem uma caixa (piece.geom = {origin, a, b, c}, em PÉS,
 * coordenadas de mundo; sem geom, uma caixa vertical própria) servida como no SVF2: malha
 * unitária normalizada + matriz do fragmento. Modelo em pés (getUnitScale 0,3048) com
 * globalOffset (100, 200, 5) e refPointTransformation identidade no AEC. O marcador do
 * eixo (overlay) aparece em data-eixo="ponto|linha" no contêiner das peças.
 */
(function () {
  'use strict';
  var SELECTION = 'selection';
  var SELECTION_HEX = '#3C3C3C'; // SELECTION_COLOR do app

  var GLOBAL_OFFSET = { x: 100, y: 200, z: 5 };
  // cubo unitário (malha normalizada do SVF2): 8 vértices, 12 triângulos
  var UNIT_VB = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1];
  var UNIT_IB = [0, 3, 2, 0, 2, 1, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6, 3, 0, 4, 3, 4, 7];

  function pieceOf(dbid) {
    return (window.__E2E_PIECES || []).find(function (p) { return p.dbid === dbid; }) || null;
  }
  function geomOf(piece) {
    if (piece.geom) return piece.geom;
    // padrão: pilar 1 x 1 x 10 pés, cada peça num lugar
    return { origin: [piece.dbid * 5, 0, 0], a: [1, 0, 0], b: [0, 1, 0], c: [0, 0, 10] };
  }

  function makeModel() {
    var root = 1;
    return {
      getData: function () { return { globalOffset: GLOBAL_OFFSET }; },
      getUnitScale: function () { return 0.3048; },
      getInstanceTree: function () {
        return {
          getRootId: function () { return root; },
          getNodeParentId: function (id) { return id === root ? 0 : root; },
          getNodeName: function (id) { var p = pieceOf(id); return p ? p.label : ''; },
          enumNodeChildren: function (id, cb) {
            if (id !== root) return;
            (window.__E2E_PIECES || []).forEach(function (p) { cb(p.dbid); });
          },
          enumNodeFragments: function (id, cb) { if (pieceOf(id)) cb(id); },
        };
      },
      getFragmentList: function () {
        return {
          getWorldMatrix: function (fragId, out) {
            var g = geomOf(pieceOf(fragId));
            out.elements = [g.a[0], g.a[1], g.a[2], 0, g.b[0], g.b[1], g.b[2], 0, g.c[0], g.c[1], g.c[2], 0, g.origin[0], g.origin[1], g.origin[2], 1];
          },
        };
      },
      getProperties: function (id, ok, fail) {
        var p = pieceOf(id);
        if (!p) { fail(new Error('sem propriedades')); return; }
        ok({
          name: p.label,
          properties: [
            { displayName: 'Category', displayCategory: 'Element', displayValue: p.category || 'Pilares estruturais' },
            { displayName: 'Material', displayCategory: 'Materiais', displayValue: 'Concreto, Pré-moldado' },
          ],
        });
      },
    };
  }

  function GuiViewer3D(container) {
    this.container = container;
    var self = this;
    this.overlay = [];
    this.impl = {
      getRenderProxy: function (model, fragId) {
        return pieceOf(fragId) ? { geometry: { vb: UNIT_VB, vbstride: 3, attributes: { position: { offset: 0 } }, ib: UNIT_IB } } : null;
      },
      createOverlayScene: function () {},
      addOverlay: function (name, obj) { self.overlay.push(obj); },
      removeOverlay: function (name, obj) { self.overlay = self.overlay.filter(function (o) { return o !== obj; }); },
      invalidate: function () {
        if (!self.root) return;
        var line = self.overlay.some(function (o) { return o.kind === 'line'; });
        var dots = self.overlay.filter(function (o) { return o.kind === 'mesh'; }).length;
        if (line) self.root.setAttribute('data-eixo', 'linha');
        else if (dots) self.root.setAttribute('data-eixo', 'ponto');
        else self.root.removeAttribute('data-eixo');
      },
    };
    this.listeners = [];
    this.selected = [];
    this.hiddenIds = []; // escondidos por hide() (isolate/showAll mostram de novo)
    this.shown = null; // destacados (os demais esmaecidos ou ocultos)
    this.ghosting = true;
    this.buttons = new Map();
    this.colors = new Map(); // dbid -> '#rrggbb' (cor de base da coloração)
    this.selTheme = new Set(); // pintadas com a cor de seleção por cima (data-base-color guarda a base)
  }
  GuiViewer3D.prototype.start = function () {
    this.root = document.createElement('div');
    this.root.setAttribute('data-testid', 'fake-3d');
    // peças à esquerda, longe da legenda (à direita) e da barra inferior
    this.root.style.cssText = 'position:absolute;inset:140px 260px 12px 12px;display:flex;flex-wrap:wrap;gap:6px;align-content:flex-start';
    this.container.appendChild(this.root);
    // imita a barra de ferramentas nativa do Viewer v7: embaixo, centralizada, sobre o desenho
    this.nativeBar = document.createElement('div');
    this.nativeBar.id = 'guiviewer3d-toolbar';
    this.nativeBar.setAttribute('role', 'toolbar');
    this.nativeBar.setAttribute('aria-label', 'Barra nativa do Viewer');
    this.nativeBar.style.cssText = 'position:absolute;bottom:12px;left:50%;transform:translateX(-50%);z-index:1;display:flex;gap:4px;padding:4px;background:#222;border-radius:4px';
    ['Órbita', 'Seção', 'Propriedades'].forEach(function (name) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = name;
      b.style.cssText = 'min-height:36px;padding:0 10px;background:#333;color:#fff;border:0;border-radius:3px';
      b.addEventListener('click', function () { window.__E2E_NATIVE_CLICKS = (window.__E2E_NATIVE_CLICKS || 0) + 1; });
      this.nativeBar.appendChild(b);
    }, this);
    this.container.appendChild(this.nativeBar);
    return 0;
  };
  GuiViewer3D.prototype.finish = function () {
    if (this.root) this.root.remove();
    if (this.nativeBar) this.nativeBar.remove();
  };
  GuiViewer3D.prototype.addEventListener = function (type, cb) {
    if (type === SELECTION) this.listeners.push(cb);
  };
  GuiViewer3D.prototype._emit = function () {
    var ids = this.selected.slice();
    this.listeners.forEach(function (cb) { cb({ dbIdArray: ids }); });
  };
  GuiViewer3D.prototype._paint = function () {
    var self = this;
    this.buttons.forEach(function (btn, dbid) {
      btn.setAttribute('aria-pressed', String(self.selected.indexOf(dbid) >= 0));
      btn.style.background = self.selected.indexOf(dbid) >= 0 ? SELECTION_HEX : '#fff';
      btn.style.color = self.selected.indexOf(dbid) >= 0 ? '#fff' : '#1B2430';
      var out = self.shown !== null && self.shown.indexOf(dbid) < 0;
      var gone = self.hiddenIds.indexOf(dbid) >= 0 || (out && !self.ghosting);
      btn.hidden = gone;
      btn.setAttribute('data-state', gone ? 'oculta' : out ? 'esmaecida' : 'normal');
      btn.style.opacity = out && self.ghosting ? '0.25' : '1';
      var base = self.colors.get(dbid);
      var color = self.selTheme.has(dbid) ? SELECTION_HEX : base;
      if (color) btn.setAttribute('data-color', color);
      else btn.removeAttribute('data-color');
      if (base) btn.setAttribute('data-base-color', base);
      else btn.removeAttribute('data-base-color');
      btn.style.borderBottom = color ? '6px solid ' + color : '';
    });
  };
  GuiViewer3D.prototype.loadDocumentNode = function () {
    var self = this;
    var model = makeModel();
    return new Promise(function (resolve) {
      setTimeout(function () {
        // Nova carga (troca de versão): começa do zero.
        self.buttons.forEach(function (btn) { btn.remove(); });
        self.buttons.clear();
        self.colors.clear();
        self.selTheme.clear();
        self.selected = [];
        self.shown = null;
        (window.__E2E_PIECES || []).forEach(function (piece) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.style.cssText = 'min-height:30px;padding:2px 8px;font-size:12px';
          btn.textContent = piece.label;
          btn.setAttribute('data-dbid', String(piece.dbid));
          btn.addEventListener('click', function (ev) {
            var id = piece.dbid;
            if (ev.ctrlKey || ev.metaKey) {
              var at = self.selected.indexOf(id);
              if (at >= 0) self.selected.splice(at, 1);
              else self.selected.push(id);
            } else {
              self.selected = [id];
            }
            self._paint();
            self._emit();
          });
          self.buttons.set(piece.dbid, btn);
          self.root.appendChild(btn);
        });
        self._paint();
        resolve(model);
      }, 300);
    });
  };
  GuiViewer3D.prototype.select = function (ids) { this.selected = ids.slice(); this._paint(); this._emit(); };
  GuiViewer3D.prototype.clearSelection = function () { this.selected = []; this._paint(); this._emit(); };
  GuiViewer3D.prototype.setGhosting = function (on) { this.ghosting = on; };
  GuiViewer3D.prototype.isolate = function (ids) { this.shown = ids.length ? ids.slice() : null; this.hiddenIds = []; this._paint(); };
  GuiViewer3D.prototype.hide = function (ids) { this.hiddenIds = this.hiddenIds.concat(ids); this._paint(); };
  GuiViewer3D.prototype.showAll = function () { this.shown = null; this.hiddenIds = []; this._paint(); };
  GuiViewer3D.prototype.fitToView = function () {};
  GuiViewer3D.prototype.resize = function () { window.__E2E_RESIZES = (window.__E2E_RESIZES || 0) + 1; };
  function hex(v) {
    return '#' + [v.x, v.y, v.z].map(function (c) {
      return ('0' + Math.round(c * 255).toString(16)).slice(-2);
    }).join('').toUpperCase();
  }
  GuiViewer3D.prototype.setThemingColor = function (dbid, v) {
    var h = hex(v);
    if (v.w === 0) { this.colors.delete(dbid); this.selTheme.delete(dbid); } // alfa 0: sem cor
    else if (h === SELECTION_HEX) this.selTheme.add(dbid); // grafite da seleção por cima da base
    else { this.colors.set(dbid, h); this.selTheme.delete(dbid); }
    this._paint();
  };
  GuiViewer3D.prototype.clearThemingColors = function () { this.colors.clear(); this.selTheme.clear(); this._paint(); };

  function Obj(kind) { this.kind = kind; this.position = { set: function () {} }; }
  window.THREE = {
    Vector4: function (x, y, z, w) { this.x = x; this.y = y; this.z = z; this.w = w; },
    Vector3: function (x, y, z) { this.x = x; this.y = y; this.z = z; },
    Matrix4: function () { this.elements = []; },
    Geometry: function () { this.vertices = []; },
    SphereGeometry: function () {},
    MeshBasicMaterial: function () {},
    LineBasicMaterial: function () {},
    Mesh: function () { Obj.call(this, 'mesh'); },
    Line: function () { Obj.call(this, 'line'); },
  };
  window.Autodesk = {
    Viewing: {
      SELECTION_CHANGED_EVENT: SELECTION,
      Initializer: function (options, onReady) {
        window.__E2E_INIT = { env: options.env, api: options.api };
        options.getAccessToken(function () { onReady(); });
      },
      GuiViewer3D: GuiViewer3D,
      Document: {
        load: function (urn, ok) {
          window.__E2E_URN = urn;
          ok({ getRoot: function () { return { getDefaultGeometry: function () { return {}; } }; } });
        },
        getAecModelData: function () {
          return Promise.resolve({ refPointTransformation: [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0] });
        },
      },
    },
  };
})();
