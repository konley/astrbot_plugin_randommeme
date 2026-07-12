const bridge = window.AstrBotPluginPage;

const state = {
  groups: [],
  currentGroup: null,
  images: [],
  selected: new Set(),
  dialogMode: null,
  editing: null,
  submitting: false,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const PLUGIN_NAME = "astrbot_plugin_randommeme";
const SUPPORTED_EXTS = ["jpg", "jpeg", "png", "webp", "bmp", "gif"];

async function init() {
  const ctx = await bridge.ready();
  document.title = bridge.t("pages.manager.title", "随机表情包 · 管理");
  void ctx;
  bindTabs();
  bindGroupEvents();
  bindImageEvents();
  await refreshGroups();
  await refreshStats();
  bridge.onContext(() => {
    /* theme switch handled by bridge SDK <html data-theme="..."> */
  });
}

function bindTabs() {
  $$(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      $$(".tab").forEach((b) =>
        b.setAttribute("aria-selected", b === btn ? "true" : "false")
      );
      $$(".panel").forEach((p) => {
        p.hidden = p.dataset.panel !== target;
      });
      if (target === "stats") refreshStats();
    });
  });
}

function bindGroupEvents() {
  $("#btn-refresh-groups").addEventListener("click", () => {
    refreshGroups();
    refreshStats();
  });

  $("#btn-new-group").addEventListener("click", () => openGroupDialog());
  $("#btn-reset-all").addEventListener("click", onResetAll);

  $("#btn-group-cancel").addEventListener("click", closeGroupDialog);
  $("#group-dialog").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeGroupDialog();
  });
  $("#group-form").addEventListener("submit", onGroupSubmit);
}

function bindImageEvents() {
  $("#image-group-select").addEventListener("change", (e) => {
    state.currentGroup = e.target.value;
    state.selected.clear();
    loadImages();
  });

  const uploadRow = $(".upload-row");
  const fileInput = $("#image-input");

  fileInput.addEventListener("change", () => {
    if (fileInput.files?.length) {
      handleUploadFiles(Array.from(fileInput.files));
      fileInput.value = "";
    }
  });

  ["dragenter", "dragover"].forEach((ev) =>
    uploadRow.addEventListener(ev, (e) => {
      e.preventDefault();
      uploadRow.classList.add("dragging");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    uploadRow.addEventListener(ev, (e) => {
      e.preventDefault();
      uploadRow.classList.remove("dragging");
    })
  );
  uploadRow.addEventListener("drop", (e) => {
    const files = Array.from(e.dataTransfer?.files || []);
    if (files.length) handleUploadFiles(files);
  });

  $("#btn-batch-delete").addEventListener("click", onBatchDelete);
  $("#btn-reset-group-history").addEventListener("click", onResetGroupHistory);
}

async function refreshGroups() {
  try {
    const result = await bridge.apiGet("groups");
    state.groups = result.groups || [];
    renderGroups();
    renderGroupSelect();
    renderSettings();
  } catch (err) {
    showToast(`加载组别失败: ${err.message}`, "error");
  }
}

async function refreshStats() {
  try {
    const stats = await bridge.apiGet("stats");
    renderStats(stats);
  } catch (err) {
    showToast(`加载统计失败: ${err.message}`, "error");
  }
}

function renderGroups() {
  const tbody = $("#groups-table tbody");
  const empty = $("#groups-empty");
  tbody.innerHTML = "";
  if (state.groups.length === 0) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  for (const g of state.groups) {
    const tr = document.createElement("tr");
    tr.appendChild(td(g.name, "name"));
    tr.appendChild(td((g.aliases || []).join(" / ") || "-"));
    tr.appendChild(td(`${g.image_count}`));
    tr.appendChild(makeStatusPillCell(g.enabled));
    tr.appendChild(makeStatusPillCell(g.require_wake, "wake", "需唤醒", "无需唤醒"));
    tr.appendChild(makeActionCell(g));
    tbody.appendChild(tr);
  }
}

function td(text, cls) {
  const cell = document.createElement("td");
  cell.textContent = text ?? "";
  if (cls) cell.className = cls;
  return cell;
}

function makeStatusPillCell(value, kind, onText, offText) {
  const cell = document.createElement("td");
  const pill = document.createElement("span");
  pill.className = "status-pill " + (value ? "on" : "off");
  pill.textContent = value ? onText || "启用" : offText || "禁用";
  cell.appendChild(pill);
  return cell;
}

function makeActionCell(g) {
  const cell = document.createElement("td");
  cell.style.whiteSpace = "nowrap";

  const editBtn = document.createElement("button");
  editBtn.className = "btn";
  editBtn.textContent = "编辑";
  editBtn.style.marginRight = "6px";
  editBtn.addEventListener("click", () => openGroupDialog(g));

  const delBtn = document.createElement("button");
  delBtn.className = "btn danger";
  delBtn.textContent = "删除";
  delBtn.addEventListener("click", () => onDeleteGroup(g));

  cell.append(editBtn, delBtn);
  return cell;
}

function renderGroupSelect() {
  const select = $("#image-group-select");
  select.innerHTML = "";
  for (const g of state.groups) {
    const opt = document.createElement("option");
    opt.value = g.name;
    opt.textContent = `${g.name} (${g.image_count})`;
    select.appendChild(opt);
  }
  state.currentGroup = select.value || null;
  if (state.currentGroup) loadImages();
}

function renderSettings() {
  const list = $("#settings-list");
  list.innerHTML = "";
  const rows = [
    ["已注册组别", `${state.groups.length}`],
    [
      "插件名（用于 bridge API 前缀）",
      PLUGIN_NAME,
    ],
    [
      "支持的图片格式",
      SUPPORTED_EXTS.map((e) => `.${e}`).join(" / "),
    ],
    [
      "抽取规则",
      "随机 + 不重复；跑完一轮自动重置（全局共享抽取池）",
    ],
  ];
  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    list.append(dt, dd);
  }
}

function renderStats(stats) {
  const list = $("#stats-list");
  list.innerHTML = "";
  const top = [
    ["组别数", `${stats.group_count}`],
    ["图片总数", `${stats.image_total}`],
    ["本轮累计抽取", `${stats.history_size}`],
  ];
  for (const [k, v] of top) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    list.append(dt, dd);
  }
  const tbody = $("#stats-table tbody");
  tbody.innerHTML = "";
  for (const g of stats.groups) {
    const remain = Math.max(0, g.image_count - g.drew);
    const tr = document.createElement("tr");
    tr.appendChild(td(g.name));
    tr.appendChild(td(`${g.image_count}`));
    tr.appendChild(td(`${g.drew}`));
    tr.appendChild(td(`${remain}`));
    tbody.appendChild(tr);
  }
}

