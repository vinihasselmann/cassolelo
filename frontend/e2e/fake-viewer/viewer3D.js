/*
 * Viewer FALSO para o E2E sem APS. O Playwright serve este arquivo no lugar de
 * .../viewers/7.x/viewer3D.min.js. Implementa só o que o ApsViewerAdapter usa e
 * desenha cada peça (window.__E2E_PIECES = [{dbid, label}]) como um botão
 * "3D" clicável. Selecionadas: aria-pressed="true". Ctrl+clique acumula, como
 * no Viewer real. Cor aplicada por setThemingColor: data-color="#rrggbb" (borda do botão).
 */
(function () {
  'use strict';
  var SELECTION = 'selection';
  var SELECTION_HEX = '#2F6FEB'; // SELECTION_COLOR do app

  function GuiViewer3D(container) {
    this.container = container;
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
    return 0;
  };
  GuiViewer3D.prototype.finish = function () {
    if (this.root) this.root.remove();
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
      btn.style.background = self.selected.indexOf(dbid) >= 0 ? '#2F6FEB' : '#fff';
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
        resolve({});
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
  function hex(v) {
    return '#' + [v.x, v.y, v.z].map(function (c) {
      return ('0' + Math.round(c * 255).toString(16)).slice(-2);
    }).join('').toUpperCase();
  }
  GuiViewer3D.prototype.setThemingColor = function (dbid, v) {
    var h = hex(v);
    if (v.w === 0) { this.colors.delete(dbid); this.selTheme.delete(dbid); } // alfa 0: sem cor
    else if (h === SELECTION_HEX) this.selTheme.add(dbid); // azul da seleção por cima da base
    else { this.colors.set(dbid, h); this.selTheme.delete(dbid); }
    this._paint();
  };
  GuiViewer3D.prototype.clearThemingColors = function () { this.colors.clear(); this.selTheme.clear(); this._paint(); };

  window.THREE = { Vector4: function (x, y, z, w) { this.x = x; this.y = y; this.z = z; this.w = w; } };
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
      },
    },
  };
})();
