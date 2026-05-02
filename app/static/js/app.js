document.addEventListener("click", (event) => {
  if (!event.target.matches("[data-add-row]")) return;
  const table = document.querySelector("#items-table tbody");
  if (!table || !table.rows.length) return;
  const clone = table.rows[0].cloneNode(true);
  clone.querySelectorAll("input").forEach((input) => {
    input.value = input.name === "quantity" ? "1" : "";
  });
  table.appendChild(clone);
});

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

window.addEventListener("load", initDashboardCharts);
window.addEventListener("resize", () => {
  window.clearTimeout(window.__chartResize);
  window.__chartResize = window.setTimeout(initDashboardCharts, 120);
});
