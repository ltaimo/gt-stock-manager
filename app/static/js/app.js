document.addEventListener("click", (event) => {
  if (event.target.matches("[data-add-row]")) {
    const table = document.querySelector(event.target.dataset.table || "#items-table tbody");
    if (!table || !table.rows.length) return;
    const clone = table.rows[0].cloneNode(true);
    clone.querySelectorAll("input").forEach((input) => {
      input.value = input.name === "quantity" ? "1" : "";
    });
    table.appendChild(clone);
    if (clone.matches("[data-requisition-item]")) {
      initRequisitionItemRow(clone);
      updateRequisitionProductAvailability();
    }
    if (clone.matches("[data-movement-item]")) {
      window.initMovementItemRow?.(clone);
      window.validateMovementTotals?.();
    }
    return;
  }

  if (event.target.matches("[data-remove-row]")) {
    const row = event.target.closest("[data-requisition-item], [data-movement-item]");
    if (!row) return;
    const selector = row.matches("[data-movement-item]") ? "[data-movement-item]" : "[data-requisition-item]";
    const rows = document.querySelectorAll(selector);
    if (row && rows.length > 1) row.remove();
    if (selector === "[data-movement-item]") {
      window.validateMovementTotals?.();
    } else {
      validateRequisitionTotals();
    }
  }
});

function uiMessage(key) {
  return document.body?.dataset[key] || "";
}

function initNavigation() {
  const body = document.body;
  const openButton = document.querySelector("[data-menu-open]");
  const closeButtons = document.querySelectorAll("[data-menu-close]");
  const sidebar = document.getElementById("app-sidebar");
  if (!openButton || !sidebar) return;

  const setOpen = (open) => {
    body.classList.toggle("menu-open", open);
    openButton.setAttribute("aria-expanded", String(open));
  };
  openButton.addEventListener("click", () => setOpen(true));
  closeButtons.forEach((button) => button.addEventListener("click", () => setOpen(false)));
  sidebar.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => setOpen(false)));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });

  const path = window.location.pathname;
  let bestMatch = null;
  sidebar.querySelectorAll("nav a").forEach((link) => {
    const exact = link.dataset.navExact;
    const prefix = link.dataset.navPrefix;
    const matches = exact ? path === exact : prefix && (path === prefix || path.startsWith(`${prefix}/`));
    if (matches && (!bestMatch || (exact || prefix.length > bestMatch.length))) {
      bestMatch = { link, length: exact ? 1000 : prefix.length };
    }
  });
  if (bestMatch) {
    bestMatch.link.classList.add("active");
    bestMatch.link.setAttribute("aria-current", "page");
  }
}

function initResponsiveTables() {
  document.querySelectorAll("table").forEach((table) => {
    const headers = Array.from(table.querySelectorAll("thead th")).map((header) => header.textContent.trim());
    if (!headers.length) return;
    table.classList.add("responsive-table");
    table.querySelectorAll("tbody tr").forEach((row) => {
      Array.from(row.children).forEach((cell, index) => {
        if (cell.tagName === "TD" && !cell.hasAttribute("colspan")) {
          cell.dataset.label = headers[index] || "";
        }
      });
    });
  });
}

function initLanguageForm() {
  document.querySelectorAll(".language-form select[name='language']").forEach((select) => {
    select.addEventListener("change", () => {
      if (!select.form) return;
      if (typeof select.form.requestSubmit === "function") {
        select.form.requestSubmit();
      } else {
        select.form.submit();
      }
    });
  });
}

document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});

function isStockRequisition() {
  const type = document.getElementById("requisition-type");
  return type && type.value.toUpperCase().includes("REQUISI");
}

function selectedProductData(row) {
  const select = row.querySelector("select[name='product_id']");
  const option = select ? select.options[select.selectedIndex] : null;
  return {
    select,
    stock: Number(option?.dataset.stock || 0),
    unit: option?.dataset.unit || "",
    price: Number(option?.dataset.price || 0),
    productId: option?.value || "",
  };
}

function updateRequisitionItemRow(row) {
  const { stock, unit } = selectedProductData(row);
  const quantity = row.querySelector("input[name='quantity']");
  const hint = row.querySelector(".stock-hint");
  if (!quantity) return;

  quantity.max = isStockRequisition() ? String(stock) : "";
  if (isStockRequisition() && Number(quantity.value || 0) > stock) quantity.value = String(stock);
  if (hint) hint.textContent = isStockRequisition() ? `${uiMessage("i18nMaxAvailable")}: ${stock} ${unit}` : "";
}

