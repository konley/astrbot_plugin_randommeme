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

function unwrap(payload) {
  if (payload && typeof payload === "object" && "data" in payload) {
    return payload.data;
  }
  return payload;
}

/* ------------------------------------------------------------------ confirm */

function showConfirm(title, message) {
  return new Promise((resolve) => {
    $("#confirm-title").textContent = title;
    $("#confirm-message").textContent = message;
    $("#confirm-dialog").hidden = false;

    function cleanup(result) {
      $("#confirm-dialog").hidden = true;
      $("#btn-confirm-ok").removeEventListener("click", onOk);
      $("#btn-confirm-cancel").removeEventListener("click", onCancel);
      resolve(result);
    }
    function onOk() { cleanup(true); }
    function onCancel() { cleanup(false); }

    $("#btn-confirm-ok").addEventListener("click", onOk);
    $("#btn-confirm-cancel").addEventListener("click", onCancel);
    $("#confirm-dialog").addEventListener("click", (e) => {
      if (e.target === e.currentTarget) cleanup(false);
    });
  });
}

/* ------------------------------------------------------------------ init */

async function init() {
  const ctx = await bridge.ready();
  document.title = bridge.t("pages.manager.title", "闅忔満琛ㄦ儏鍖?路 绠＄悊");
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
    // 绔嬪嵆娓呯┖缃戞牸鏄剧ず鍔犺浇鐘舵€?
    $("#images-grid").innerHTML = "";
    $("#images-empty").hidden = false;
    $("#images-empty").textContent = "鍔犺浇涓€?;
    $("#images-meta").textContent = "";
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

/* ------------------------------------------------------------------ data */

async function refreshGroups() {
  try {
    const result = unwrap(await bridge.apiGet("groups"));
    state.groups = result.groups || [];
    renderGroups();
    renderGroupSelect();
    renderSettings();
  } catch (err) {
    showToast(`鍔犺浇缁勫埆澶辫触: ${err.message}`, "error");
  }
}

async function refreshStats() {
  try {
    const stats = unwrap(await bridge.apiGet("stats"));
    renderStats(stats);
  } catch (err) {
    showToast(`鍔犺浇缁熻澶辫触: ${err.message}`, "error");
  }
}

/* ------------------------------------------------------------------ images */

async function loadImages() {
  if (!state.currentGroup) {
    state.images = [];
    renderImages();
    return;
  }
  try {
    const result = unwrap(await bridge.apiGet(`groups/${state.currentGroup}/images`));
    state.images = result.images || [];
  } catch (err) {
    showToast(`鍔犺浇鍥剧墖澶辫触: ${err.message}`, "error");
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
    empty.textContent = "璇峰厛閫夋嫨涓€涓粍鍒€?;
    meta.textContent = "";
    $("#btn-batch-delete").disabled = true;
    $("#btn-reset-group-history").disabled = true;
    return;
  }
  empty.hidden = state.images.length > 0;
  empty.textContent = "璇ョ粍鍒笅杩樻病鏈夊浘鐗囷紝鍘讳笂浼犲嚑寮犲惂銆?;
  meta.textContent = `鍏?${state.images.length} 寮燻;
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
  toggle.textContent = "鉁?;
  toggle.title = "閫変腑";
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
  // Load image via bridge API (direct URL fails in sandboxed iframe)
  loadImageData(group, filename).then((dataUrl) => {
    img.src = dataUrl;
  }).catch(() => {
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
  del.textContent = "鍒犻櫎";
  del.addEventListener("click", (e) => {
    e.stopPropagation();
    onDeleteImage(group, filename);
  });
  meta.append(name, del);
  card.appendChild(meta);
  return card;
}

async function loadImageData(group, filename) {
  const result = await bridge.apiGet("images/data", {
    name: group,
    filename: filename,
  });
  return result.data_url;
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

/* ------------------------------------------------------------------ upload */

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.onerror = () => reject(reader.error || new Error("璇诲彇鏂囦欢澶辫触"));
    reader.readAsDataURL(file);
  });
}

async function handleUploadFiles(files) {
  if (!state.currentGroup) {
    showToast("璇峰厛閫夋嫨涓€涓粍鍒?, "error");
    return;
  }
  let uploaded = 0;
  for (const file of files) {
    try {
      const base64 = await readFileAsBase64(file);
      await bridge.apiPost(
        `groups/${state.currentGroup}/images`,
        {
          filename: file.name || "image",
          mime_type: file.type || "image/png",
          content_base64: base64,
        }
      );
      uploaded += 1;
    } catch (err) {
      showToast(`涓婁紶 ${file.name} 澶辫触: ${err.message}`, "error");
    }
  }
  if (uploaded > 0) showToast(`鎴愬姛涓婁紶 ${uploaded} 寮燻, "success");
  await loadImages();
  await refreshGroups();
  refreshStats();
}

