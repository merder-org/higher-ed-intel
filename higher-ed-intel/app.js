async function loadLatest() {
  const res = await fetch("data/latest.json", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to load brief: ${res.status}`);
  }
  return res.json();
}

function node(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") el.className = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value);
  }
  for (const child of children) {
    if (child === null || child === undefined) continue;
    if (typeof child === "string") el.appendChild(document.createTextNode(child));
    else el.appendChild(child);
  }
  return el;
}

async function copyToClipboard(text, button) {
  await navigator.clipboard.writeText(text);
  if (button) {
    const original = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => (button.textContent = original), 1200);
  }
}

function renderFreshness(data) {
  const panel = document.getElementById("freshnessPanel");
  const fresh = data.freshness || {};
  panel.innerHTML = "";
  panel.appendChild(
    node("div", { class: "freshness-grid" }, [
      node("div", {}, [node("div", { class: "metric-label" }, ["Cycle date"]), node("div", { class: "metric-value" }, [fresh.cycle_date || data.cycle_date || "N/A"])]),
      node("div", {}, [node("div", { class: "metric-label" }, ["Generated"]), node("div", { class: "metric-value" }, [data.generated_at || "N/A"])]),
      node("div", {}, [node("div", { class: "metric-label" }, ["New signals"]), node("div", { class: "metric-value" }, [String(fresh.new_count ?? 0)])]),
      node("div", {}, [node("div", { class: "metric-label" }, ["Updated signals"]), node("div", { class: "metric-value" }, [String(fresh.updated_count ?? 0)])]),
      node("div", {}, [node("div", { class: "metric-label" }, ["Cadence"]), node("div", { class: "metric-value" }, [data.cadence || "Monday / Wednesday / Friday"])])
    ])
  );
}

function renderTopSignals(data) {
  const wrap = document.getElementById("topSignals");
  wrap.innerHTML = "";

  const signals = data.top_signals || [];
  if (!signals.length) {
    wrap.appendChild(node("p", { class: "empty" }, ["No strong signals passed quality threshold this cycle."]));
    return;
  }

  signals.forEach((item) => {
    const tags = node("div", { class: "tags" }, (item.labels || []).map((label) => {
      const noveltyClass = label === "NEW" ? " tag-new" : (label === "UPDATED" ? " tag-updated" : "");
      return node("span", { class: "tag" + noveltyClass }, [label]);
    }));
    wrap.appendChild(
      node("article", { class: "signal-card" }, [
        node("h3", {}, [item.headline || "Untitled signal"]),
        node("p", { class: "signal-meta" }, [`${item.source || "Unknown source"} · ${item.date || "N/A"}`]),
        tags,
        node("p", { class: "summary" }, [item.summary || ""]),
        node("p", { class: "why" }, [item.why_it_matters || ""]),
        node("a", { href: item.url, target: "_blank", rel: "noopener" }, ["Open source"])
      ])
    );
  });
}

function renderAnalysis(data) {
  const block = document.getElementById("analysisBlock");
  block.innerHTML = "";
  const text = data.why_this_matters_now || "No cycle analysis available.";
  text.split(/\n\n+/).forEach((paragraph) => {
    block.appendChild(node("p", {}, [paragraph]));
  });
}

function renderAngles(data) {
  const wrap = document.getElementById("linkedinAngles");
  wrap.innerHTML = "";
  const angles = data.linkedin_angles || [];

  if (!angles.length) {
    wrap.appendChild(node("p", { class: "empty" }, ["No post opportunities this cycle."]));
    return;
  }

  angles.forEach((angle, index) => {
    const copyBtn = node("button", { class: "btn", onclick: () => copyToClipboard(angle.draft || "", copyBtn) }, ["Copy draft"]);
    wrap.appendChild(
      node("article", { class: "angle-card" }, [
        node("p", { class: "angle-number" }, [`Opportunity ${index + 1}`]),
        node("h3", {}, [angle.hook || "Untitled"]),
        node("p", { class: "angle" }, [angle.angle || ""]),
        node("pre", { class: "draft" }, [angle.draft || ""]),
        node("div", { class: "actions" }, [copyBtn])
      ])
    );
  });

  const firstDraft = angles[0]?.draft || "";
  const topBtn = document.getElementById("copyTopDraftBtn");
  topBtn.onclick = () => copyToClipboard(firstDraft, topBtn);
}

function renderWatchList(data) {
  const wrap = document.getElementById("watchList");
  wrap.innerHTML = "";
  const watch = data.watch_list || [];

  if (!watch.length) {
    wrap.appendChild(node("li", { class: "empty" }, ["Watch list is empty this cycle."]));
    return;
  }

  watch.forEach((item) => {
    wrap.appendChild(
      node("li", {}, [
        node("a", { href: item.url, target: "_blank", rel: "noopener" }, [item.headline || "Untitled"]),
        node("span", { class: "watch-meta" }, [` — ${item.source || "Source"}, ${item.date || "N/A"}`])
      ])
    );
  });
}

function renderArchive(data) {
  const wrap = document.getElementById("archiveList");
  wrap.innerHTML = "";

  (data.archive || []).forEach((entry) => {
    const md = entry.url.replace(/\.json$/, ".md");
    wrap.appendChild(
      node("li", {}, [
        node("span", {}, [entry.label + " — "]),
        node("a", { href: md, target: "_blank", rel: "noopener" }, ["Readable"]),
        node("span", {}, [" · "]),
        node("a", { href: entry.url, target: "_blank", rel: "noopener" }, ["JSON"])
      ])
    );
  });
}

(async function init() {
  try {
    const data = await loadLatest();
    renderFreshness(data);
    renderTopSignals(data);
    renderAnalysis(data);
    renderAngles(data);
    renderWatchList(data);
    renderArchive(data);
  } catch (err) {
    document.getElementById("freshnessPanel").textContent = err.message;
  }
})();
