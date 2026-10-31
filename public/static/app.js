document.addEventListener('DOMContentLoaded', () => {
  const createText = (tag, content, className) => {
    const node = document.createElement(tag);
    node.textContent = content;
    if (className) node.className = className;
    return node;
  };
  const menu = document.querySelector('.mobile-menu');
  const closeMenu = () => { document.body.classList.remove('nav-open'); menu?.setAttribute('aria-expanded', 'false'); };
  menu?.addEventListener('click', () => menu.setAttribute('aria-expanded', String(document.body.classList.toggle('nav-open'))));
  document.querySelectorAll('[data-nav-close], #main-nav a').forEach(node => node.addEventListener('click', closeMenu));
  window.addEventListener('resize', () => { if (window.innerWidth > 900) closeMenu(); });

  const dialogStack = [];
  const openers = new WeakMap();
  let remoteController, remoteVersion = 0, pendingConfirmation;
  const closeDialog = dialog => {
    if (!dialog?.open) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
    dialog.removeAttribute('aria-modal');
    const index = dialogStack.indexOf(dialog);
    if (index >= 0) dialogStack.splice(index, 1);
    document.body.classList.toggle('modal-open', dialogStack.length > 0);
    if (dialog.id === 'remote-dialog') { ++remoteVersion; remoteController?.abort(); }
    if (dialog.id === 'confirm-action') pendingConfirmation = null;
    const opener = openers.get(dialog);
    if (opener?.isConnected && !opener.closest('[hidden]')) opener.focus();
  };
  const openDialog = (id, opener) => {
    const dialog = document.getElementById(id);
    if (!dialog || dialog.tagName !== 'DIALOG') return null;
    if (opener?.dataset.componentId) {
      const input = dialog.querySelector('[name="component_id"]');
      if (input) input.value = opener.dataset.componentId;
    }
    if (opener?.dataset.message) {
      const message = dialog.querySelector('[data-dialog-message]');
      if (message) message.textContent = opener.dataset.message;
    }
    if (dialog.open) return dialog;
    openers.set(dialog, opener || document.activeElement);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    dialog.setAttribute('aria-modal', 'true');
    dialogStack.push(dialog);
    document.body.classList.add('modal-open');
    const focusTarget = [...dialog.querySelectorAll('[data-autofocus], input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])')]
      .find(node => !node.closest('[hidden]')) || dialog.querySelector('[data-close-dialog]');
    focusTarget?.focus();
    return dialog;
  };
  document.addEventListener('cancel', event => {
    if (event.target.tagName === 'DIALOG') { event.preventDefault(); closeDialog(event.target); }
  }, true);

  const owned = (scope, selector) => [...scope.querySelectorAll(selector)].filter(node => node.closest('[data-tabs]') === scope);
  const activateTab = (scope, name, updateUrl = false) => {
    const buttons = owned(scope, '[data-tab]');
    if (!buttons.some(button => button.dataset.tab === name)) return;
    buttons.forEach(button => {
      const active = button.dataset.tab === name;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
    });
    owned(scope, '[data-panel]').forEach(panel => { panel.hidden = panel.dataset.panel !== name; });
    if (updateUrl && scope.dataset.urlParam) {
      const url = new URL(window.location.href);
      url.searchParams.set(scope.dataset.urlParam, name);
      if (scope.dataset.urlParam === 'section') {
        ['q', 'bom_id', 'open'].forEach(key => url.searchParams.delete(key));
      }
      window.history.replaceState(null, '', url);
      document.querySelectorAll('input[data-section-field]').forEach(input => { input.value = name; });
    }
  };
  const initializeTabs = (root = document) => root.querySelectorAll('[data-tabs]').forEach(scope => {
    const buttons = owned(scope, '[data-tab]');
    const selected = buttons.find(button => button.classList.contains('is-active')) || buttons[0];
    if (selected) activateTab(scope, selected.dataset.tab);
  });
  initializeTabs();

  const normalized = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase();
  const filterState = new WeakMap();
  const refreshFilter = (scope, resetPage = false) => {
    const state = filterState.get(scope) || {page: 1};
    if (resetPage) state.page = 1;
    const query = normalized(scope.querySelector('[data-filter-input]')?.value);
    const activeChip = scope.querySelector('[data-filter-value].is-active');
    const tag = activeChip?.dataset.filterValue || 'all';
    const items = [...scope.querySelectorAll('[data-filter-item]')].filter(item => item.closest('[data-filter]') === scope);
    const matches = items.filter(item => normalized(item.dataset.search || item.textContent).includes(query) &&
      (tag === 'all' || (item.dataset.filterTags || '').split(' ').includes(tag)));
    const pageSize = Number(scope.dataset.pageSize) || Math.max(items.length, 1);
    const pages = Math.max(1, Math.ceil(matches.length / pageSize));
    state.page = Math.min(state.page, pages);
    items.forEach(item => { item.hidden = true; });
    matches.slice((state.page - 1) * pageSize, state.page * pageSize).forEach(item => { item.hidden = false; });
    scope.querySelectorAll('[data-filter-count]').forEach(node => { node.textContent = `${matches.length} kết quả`; });
    const empty = scope.querySelector('[data-filter-empty]');
    if (empty) empty.hidden = matches.length !== 0 || items.length === 0;
    const pagination = scope.querySelector('[data-pagination]');
    if (pagination) {
      pagination.hidden = matches.length <= pageSize;
      const label = pagination.querySelector('[data-page-label]');
      if (label) label.textContent = `Trang ${state.page} / ${pages}`;
      pagination.querySelector('[data-page="prev"]').disabled = state.page <= 1;
      pagination.querySelector('[data-page="next"]').disabled = state.page >= pages;
    }
    filterState.set(scope, state);
  };
  document.querySelectorAll('[data-filter]').forEach(scope => refreshFilter(scope));
  document.addEventListener('input', event => {
    if (event.target.matches('[data-filter-input]')) refreshFilter(event.target.closest('[data-filter]'), true);
  });

  const loadRemote = async link => {
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    const dialog = openDialog('remote-dialog', link);
    const content = document.getElementById('remote-dialog-content');
    if (!dialog || !content) { window.location.href = link.href; return; }
    document.getElementById('remote-dialog-title').textContent = link.dataset.dialogTitle || 'Chi tiết đơn hàng';
    content.replaceChildren(createText('div', 'Đang tải thông tin…', 'loading-state'));
    remoteController?.abort();
    remoteController = new AbortController();
    const version = ++remoteVersion;
    try {
      const response = await fetch(url.pathname + url.search, {signal: remoteController.signal, headers: {'X-Requested-With': 'fetch'}});
      if (!response.ok) throw new Error('Không tải được thông tin. Vui lòng thử lại.');
      const html = await response.text();
      if (version !== remoteVersion || !dialog.open) return;
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      const fragment = parsed.querySelector('[data-dialog-fragment]');
      if (!fragment) throw new Error('Phiên làm việc đã hết hạn hoặc thông tin không còn khả dụng.');
      content.replaceChildren(document.importNode(fragment, true));
      initializeTabs(content);
    } catch (error) {
      if (error.name === 'AbortError' || version !== remoteVersion || !dialog.open) return;
      const notice = createText('p', error.message, 'notice notice-error');
      const fullPage = createText('a', 'Mở trang chi tiết', 'button button-secondary');
      fullPage.href = link.href;
      content.replaceChildren(notice, fullPage);
    }
  };

  document.addEventListener('click', event => {
    const target = event.target.closest('button, a');
    if (target?.matches('[data-open-dialog]')) { event.preventDefault(); openDialog(target.dataset.openDialog, target); }
    else if (target?.matches('[data-close-dialog]')) { event.preventDefault(); closeDialog(target.closest('dialog')); }
    else if (target?.matches('[data-remote-dialog]') && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) {
      event.preventDefault(); loadRemote(target);
    } else if (target?.matches('[data-tab]')) {
      event.preventDefault(); activateTab(target.closest('[data-tabs]'), target.dataset.tab, true);
    } else if (target?.matches('[data-filter-value]')) {
      const scope = target.closest('[data-filter]');
      scope.querySelectorAll('[data-filter-value]').forEach(button => {
        const active = button === target;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', String(active));
      });
      refreshFilter(scope, true);
    } else if (target?.matches('[data-page]')) {
      const scope = target.closest('[data-filter]');
      const state = filterState.get(scope) || {page: 1};
      state.page += target.dataset.page === 'next' ? 1 : -1;
      filterState.set(scope, state); refreshFilter(scope);
    } else if (target?.matches('[data-password-toggle]')) {
      const input = document.getElementById(target.dataset.passwordToggle);
      if (input) {
        const showing = input.type === 'password';
        input.type = showing ? 'text' : 'password';
        target.setAttribute('aria-label', showing ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
        target.setAttribute('aria-pressed', String(showing));
      }
    } else if (target?.matches('[data-dismiss-notice]')) target.closest('.notice')?.remove();
    if (event.target.tagName === 'DIALOG') closeDialog(event.target);
  });
  document.addEventListener('keydown', event => {
    if (event.target.matches('[data-tab]') && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      const scope = event.target.closest('[data-tabs]');
      const buttons = owned(scope, '[data-tab]');
      let index = buttons.indexOf(event.target);
      index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
      event.preventDefault(); activateTab(scope, buttons[index].dataset.tab, true); buttons[index].focus();
    }
    const dialog = dialogStack.at(-1);
    if (!dialog) return;
    if (event.key === 'Escape') { event.preventDefault(); closeDialog(dialog); }
    if (event.key === 'Tab') {
      const focusable = [...dialog.querySelectorAll('button:not([disabled]),a[href],input:not([type="hidden"]):not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]')].filter(node => !node.closest('[hidden]'));
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  const confirmed = new WeakSet();
  const submitting = new Set();
  document.addEventListener('submit', event => {
    const form = event.target;
    if (form.method.toLowerCase() !== 'post') return;
    const message = event.submitter?.dataset.confirm || form.dataset.confirm;
    if (message && !confirmed.has(form)) {
      event.preventDefault();
      pendingConfirmation = {form, submitter: event.submitter};
      document.getElementById('confirm-message').textContent = message;
      openDialog('confirm-action', event.submitter);
      return;
    }
    confirmed.delete(form);
    if (submitting.has(form)) { event.preventDefault(); return; }
    submitting.add(form);
    form.setAttribute('aria-busy', 'true');
    if (event.submitter) event.submitter.classList.add('is-loading');
  });
  document.getElementById('confirm-submit')?.addEventListener('click', () => {
    const chosen = pendingConfirmation;
    closeDialog(document.getElementById('confirm-action'));
    if (chosen?.form.isConnected) { confirmed.add(chosen.form); chosen.form.requestSubmit(chosen.submitter || undefined); }
  });
  window.addEventListener('pageshow', () => {
    submitting.forEach(form => { form.removeAttribute('aria-busy'); form.querySelectorAll('.is-loading').forEach(button => button.classList.remove('is-loading')); });
    submitting.clear();
  });
  const requestedDialog = new URL(window.location.href).searchParams.get('open');
  if (requestedDialog && document.getElementById(requestedDialog)?.tagName === 'DIALOG') openDialog(requestedDialog);
  else {
    const auto = document.querySelector('dialog[data-auto-open]');
    if (auto) openDialog(auto.id);
  }
  const orderForm = document.querySelector('#sales-order-form');
  const output = document.querySelector('#forecast');
  const orderTotal = document.getElementById('order-total');
  const clearTotal = () => { if (orderTotal) orderTotal.textContent = '—'; };
  const markBomDirty = () => {
    const activate = document.querySelector('[data-activate-bom]');
    if (activate) activate.disabled = true;
    const hint = document.querySelector('[data-bom-save-hint]');
    if (hint) hint.textContent = 'Có thay đổi chưa lưu. Lưu bản nháp trước khi kích hoạt.';
  };
  document.querySelector('[data-bom-editor]')?.addEventListener('input', markBomDirty);
  document.querySelector('[data-bom-editor]')?.addEventListener('change', markBomDirty);
  let forecastController, forecastVersion = 0, forecastTimer;
  const renderForecast = async () => {
    if (!orderForm || !output) return;
    const version = ++forecastVersion;
    forecastController?.abort();
    forecastController = new AbortController();
    clearTotal();
    output.replaceChildren(createText('p', 'Đang kiểm tra vật tư…', 'loading-state'));
    try {
      const response = await fetch('/orders/check-stock', {
        method: 'POST', body: new FormData(orderForm), signal: forecastController.signal,
        headers: {'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content}
      });
      const result = await response.json();
      if (version !== forecastVersion) return;
      if (!response.ok || result.error) throw new Error(result.error || 'Không kiểm tra được vật tư.');
      if (orderTotal) orderTotal.textContent = new Intl.NumberFormat('vi-VN').format(result.items.reduce((sum, item) => sum + item.price * item.quantity, 0)) + ' ₫';
      const labels = {unknown: 'Chưa xác định vật tư', pending_material: 'Cần bổ sung vật tư', pending_approval: 'Đủ vật tư cho đơn hàng'};
      const nodes = [createText('p', labels[result.material_status], `material-badge ${result.material_status}`)];
      if (result.invalid_products.length) nodes.push(createText('p', `Cần hoàn thiện định mức: ${result.invalid_products.join(', ')}`, 'auth-hint'));
      result.requirements.forEach(part => {
        const row = createText('div', '', `forecast-result ${part.shortage > 0 ? 'material-red' : 'material-green'}`);
        row.append(createText('strong', `${part.sku} · ${part.name}`), createText('p', `Cần: ${part.required} ${part.unit} · Khả dụng: ${part.available} ${part.unit} · Thiếu: ${part.shortage} ${part.unit}`));
        nodes.push(row);
      });
      output.replaceChildren(...nodes);
    } catch (error) {
      if (error.name !== 'AbortError' && version === forecastVersion) output.replaceChildren(createText('p', `Chưa xác định: ${error.message}`, 'material-badge unknown'));
    }
  };
  const scheduleForecast = () => {
    ++forecastVersion;
    forecastController?.abort();
    clearTimeout(forecastTimer);
    clearTotal();
    output?.replaceChildren(createText('p', 'Đang kiểm tra vật tư…', 'material-badge unknown'));
    forecastTimer = setTimeout(renderForecast, 180);
  };
  const renumber = list => list.querySelectorAll('[data-repeat-row]').forEach((row, index) => {
    row.querySelector('[data-line-number]').textContent = `${list.dataset.repeatList === 'bom' ? 'Linh kiện' : 'Sản phẩm'} ${index + 1}`;
    row.querySelector('[data-remove-row]')?.setAttribute('aria-label', `Xóa dòng ${index + 1}`);
    row.querySelector('select')?.setAttribute('aria-label', `${list.dataset.repeatList === 'bom' ? 'Linh kiện' : 'Sản phẩm'} dòng ${index + 1}`);
    row.querySelector('input:not([type="hidden"])')?.setAttribute('aria-label', `${list.dataset.repeatList === 'bom' ? 'Định mức' : 'Số lượng'} dòng ${index + 1}`);
  });
  document.querySelectorAll('[data-add-row]').forEach(button => button.addEventListener('click', () => {
    const list = document.querySelector(`[data-repeat-list="${button.dataset.addRow}"]`);
    const source = list?.querySelector('[data-repeat-row]');
    if (!source) return;
    const row = source.cloneNode(true);
    row.querySelectorAll('input:not([type="hidden"])').forEach(input => { input.value = '1'; });
    list.appendChild(row);
    renumber(list);
    row.querySelector('select')?.focus();
    if (button.dataset.addRow === 'order') scheduleForecast();
    else markBomDirty();
  }));
  document.querySelectorAll('[data-repeat-list]').forEach(list => list.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-row]');
    if (button && list.querySelectorAll('[data-repeat-row]').length > 1) {
      const row = button.closest('[data-repeat-row]');
      const next = row.nextElementSibling || row.previousElementSibling;
      row.remove(); renumber(list); next?.querySelector('select')?.focus();
      if (list.dataset.repeatList === 'order') scheduleForecast();
      else markBomDirty();
    }
  }));
  if (orderForm) {
    orderForm.querySelector('[data-repeat-list="order"]').addEventListener('input', scheduleForecast);
    orderForm.querySelector('[data-repeat-list="order"]').addEventListener('change', scheduleForecast);
    renderForecast();
  }
});
