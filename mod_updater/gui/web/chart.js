/* Gráfico de columnas de bloques isométricos (SVG propio, sin librerías).

   Cada columna es un prisma cuya ALTURA es proporcional al número de mods; las juntas de
   los bloques son textura (cada BLOCK px), no unidades, para no falsear el valor. Caras de
   piedra gris y cara superior verde hierba (un solo color de serie). El número va sobre la
   columna y el icono de la categoría encima.

   renderBlockChart(el, bars, { onSelect, selected }) donde bars = [{ id, count, name, short, icon }].
   Cada columna es un <button>: foco o ratón llaman a onSelect(id). */
"use strict";

const CHART = { W: 24, D: 10, HMAX: 180, HMIN: 6, BLOCK: 14 };

function blockPrism(h) {
  const { W, D, BLOCK } = CHART;
  const top = D / 2;
  const seams = [];
  for (let y = top + BLOCK; y < top + h - 2; y += BLOCK) {
    seams.push(`<path class="seam" d="M0 ${y}H${W}L${W + D} ${y - top}"/>`);
  }
  const grass = Math.min(4, h);  // franja de hierba bajo la cara superior
  return `<svg class="prism" width="${W + D}" height="${h + top}" viewBox="0 0 ${W + D} ${h + top}" aria-hidden="true">
    <polygon class="face-front" points="0,${top} ${W},${top} ${W},${top + h} 0,${top + h}"/>
    <polygon class="face-side" points="${W},${top} ${W + D},0 ${W + D},${h} ${W},${top + h}"/>
    ${seams.join("")}
    <polygon class="grass-front" points="0,${top} ${W},${top} ${W},${top + grass} 0,${top + grass}"/>
    <polygon class="grass-side" points="${W},${top} ${W + D},0 ${W + D},${grass} ${W},${top + grass}"/>
    <polygon class="face-top" points="0,${top} ${D},0 ${W + D},0 ${W},${top}"/>
  </svg>`;
}

function renderBlockChart(el, bars, { onSelect, selected, label } = {}) {
  const max = Math.max(1, ...bars.map(b => b.count));
  el.innerHTML = `<div class="blocks">${bars.map((b, i) => {
    const h = Math.max(CHART.HMIN, Math.round((b.count / max) * CHART.HMAX));
    return `<div class="block-col" style="--i:${i}">
      <button class="block-btn${b.id === selected ? " on" : ""}" type="button" data-cat="${b.id}"
              aria-pressed="${b.id === selected}" tabindex="${b.id === selected ? 0 : -1}" aria-label="${esc(label ? label(b) : `${b.name}: ${b.count}`)}">
        <span class="block-icon">${b.icon}</span>
        <span class="block-value">${b.count}</span>
        ${blockPrism(h)}
      </button>
      <span class="block-label" title="${esc(b.name)}">${esc(b.short)}</span>
    </div>`;
  }).join("")}</div>`;
  const btns = [...el.querySelectorAll(".block-btn")];
  for (const btn of btns) {
    const pick = () => {
      for (const b of btns) b.tabIndex = b === btn ? 0 : -1;  // una sola parada de tabulador
      if (onSelect) onSelect(btn.dataset.cat);
    };
    btn.addEventListener("click", pick);
    btn.addEventListener("focus", pick);
    btn.addEventListener("mouseenter", pick);
  }
  // Flechas, Inicio y Fin recorren las columnas.
  el.onkeydown = e => {
    const i = btns.indexOf(document.activeElement);
    if (i < 0) return;
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: btns.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    btns[Math.max(0, Math.min(btns.length - 1, next))].focus();
  };
}