async function loadImages() {
  if (!state.currentGroup) {
    state.images = [];
    renderImages();
    return;
  }
  try {
    const result = await bridge.apiGet(`groups/${encodeURIComponent(state.currentGroup)}/images`);
    state.images = result.images || [];
  } catch (err) {
    showToast(`加载图片失败: ${err.message}`, "error");
    state.images = [];
  }
  renderImages();
}

function renderImages() {
  const grid = $("#images-grid");
  const empty = $("#images-empty");
  const meta = $("#images-meta");
  grid.innerHTML = "";
  if (!state.currentGroup) {
    empty.hidden = false;
    empty.textContent = "请先选择一个组别。";
    meta.textContent = "";
    $("#btn-batch-delete").disabled = true;
    $("#btn-reset-group-history").disabled = true;
    return;
  }
  empty.hidden = state.images.length > 0;
  empty.textContent = "该组别下还没有图片，去上传几张吧。";
  meta.textContent = `共 ${state.images.length} 张`;
  $("#btn-batch-delete").disabled = state.selected.size === 0;
  $("#btn-reset-group-history").disabled = false;

  for (const filename of state.images) {
    grid.appendChild(makeImageCard(state.currentGroup, filename));
  }
}

function makeImageCard(group, filename) {
  const card = document.createElement("div");
  card.className = "image-card";

  const toggle = document.createElement("button");
  toggle.className = "select-toggle";
  toggle.textContent = "✓";
  toggle.title = "选中";
  toggle.addEventListener("click", (e) => {
    e.stopPropagation();
    if (state.selected.has(filename)) {
      state.selected.delete(filename);
      card.classList.remove("selected");
    } else {
      state.selected.add(filename);
      card.classList.add("selected");
    }
    $("#btn-batch-delete").disabled = state.selected.size === 0;
  });
  card.appendChild(toggle);

  const img = document.createElement("img");
  img.alt = filename;
  img.loading = "lazy";
  const url = buildImageUrl(group, filename);
  img.src = url;
  img.addEventListener("error", () => {
    img.replaceWith(makeTextPreview(filename));
  });
  card.appendChild(img);

  const meta = document.createElement("div");
  meta.className = "image-meta";
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = filename;
  name.title = filename;
  const del = document.createElement("button");
  del.textContent = "删除";
  del.addEventListener("click", (e) => {
    e.stopPropagation();
    onDeleteImage(group, filename);
  });
  meta.append(name, del);
  card.appendChild(meta);
  return card;
}

function buildImageUrl(group, filename) {
  return `/api/plug/${PLUGIN_NAME}/groups/${encodeURIComponent(group)}/images/${encodeURIComponent(filename)}`;
}

function makeTextPreview(text) {
  const div = document.createElement("div");
  div.style.padding = "32px 8px";
  div.style.fontSize = "12px";
  div.style.color = "var(--text-muted)";
  div.style.textAlign = "center";
  div.style.wordBreak = "break-all";
  div.textContent = text;
  return div;
}