function validateRequisitionTotals() {
  const rows = document.querySelectorAll("[data-requisition-item]");
  const totals = new Map();
  rows.forEach((row) => {
    const { productId, stock } = selectedProductData(row);
    const quantity = row.querySelector("input[name='quantity']");
    if (!quantity) return;
    quantity.setCustomValidity("");
    const current = totals.get(productId) || { total: 0, stock, quantity };
    current.total += Number(quantity.value || 0);
    totals.set(productId, current);
  });

  if (!isStockRequisition()) return true;
  let valid = true;
  totals.forEach(({ total, stock, quantity }) => {
    if (stock <= 0) {
      quantity.setCustomValidity(uiMessage("i18nNoStock"));
      valid = false;
    } else if (total > stock) {
      quantity.setCustomValidity(uiMessage("i18nExceedsStock").replace("{stock}", stock));
      valid = false;
    }
  });
  return valid;
}

function initRequisitionItemRow(row) {
  const select = row.querySelector("select[name='product_id']");
  const quantity = row.querySelector("input[name='quantity']");
  if (select) select.addEventListener("change", () => {
    updateRequisitionItemRow(row);
    validateRequisitionTotals();
  });
  if (quantity) quantity.addEventListener("input", validateRequisitionTotals);
  updateRequisitionItemRow(row);
}

function updateRequisitionProductAvailability() {
  const stockRequest = isStockRequisition();
  document.querySelectorAll("select[name='product_id']").forEach((select) => {
    Array.from(select.options).forEach((option) => {
      option.disabled = stockRequest && Number(option.dataset.stock || 0) <= 0;
    });
    if (select.selectedOptions[0]?.disabled) {
      const available = Array.from(select.options).find((option) => !option.disabled);
      if (available) select.value = available.value;
    }
    const row = select.closest("[data-requisition-item]");
    if (row) updateRequisitionItemRow(row);
  });
  validateRequisitionTotals();
}

function initRequisitionForm() {
  const type = document.getElementById("requisition-type");
  if (!type) return;
  document.querySelectorAll("[data-requisition-item]").forEach(initRequisitionItemRow);
  type.addEventListener("change", updateRequisitionProductAvailability);
  type.closest("form")?.addEventListener("submit", (event) => {
    if (!validateRequisitionTotals()) event.preventDefault();
  });
  updateRequisitionProductAvailability();
}

function updateRequisitionReviewRow(row) {
  const requested = Number(row.dataset.requested || 0);
  const approvedInput = row.querySelector(".approved-quantity");
  const rejectedOutput = row.querySelector(".rejected-quantity");
  const observation = row.querySelector(".review-observation");
  if (!approvedInput || !rejectedOutput || !observation) return;

  const approved = Math.min(requested, Math.max(0, Number(approvedInput.value || 0)));
  const rejected = Math.max(0, requested - approved);
  rejectedOutput.textContent = rejected.toFixed(2).replace(/\.00$/, "");
  observation.required = rejected > 0;
}

function initRequisitionReview() {
  document.querySelectorAll("[data-review-row]").forEach((row) => {
    updateRequisitionReviewRow(row);
    const input = row.querySelector(".approved-quantity");
    if (input) input.addEventListener("input", () => updateRequisitionReviewRow(row));
  });
}

function initMovementForm() {
  const actionGroup = document.getElementById("movement-action");
  if (!actionGroup) return;

  const isExit = () => {
    const action = (actionGroup.querySelector("input[name='action_type']:checked")?.value || "ENTRADA").toUpperCase();
    return action === "SAÍDA" || action === "SAIDA" || action === "SAÃDA";
  };

  const selectedMovementProductData = (row) => {
    const select = row.querySelector("select[name='product_id']");
    const option = select ? select.options[select.selectedIndex] : null;
    return {
      stock: Number(option?.dataset.stock || 0),
      unit: option?.dataset.unit || "",
      productId: option?.value || "",
    };
  };

  window.initMovementItemRow = (row) => {
    const select = row.querySelector("select[name='product_id']");
    const quantity = row.querySelector("input[name='quantity']");
    const hint = row.querySelector(".stock-hint");
    const updateRow = () => {
      const { stock, unit } = selectedMovementProductData(row);
      if (hint) hint.textContent = `${stock} ${unit}`;
      if (quantity) quantity.max = isExit() ? String(stock) : "";
      validateMovementTotals();
    };
    if (select) select.addEventListener("change", updateRow);
    if (quantity) quantity.addEventListener("input", validateMovementTotals);
    updateRow();
  };

  window.validateMovementTotals = () => {
    const rows = document.querySelectorAll("[data-movement-item]");
    const totals = new Map();
    rows.forEach((row) => {
      const { productId, stock } = selectedMovementProductData(row);
      const quantity = row.querySelector("input[name='quantity']");
      if (!quantity) return;
      quantity.setCustomValidity("");
      const current = totals.get(productId) || { total: 0, stock, quantity };
      current.total += Number(quantity.value || 0);
      totals.set(productId, current);
    });
    if (!isExit()) return true;
    let valid = true;
    totals.forEach(({ total, stock, quantity }) => {
      if (total > stock) {
        quantity.setCustomValidity(uiMessage("i18nExceedsStock").replace("{stock}", stock));
        valid = false;
      }
    });
    return valid;
  };

  const updateFields = () => {
    const action = actionGroup.querySelector("input[name='action_type']:checked")?.value || "ENTRADA";
    const isEntry = action === "ENTRADA";
    document.querySelectorAll("[data-movement-entry]").forEach((element) => {
      element.hidden = !isEntry;
      element.querySelectorAll("input, select").forEach((field) => {
        field.required = isEntry;
      });
    });
    document.querySelectorAll("[data-movement-exit]").forEach((element) => {
      element.hidden = isEntry;
      element.querySelectorAll("select[name='department_id']").forEach((field) => {
        field.required = !isEntry;
      });
      element.querySelectorAll("input[name='responsible_person']").forEach((field) => {
        field.required = action === "SAÍDA";
      });
    });
    document.querySelectorAll("[data-movement-item]").forEach(window.initMovementItemRow);
    window.validateMovementTotals();
  };

  actionGroup.querySelectorAll("input[name='action_type']").forEach((input) => {
    input.addEventListener("change", updateFields);
  });
  actionGroup.closest("form")?.addEventListener("submit", (event) => {
    if (!window.validateMovementTotals()) event.preventDefault();
  });
  updateFields();
}

