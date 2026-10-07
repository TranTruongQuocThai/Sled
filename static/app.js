document.addEventListener('DOMContentLoaded', () => {
  const menuButton = document.querySelector('.mobile-menu');
  const closeMenu = () => {
    document.body.classList.remove('nav-open');
    if (menuButton) menuButton.setAttribute('aria-expanded', 'false');
  };
  if (menuButton) menuButton.addEventListener('click', () => {
    const isOpen = document.body.classList.toggle('nav-open');
    menuButton.setAttribute('aria-expanded', String(isOpen));
  });
  document.querySelectorAll('[data-nav-close], #main-nav a').forEach(item => item.addEventListener('click', closeMenu));
  window.addEventListener('resize', () => { if (window.innerWidth > 760) closeMenu(); });

  const qty = document.querySelector('#quantity');
  const product = document.querySelector('#product');
  const output = document.querySelector('#forecast');
  if (!qty || !product || !output) return;
  const renderForecast = async () => {
    const response = await fetch(`/inventory/forecast?quantity=${encodeURIComponent(qty.value || 1)}&product_id=${product.value}`);
    const parts = await response.json();
    output.innerHTML = parts.map(part => `<div class="forecast-row"><div><b>${part.name}</b><small>${part.sku} · ${part.per_product}/sản phẩm</small></div><span>${part.required} ${part.unit}<small>Cần dùng</small></span><span>${part.available} ${part.unit}<small>Khả dụng</small></span><span class="${part.shortage ? 'shortage' : 'ok'}">${part.remaining} ${part.unit}<small>${part.shortage ? 'Thiếu hàng' : 'Sau đơn'}</small></span></div>`).join('');
  };
  qty.addEventListener('input', renderForecast);
  product.addEventListener('change', renderForecast);
  renderForecast();
});
