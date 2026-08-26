function toast(message, bad) {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.toggle('bad', !!bad);
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3200);
}

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) {
    toast(data.detail || data.message || ('HTTP ' + res.status), true);
    throw new Error('request failed');
  }
  return data;
}

/* Fields save themselves: text after a short pause, everything else at once. */
function autosave(root, url) {
  root.querySelectorAll('[data-field]').forEach(el => {
    const instant = el.type === 'checkbox' || el.tagName === 'SELECT';
    let timer;
    const send = async () => {
      const value = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value;
      await api('POST', url, { [el.dataset.field]: value });
      toast('Saved');
    };
    el.addEventListener(instant ? 'change' : 'input', () => {
      clearTimeout(timer);
      if (instant) send(); else timer = setTimeout(send, 700);
    });
  });
}

/* Scene fields post one key at a time and get the re-rendered prompt back. */
function autosaveFields(root, url, onRendered) {
  root.querySelectorAll('[data-pfield]').forEach(el => {
    let timer;
    el.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const r = await api('POST', url, { [el.dataset.pfield]: el.value });
        toast('Saved');
        if (onRendered) onRendered(r.prompt);
      }, 700);
    });
  });
}

/* Drag-and-drop reordering. Cards sit several per row, so the drop side comes
   from the cursor's X when the item is narrower than the container, and from
   its Y when the list is a single column. */
function initReorder(listEl, onDrop) {
  let dragged = null;
  listEl.querySelectorAll('li[draggable]').forEach(li => {
    li.addEventListener('dragstart', () => {
      dragged = li;
      li.classList.add('dragging');
    });
    li.addEventListener('dragend', () => {
      li.classList.remove('dragging');
      listEl.querySelectorAll('li').forEach(x => x.classList.remove('over'));
      onDrop([...listEl.querySelectorAll('li')].map(x => Number(x.dataset.id)));
    });
    li.addEventListener('dragover', e => {
      e.preventDefault();
      if (!dragged || dragged === li) return;
      li.classList.add('over');
      const rect = li.getBoundingClientRect();
      const grid = rect.width < listEl.clientWidth - 4;
      const after = grid
        ? e.clientX > rect.left + rect.width / 2
        : e.clientY > rect.top + rect.height / 2;
      listEl.insertBefore(dragged, after ? li.nextSibling : li);
    });
    li.addEventListener('dragleave', () => li.classList.remove('over'));
  });
}