function initReplenishmentForm() {
  const form = document.querySelector("[data-replenishment-form]");
  if (!form) return;
  const rows = Array.from(form.querySelectorAll("[data-replenishment-row]"));
  const totalOutput = form.querySelector("[data-replenishment-total]");
  const search = form.querySelector("[data-replenishment-search]");

  const update = () => {
    let total = 0;
    let selectedCount = 0;
    rows.forEach((row) => {
      const checkbox = row.querySelector("[data-replenishment-check]");
      const quantity = row.querySelector("[data-replenishment-quantity]");
      const price = row.querySelector("[data-replenishment-price]");
      const lineOutput = row.querySelector("[data-replenishment-line-total]");
      const selected = Boolean(checkbox?.checked);
      if (quantity) {
        quantity.disabled = !selected;
        quantity.required = selected;
      }
      if (price) {
        price.disabled = !selected;
        price.required = selected;
      }
      row.classList.toggle("is-selected", selected);
      const lineTotal = selected ? Number(quantity?.value || 0) * Number(price?.value || 0) : 0;
      if (lineOutput) lineOutput.textContent = lineTotal.toFixed(2);
      total += lineTotal;
      if (selected) selectedCount += 1;
    });
    if (totalOutput) totalOutput.textContent = total.toFixed(2);
    const firstCheckbox = rows[0]?.querySelector("[data-replenishment-check]");
    if (firstCheckbox) {
      firstCheckbox.setCustomValidity(selectedCount ? "" : uiMessage("i18nSelectReplenishment"));
    }
  };

  rows.forEach((row) => {
    row.querySelectorAll("input").forEach((input) => input.addEventListener("input", update));
    row.addEventListener("click", (event) => {
      if (event.target.closest("input, label, a, button")) return;
      const checkbox = row.querySelector("[data-replenishment-check]");
      if (checkbox) {
        checkbox.checked = !checkbox.checked;
        update();
      }
    });
  });
  search?.addEventListener("input", () => {
    const query = search.value.trim().toLocaleLowerCase(document.documentElement.lang || "pt");
    rows.forEach((row) => {
      row.hidden = Boolean(query) && !row.dataset.searchText.toLocaleLowerCase(document.documentElement.lang || "pt").includes(query);
    });
  });
  form.addEventListener("submit", update);
  update();
}