async function handleUploadFiles(files) {
  if (!state.currentGroup) {
    showToast("请先选择一个组别", "error");
    return;
  }
  let uploaded = 0;
  for (const file of files) {
    try {
      await bridge.upload(
        `groups/${encodeURIComponent(state.currentGroup)}/images`,
        file
      );
      uploaded += 1;
    } catch (err) {
      showToast(`上传 ${file.name} 失败: ${err.message}`, "error");
    }
  }
  if (uploaded > 0) showToast(`成功上传 ${uploaded} 张`, "success");
  await loadImages();
  await refreshGroups();
  refreshStats();
}

async function onDeleteImage(group, filename) {
  if (!confirm(`确定删除 "${filename}" 吗？`)) return;
  try {
    await bridge.apiPost(`groups/${encodeURIComponent(group)}/images/delete`, {
      filenames: [filename],
    });
    showToast("已删除", "success");
    state.selected.delete(filename);
    await loadImages();
    await refreshGroups();
    refreshStats();
  } catch (err) {
    showToast(`删除失败: ${err.message}`, "error");
  }
}

async function onBatchDelete() {
  if (state.selected.size === 0) return;
  const filenames = Array.from(state.selected);
  if (!confirm(`确定要批量删除 ${filenames.length} 张图片吗？`)) return;
  try {
    const result = await bridge.apiPost(
      `groups/${encodeURIComponent(state.currentGroup)}/images/delete`,
      { filenames }
    );
    showToast(`已删除 ${result.removed.length} 张`, "success");
    state.selected.clear();
    await loadImages();
    await refreshGroups();
    refreshStats();
  } catch (err) {
    showToast(`批量删除失败: ${err.message}`, "error");
  }
}

async function onResetGroupHistory() {
  if (!state.currentGroup) return;
  if (!confirm(`重置组别 "${state.currentGroup}" 的抽取序列？`)) return;
  try {
    await bridge.apiPost(`groups/${encodeURIComponent(state.currentGroup)}/reset`);
    showToast("抽取序列已重置", "success");
    refreshStats();
  } catch (err) {
    showToast(`重置失败: ${err.message}`, "error");
  }
}

async function onResetAll() {
  if (!confirm("重置所有组别的抽取序列？（不会删除任何图片）")) return;
  try {
    const result = await bridge.apiPost("reset");
    showToast(`已重置 ${result.groups_cleared} 个组别`, "success");
    refreshStats();
  } catch (err) {
    showToast(`重置失败: ${err.message}`, "error");
  }
}

async function onDeleteGroup(g) {
  if (!confirm(`删除组别 "${g.name}"？该组别下所有图片也会被删除，此操作不可恢复。`))
    return;
  try {
    await bridge.apiPost(`groups/${encodeURIComponent(g.name)}/delete`);
    showToast("组别已删除", "success");
    if (state.currentGroup === g.name) {
      state.currentGroup = null;
    }
    state.selected.clear();
    await refreshGroups();
    refreshStats();
  } catch (err) {
    showToast(`删除失败: ${err.message}`, "error");
  }
}

function openGroupDialog(group = null) {
  state.dialogMode = group ? "edit" : "create";
  state.editing = group;
  $("#group-dialog-title").textContent = group ? `编辑组别: ${group.name}` : "新建组别";
  $("#field-name").value = group?.name || "";
  $("#field-name").disabled = !!group;
  $("#field-aliases").value = (group?.aliases || []).join("\n");
  $("#field-require-wake").checked = !!group?.require_wake;
  $("#field-enabled").checked = group ? !!group.enabled : true;
  $("#field-enabled-row").hidden = !group;
  $("#group-dialog").hidden = false;
}

function closeGroupDialog() {
  $("#group-dialog").hidden = true;
  state.editing = null;
}

async function onGroupSubmit(e) {
  e.preventDefault();
  if (state.submitting) return;
  const name = $("#field-name").value.trim();
  const aliases = $("#field-aliases").value
    .split(/[\n,;]/)
    .map((s) => s.trim())
    .filter(Boolean);
  const require_wake = $("#field-require-wake").checked;
  const enabled = $("#field-enabled").checked;

  const isCreate = !state.editing;
  const btn = $("#group-form button[type=submit]");
  state.submitting = true;
  btn.disabled = true;
  try {
    if (isCreate) {
      if (!name) { showToast("请输入组别名称", "error"); return; }
      await bridge.apiPost("groups", { name, aliases, require_wake });
      showToast(`已创建: ${name}`, "success");
    } else {
      await bridge.apiPost(`groups/${encodeURIComponent(state.editing.name)}/update`, {
        aliases, require_wake, enabled,
      });
      showToast(`已更新: ${state.editing.name}`, "success");
    }
    closeGroupDialog();
    await refreshGroups();
    refreshStats();
  } catch (err) {
    showToast(`保存失败: ${err.message}`, "error");
  } finally {
    state.submitting = false;
    btn.disabled = false;
  }
}

let toastTimer = null;
function showToast(msg, kind) {
  const toast = $("#toast");
  toast.textContent = msg;
  toast.className = "toast" + (kind ? ` ${kind}` : "");
  toast.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 3200);
}

init().catch((err) => {
  console.error(err);
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<pre style="color:red;padding:12px;">初始化失败: ${err.message}</pre>`
  );
});