/* ------------------------------------------------------------------ actions */

async function onDeleteImage(group, filename) {
  if (!await showConfirm("鍒犻櫎鍥剧墖", `纭畾鍒犻櫎 "${filename}" 鍚楋紵`)) return;
  try {
    await bridge.apiPost(`groups/${group}/images/delete`, {
      filenames: [filename],
    });
    showToast("宸插垹闄?, "success");
    state.selected.delete(filename);
    await loadImages();
    await refreshGroups();
    refreshStats();
  } catch (err) {
    showToast(`鍒犻櫎澶辫触: ${err.message}`, "error");
  }
}

async function onBatchDelete() {
  if (state.selected.size === 0) return;
  const filenames = Array.from(state.selected);
  if (!await showConfirm("鎵归噺鍒犻櫎", `纭畾瑕佹壒閲忓垹闄?${filenames.length} 寮犲浘鐗囧悧锛焋)) return;
  try {
    const result = unwrap(await bridge.apiPost(
      `groups/${state.currentGroup}/images/delete`,
      { filenames }
    ));
    showToast(`宸插垹闄?${result.removed.length} 寮燻, "success");
    state.selected.clear();
    await loadImages();
    await refreshGroups();
    refreshStats();
  } catch (err) {
    showToast(`鎵归噺鍒犻櫎澶辫触: ${err.message}`, "error");
  }
}

async function onResetGroupHistory() {
  if (!state.currentGroup) return;
  if (!await showConfirm("閲嶇疆搴忓垪", `閲嶇疆缁勫埆 "${state.currentGroup}" 鐨勬娊鍙栧簭鍒楋紵`)) return;
  try {
    await bridge.apiPost(`groups/${state.currentGroup}/reset`);
    showToast("鎶藉彇搴忓垪宸查噸缃?, "success");
    refreshStats();
  } catch (err) {
    showToast(`閲嶇疆澶辫触: ${err.message}`, "error");
  }
}

async function onResetAll() {
  if (!await showConfirm("閲嶇疆鍏ㄩ儴", "閲嶇疆鎵€鏈夌粍鍒殑鎶藉彇搴忓垪锛燂紙涓嶄細鍒犻櫎浠讳綍鍥剧墖锛?)) return;
  try {
    const result = unwrap(await bridge.apiPost("reset"));
    showToast(`宸查噸缃?${result.groups_cleared} 涓粍鍒玚, "success");
    refreshStats();
  } catch (err) {
    showToast(`閲嶇疆澶辫触: ${err.message}`, "error");
  }
}

async function onDeleteGroup(g) {
  if (!await showConfirm("鍒犻櫎缁勫埆", `鍒犻櫎缁勫埆 "${g.name}"锛熻缁勫埆涓嬫墍鏈夊浘鐗囦篃浼氳鍒犻櫎锛屾鎿嶄綔涓嶅彲鎭㈠銆俙)) return;
  try {
    await bridge.apiPost(`groups/${g.name}/delete`);
    showToast("缁勫埆宸插垹闄?, "success");
    if (state.currentGroup === g.name) {
      state.currentGroup = null;
    }
    state.selected.clear();
    await refreshGroups();
    refreshStats();
  } catch (err) {
    showToast(`鍒犻櫎澶辫触: ${err.message}`, "error");
  }
}

/* ------------------------------------------------------------------ group dialog */

function openGroupDialog(group = null) {
  state.dialogMode = group ? "edit" : "create";
  state.editing = group;
  $("#group-dialog-title").textContent = group ? `缂栬緫缁勫埆: ${group.name}` : "鏂板缓缁勫埆";
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
  const btnText = btn.textContent;
  state.submitting = true;
  btn.disabled = true;
  btn.textContent = "淇濆瓨涓€?;
  try {
    if (isCreate) {
      if (!name) { showToast("璇疯緭鍏ョ粍鍒悕绉?, "error"); return; }
      await bridge.apiPost("groups", { name, aliases, require_wake });
      showToast(`宸插垱寤? ${name}`, "success");
    } else {
      await bridge.apiPost(`groups/${state.editing.name}/update`, {
        aliases, require_wake, enabled,
      });
      showToast(`宸叉洿鏂? ${state.editing.name}`, "success");
    }
    await new Promise(r => setTimeout(r, 600));
    closeGroupDialog();
    await refreshGroups();
    refreshStats();
  } catch (err) {
    showToast(`淇濆瓨澶辫触: ${err.message}`, "error");
  } finally {
    state.submitting = false;
    btn.disabled = false;
    btn.textContent = btnText;
  }
}

/* ------------------------------------------------------------------ render helpers */

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
    tr.appendChild(makeStatusPillCell(g.require_wake, "wake", "闇€鍞ら啋", "鏃犻渶鍞ら啋"));
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
  pill.textContent = value ? onText || "鍚敤" : offText || "绂佺敤";
  cell.appendChild(pill);
  return cell;
}

function makeActionCell(g) {
  const cell = document.createElement("td");
  cell.style.whiteSpace = "nowrap";

  const editBtn = document.createElement("button");
  editBtn.className = "btn";
  editBtn.textContent = "缂栬緫";
  editBtn.style.marginRight = "6px";
  editBtn.addEventListener("click", () => openGroupDialog(g));

  const delBtn = document.createElement("button");
  delBtn.className = "btn danger";
  delBtn.textContent = "鍒犻櫎";
  delBtn.addEventListener("click", () => onDeleteGroup(g));

  cell.append(editBtn, delBtn);
  return cell;
}

function renderGroupSelect() {
  const select = $("#image-group-select");
  const prevValue = select.value;  // 璁颁綇褰撳墠閫変腑鐨勫€?
  select.innerHTML = "";
  for (const g of state.groups) {
    const opt = document.createElement("option");
    opt.value = g.name;
    opt.textContent = `${g.name} (${g.image_count})`;
    select.appendChild(opt);
  }
  // 濡傛灉涔嬪墠閫変腑鐨勭粍鍒繕鍦ㄥ垪琛ㄤ腑锛屼繚鎸侀€変腑锛涘惁鍒欓€夌涓€涓?
  if (prevValue && [...select.options].some(o => o.value === prevValue)) {
    select.value = prevValue;
  }
  state.currentGroup = select.value || null;
  if (state.currentGroup) loadImages();
}

function renderSettings() {
  const list = $("#settings-list");
  list.innerHTML = "";
  const rows = [
    ["宸叉敞鍐岀粍鍒?, `${state.groups.length}`],
    ["鎻掍欢鍚嶏紙鐢ㄤ簬 bridge API 鍓嶇紑锛?, PLUGIN_NAME],
    ["鏀寔鐨勫浘鐗囨牸寮?, ".jpg / .jpeg / .png / .webp / .bmp / .gif"],
    ["鎶藉彇瑙勫垯", "闅忔満 + 涓嶉噸澶嶏紱璺戝畬涓€杞嚜鍔ㄩ噸缃紙鍏ㄥ眬鍏变韩鎶藉彇姹狅級"],
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
    ["缁勫埆鏁?, `${stats.group_count}`],
    ["鍥剧墖鎬绘暟", `${stats.image_total}`],
    ["鏈疆绱鎶藉彇", `${stats.history_size}`],
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

/* ------------------------------------------------------------------ toast */

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
    `<pre style="color:red;padding:12px;">鍒濆鍖栧け璐? ${err.message}</pre>`
  );
});