function drawBarLineChart(canvas, labels, bars, line) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = rect.width * ratio;
  canvas.height = rect.height * ratio;
  ctx.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  const pad = { top: 18, right: 18, bottom: 26, left: 38 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...bars, ...line);
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#e3e6ea";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (plotH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }
  const step = plotW / labels.length;
  bars.forEach((value, index) => {
    const h = (value / max) * plotH;
    const x = pad.left + index * step + step * 0.18;
    const y = pad.top + plotH - h;
    ctx.fillStyle = "#d6a619";
    ctx.fillRect(x, y, Math.max(3, step * 0.45), h);
  });
  ctx.beginPath();
  line.forEach((value, index) => {
    const x = pad.left + index * step + step * 0.4;
    const y = pad.top + plotH - (value / max) * plotH;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = "#c53333";
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = "#747981";
  ctx.font = "11px Segoe UI, Arial";
  labels.forEach((label, index) => {
    if (index % 5 === 0 || index === labels.length - 1) {
      ctx.fillText(label, pad.left + index * step, height - 8);
    }
  });
}

function drawDonutChart(canvas, labels, values) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = rect.width * ratio;
  canvas.height = rect.height * ratio;
  ctx.scale(ratio, ratio);
  const total = values.reduce((sum, value) => sum + value, 0) || 1;
  const colors = ["#d6a619", "#6b7280", "#18794e", "#c53333", "#b86b00", "#3d6fb6", "#8a9098", "#50545a"];
  const cx = rect.width * 0.33;
  const cy = rect.height * 0.48;
  const r = Math.min(rect.width, rect.height) * 0.28;
  let start = -Math.PI / 2;
  ctx.clearRect(0, 0, rect.width, rect.height);
  values.forEach((value, index) => {
    const angle = (value / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, start, start + angle);
    ctx.closePath();
    ctx.fillStyle = colors[index % colors.length];
    ctx.fill();
    start += angle;
  });
  ctx.beginPath();
  ctx.arc(cx, cy, r * 0.58, 0, Math.PI * 2);
  ctx.fillStyle = "#fff";
  ctx.fill();
  ctx.fillStyle = "#2d3033";
  ctx.font = "700 16px Segoe UI, Arial";
  ctx.textAlign = "center";
  ctx.fillText(String(total), cx, cy + 5);
  ctx.textAlign = "left";
  ctx.font = "12px Segoe UI, Arial";
  labels.slice(0, 8).forEach((label, index) => {
    const y = 22 + index * 20;
    ctx.fillStyle = colors[index % colors.length];
    ctx.fillRect(rect.width * 0.62, y - 10, 10, 10);
    ctx.fillStyle = "#2d3033";
    ctx.fillText(`${label}: ${values[index]}`, rect.width * 0.62 + 16, y);
  });
}

function initDashboardCharts() {
  const dataEl = document.getElementById("dashboard-data");
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  drawBarLineChart(
    document.getElementById("monthlyFlowChart"),
    data.month.labels,
    data.month.entries,
    data.month.exits
  );
  drawDonutChart(document.getElementById("movementTypeChart"), data.movementTypes.labels, data.movementTypes.values);
  drawDonutChart(document.getElementById("unitChart"), data.units.labels, data.units.values);
}

window.addEventListener("load", () => {
  initNavigation();
  initResponsiveTables();
  initLanguageForm();
  initDashboardCharts();
  initRequisitionForm();
  initRequisitionReview();
  initMovementForm();
  initReplenishmentForm();
});
window.addEventListener("resize", () => {
  window.clearTimeout(window.__chartResize);
  window.__chartResize = window.setTimeout(initDashboardCharts, 120);
});

function updateRequisitionItemRow(row) {
  const { stock, unit, price } = selectedProductData(row);
  const quantity = row.querySelector("input[name='quantity']");
  const hint = row.querySelector(".stock-hint");
  const priceEl = row.querySelector(".unit-price");
  const totalEl = row.querySelector(".line-total");
  if (!quantity) return;

  quantity.max = isStockRequisition() ? String(stock) : "";
  if (isStockRequisition() && Number(quantity.value || 0) > stock) quantity.value = String(stock);
  if (hint) hint.textContent = isStockRequisition() ? `${uiMessage("i18nMaxAvailable")}: ${stock} ${unit}` : "";
  if (priceEl) priceEl.textContent = price.toFixed(2);
  if (totalEl) totalEl.textContent = (price * Number(quantity.value || 0)).toFixed(2);
}

function validateRequisitionTotals() {
  const rows = document.querySelectorAll("[data-requisition-item]");
  const totals = new Map();
  let requestValue = 0;
  rows.forEach((row) => {
    const { productId, stock, price } = selectedProductData(row);
    const quantity = row.querySelector("input[name='quantity']");
    if (!quantity) return;
    quantity.setCustomValidity("");
    const current = totals.get(productId) || { total: 0, stock, quantity };
    const qty = Number(quantity.value || 0);
    current.total += qty;
    requestValue += qty * price;
    totals.set(productId, current);
    updateRequisitionItemRow(row);
  });

  const totalEl = document.getElementById("requisition-total");
  if (totalEl) totalEl.textContent = requestValue.toFixed(2);

  if (!isStockRequisition()) return true;
  let valid = true;
  totals.forEach(({ total, stock, quantity }) => {
    if (stock <= 0) {
      quantity.setCustomValidity(uiMessage("i18nNoStock"));
      valid = false;
    } else if (total > stock) {
      quantity.setCustomValidity(uiMessage("i18nExceedsStock").replace("{stock}", stock));
      valid = false;
    }
  });
  return valid;
}
