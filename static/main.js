// static/main.js
// Autocomplete acessível para o campo de busca (#q) usando /api/meta?q=....
// - WAI-ARIA combobox + listbox (setas ↑/↓, Enter, Esc)  [APG Combobox Example]
// - Dispara no evento 'input' com debounce                [MDN input event]
// - Sugestões: cartas (nome, set_code, número), “atalhos” (buscar na Liga/eBay)
// - Sem dependências. Funciona junto com o resto da página.

(() => {
  const SELECTOR_INPUT = '#q'; // ajuste se seu input tiver outro id
  const API_META = '/api/meta?q='; // já existe no seu app

  // -------- utils --------
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));

  // debounce simples com setTimeout (estável para inputs)
  function debounce(fn, wait = 200) {
    let t = null;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), wait);
    };
  }

  // cria nó com classes + atributos
  function el(tag, opts = {}) {
    const $e = document.createElement(tag);
    if (opts.class) $e.className = opts.class;
    if (opts.attrs) {
      for (const [k, v] of Object.entries(opts.attrs)) {
        if (v !== undefined && v !== null) $e.setAttribute(k, String(v));
      }
    }
    if (opts.text) $e.textContent = opts.text;
    return $e;
  }

  // formata uma sugestão de card vindo do /api/meta
  function toSuggestionFromMeta(card) {
    const name = card.name || '';
    const num = card.number ? String(card.number) : '';
    const setc = card.set_code ? String(card.set_code) : '';
    const rarity = card.rarity || '';
    const label = [name, (setc && num) ? `(${setc} ${num})` : '', rarity ? `[${rarity}]` : '']
      .filter(Boolean)
      .join(' ');
    // value é o que vai pro input ao selecionar
    const value = [name, (num ? num : '')].filter(Boolean).join(' ');
    return {
      type: 'card',
      value,
      label,
      hint: card.set || '',
      image: card.image || null,
    };
  }

  // “atalhos” para abrir fontes com o termo atual
  function quickLinks(term) {
    const q = encodeURIComponent(term.trim());
    return [
      {
        type: 'action',
        value: term,
        label: `Buscar na LigaPokemon por “${term}”`,
        url: `/fonte/ligapokemon?q=${q}`,
      },
      {
        type: 'action',
        value: term,
        label: `Buscar no eBay por “${term}”`,
        url: `/fonte/ebay?q=${q}`,
      },
      {
        type: 'action',
        value: term,
        label: `Estimativa (misturar fontes)`,
        url: `/api/estimate?q=${q}&sources=ligapokemon,ebay`,
      },
    ];
  }

  // consulta /api/meta e devolve array de sugestões
  async function fetchSuggestions(term) {
    const q = term.trim();
    if (q.length < 2) return [];

    try {
      const res = await fetch(`${API_META}${encodeURIComponent(q)}`, { headers: { 'Accept': 'application/json' } });
      if (!res.ok) return quickLinks(q); // degrade para atalhos
      const data = await res.json();
      const cards = Array.isArray(data.items) ? data.items : [];
      const mapped = cards.slice(0, 8).map(toSuggestionFromMeta);

      // heurística: se o usuário digita "4/102", empurrar Charizard 4/102 pro topo
      const boost = [];
      if (/\b4\s*\/\s*102\b/.test(q) || /\b4[\s-]102\b/.test(q)) {
        for (const s of mapped) {
          if (/\b4\s*\/\s*102\b|\b4[\s-]102\b/i.test(s.label)) boost.push(s);
        }
      }
      // dedup simples por label
      const seen = new Set();
      const deduped = [];
      for (const s of [...boost, ...mapped]) {
        if (seen.has(s.label)) continue;
        seen.add(s.label);
        deduped.push(s);
      }

      // acrescenta atalhos no fim
      return [...deduped, ...quickLinks(q)];
    } catch {
      return quickLinks(q);
    }
  }

  // -------- UI (combobox + listbox) --------
  function mountAutocomplete($input) {
    // wrapper de acessibilidade
    const $wrap = el('div', {
      class: 'autocomplete-wrap',
      attrs: {
        role: 'combobox',
        'aria-haspopup': 'listbox',
        'aria-owns': 'suggestions-listbox',
        'aria-expanded': 'false',
        'aria-controls': 'suggestions-listbox',
      },
    });

    // listbox (popup)
    const $list = el('ul', {
      class: 'autocomplete-list',
      attrs: { id: 'suggestions-listbox', role: 'listbox' },
    });

    // estilos mínimos (se preferir, mova para seu CSS)
    const baseCSS = `
.autocomplete-wrap { position: relative; display: block; }
.autocomplete-list {
  position: absolute; z-index: 30; left: 0; right: 0; top: 100%;
  background: #fff; border: 1px solid #ddd; border-radius: 8px;
  margin: 6px 0 0; padding: 6px 0; max-height: 320px; overflow: auto;
  box-shadow: 0 8px 24px rgba(0,0,0,.08);
}
.autocomplete-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px; cursor: pointer; }
.autocomplete-item[aria-selected="true"], .autocomplete-item:hover { background: #f5f7fb; }
.autocomplete-item .meta { font-size: 12px; color: #666; }
.autocomplete-item img { width: 28px; height: 40px; object-fit: cover; border-radius: 4px; flex: none; }
.autocomplete-empty { padding: 10px 12px; color: #666; font-size: 13px; }
`;
    const $style = el('style'); $style.textContent = baseCSS;
    document.head.appendChild($style);

    // injeta wrapper na DOM, envolvendo o input existente
    const parent = $input.parentNode;
    parent.insertBefore($wrap, $input);
    $wrap.appendChild($input);
    $wrap.appendChild($list);

    // estado
    let open = false;
    let highlighted = -1;
    let suggestions = [];

    function openList() {
      if (!open) {
        $wrap.setAttribute('aria-expanded', 'true');
        $list.style.display = 'block';
        open = true;
      }
    }
    function closeList() {
      if (open) {
        $wrap.setAttribute('aria-expanded', 'false');
        $list.style.display = 'none';
        highlighted = -1;
        open = false;
      }
    }

    function renderList(items) {
      suggestions = items;
      $list.innerHTML = '';
      if (!items || items.length === 0) {
        const empty = el('div', { class: 'autocomplete-empty', text: 'Sem sugestões' });
        const li = el('li', { attrs: { role: 'option', 'aria-disabled': 'true' } }); li.appendChild(empty);
        $list.appendChild(li);
        openList();
        return;
      }
      items.forEach((sug, idx) => {
        const li = el('li', {
          class: 'autocomplete-item',
          attrs: {
            id: `sug-${idx}`,
            role: 'option',
            'aria-selected': 'false',
            'data-idx': String(idx),
          },
        });

        if (sug.image) {
          const img = el('img', { attrs: { alt: sug.value, src: sug.image } });
          li.appendChild(img);
        }

        const box = el('div');
        const title = el('div', { text: sug.label });
        const hint = el('div', { class: 'meta', text: sug.hint || (sug.type === 'action' ? 'Atalho' : '') });
        box.appendChild(title);
        if (hint.textContent) box.appendChild(hint);
        li.appendChild(box);

        li.addEventListener('mousedown', (ev) => {
          ev.preventDefault(); // evita blur no input antes do click
          apply(idx);
        });
        $list.appendChild(li);
      });
      openList();
    }

    function highlight(idx) {
      const count = $list.children.length;
      highlighted = clamp(idx, -1, count - 1);
      for (let i = 0; i < count; i++) {
        const li = $list.children[i];
        li.setAttribute('aria-selected', i === highlighted ? 'true' : 'false');
        if (i === highlighted) li.scrollIntoView({ block: 'nearest' });
      }
    }

    function apply(idx) {
      const sug = suggestions[idx];
      if (!sug) return;
      $input.value = sug.value || '';
      closeList();
      // se for atalho com URL, navega
      if (sug.type === 'action' && sug.url) {
        window.location.href = sug.url;
      } else {
        // dispara um submit se existir form
        const form = $input.form;
        if (form) form.submit();
      }
    }

    // eventos
    const onInput = debounce(async () => {
      const term = $input.value || '';
      if (term.trim().length < 2) { closeList(); return; }
      const items = await fetchSuggestions(term);
      renderList(items);
      highlight(-1);
    }, 200);

    $input.addEventListener('input', onInput); // MDN: fires quando value muda
    $input.addEventListener('keydown', (e) => {
      if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        if ($list.children.length) openList();
      }
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          highlight(highlighted + 1);
          break;
        case 'ArrowUp':
          e.preventDefault();
          highlight(highlighted - 1);
          break;
        case 'Enter':
          if (open && highlighted >= 0) {
            e.preventDefault();
            apply(highlighted);
          }
          break;
        case 'Escape':
          if (open) { e.preventDefault(); closeList(); }
          break;
        default:
          break;
      }
    });

    // fecha ao clicar fora
    document.addEventListener('click', (e) => {
      if (!open) return;
      if (!$wrap.contains(e.target)) closeList();
    });

    // acessibilidade: associa input ao listbox
    $input.setAttribute('aria-autocomplete', 'list');
    $input.setAttribute('aria-controls', 'suggestions-listbox');
    $input.setAttribute('aria-expanded', 'false');
  }

  // boot
  document.addEventListener('DOMContentLoaded', () => {
    const $input = document.querySelector(SELECTOR_INPUT);
    if ($input) mountAutocomplete($input);
  });
})();
