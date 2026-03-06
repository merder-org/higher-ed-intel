
async function loadJSON(url){
  const res = await fetch(url, { cache: "no-store" });
  if(!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
  return await res.json();
}
function el(tag, attrs = {}, children = []){
  const node = document.createElement(tag);
  for(const [k,v] of Object.entries(attrs)){
    if(k === "class") node.className = v;
    else if(k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for(const child of children){
    if(child == null) continue;
    if(typeof child === "string") node.appendChild(document.createTextNode(child));
    else node.appendChild(child);
  }
  return node;
}
async function copyText(text, btn){
  await navigator.clipboard.writeText(text);
  if(btn){
    const old = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(()=> btn.textContent = old, 1000);
  }
}
function renderMeta(data){
  const box = document.getElementById("metaBox");
  const feedWarnings = (data.feed_errors || []).length;
  box.innerHTML = `<div><strong>Week of:</strong> ${data.week_of}</div><div><strong>Generated:</strong> ${data.generated_at}</div><div><strong>Items:</strong> ${data.items.length}</div><div><strong>Feed warnings:</strong> ${feedWarnings}</div>`;
}
function renderDrafts(data){
  const wrap = document.getElementById("linkedinDrafts");
  wrap.innerHTML = "";
  const drafts = data.linkedin_drafts || [];
  if(!drafts.length){ wrap.appendChild(el("div", {class:"empty"}, ["No drafts available."])); return; }
  drafts.forEach((d, i) => {
    const btn = el("button", {class:"btn", onclick:()=>copyText(d.text || "", btn)}, ["Copy"]);
    wrap.appendChild(el("div", {class:"draft-card"}, [
      el("div", {class:"kicker"}, [`Draft ${i+1}`]),
      el("h3", {}, [d.title || `Draft ${i+1}`]),
      el("div", {class:"draft-text"}, [d.text || ""]),
      el("div", {class:"copy-row"}, [btn])
    ]));
  });
  document.getElementById("copyAllDraftsBtn").onclick = () => {
    const all = drafts.map(d => d.text || "").join("\n\n---\n\n");
    copyText(all, document.getElementById("copyAllDraftsBtn"));
  };
}
function renderSignals(data){
  const wrap = document.getElementById("topSignals");
  wrap.innerHTML = "";
  const items = (data.top_signals || []).slice(0, 6);
  if(!items.length){ wrap.appendChild(el("div", {class:"empty"}, ["No top signals available."])); return; }
  items.forEach((it) => {
    wrap.appendChild(el("div", {class:"signal-card"}, [
      el("div", {class:"kicker"}, [it.category || "Signal"]),
      el("h3", {}, [it.title || "Untitled"]),
      el("div", {class:"meta"}, [`${it.source || ""}${it.published ? " • " + it.published : ""}`]),
      el("p", {class:"signal-summary"}, [it.summary_for_brief || it.summary || ""]),
      el("p", {class:"signal-why"}, [`Why it matters: ${it.why_it_matters || ""}`]),
      el("div", {class:"small-links"}, [el("a", {href: it.url, target:"_blank", rel:"noopener"}, ["Open source"])])
    ]));
  });
}
function renderNotes(data){
  const wrap = document.getElementById("briefingNotes");
  wrap.innerHTML = "";
  const grid = el("div", {class:"note-grid"});
  (data.categories || []).forEach(cat => {
    const notes = (data.briefing_notes || []).filter(x => x.category === cat);
    if(!notes.length) return;
    const box = el("div", {class:"note-card"}, [el("div", {class:"kicker"}, [cat])]);
    notes.slice(0, 4).forEach(it => {
      box.appendChild(el("h3", {}, [it.title]));
      box.appendChild(el("p", {class:"note-summary"}, [it.summary_for_brief || it.summary || ""]));
      if(it.why_it_matters) box.appendChild(el("p", {class:"note-why"}, [`Why it matters: ${it.why_it_matters}`]));
    });
    grid.appendChild(box);
  });
  if(!grid.childNodes.length) wrap.appendChild(el("div", {class:"empty"}, ["No briefing notes available."]));
  else wrap.appendChild(grid);
}
function renderArchive(data){
  const wrap = document.getElementById("archiveList");
  wrap.innerHTML = "";
  (data.archive || []).forEach(a => {
    const mdUrl = a.url.replace(/\.json$/, ".md");
    wrap.appendChild(el("li", {}, [
      el("span", {}, [a.label + " — "]),
      el("a", {href: mdUrl, target:"_blank", rel:"noopener"}, ["Readable"]),
      el("span", {}, [" · "]),
      el("a", {href: a.url, target:"_blank", rel:"noopener"}, ["Raw JSON"])
    ]));
  });
}
function renderFeedErrors(data){
  const wrap = document.getElementById("feedErrors");
  wrap.innerHTML = "";
  const errs = data.feed_errors || [];
  if(!errs.length){ wrap.appendChild(el("div", {class:"empty"}, ["No feed warnings this run."])); return; }
  const ul = el("ul");
  errs.forEach(err => ul.appendChild(el("li", {}, [err])));
  wrap.appendChild(ul);
}
(async function(){
  try{
    const data = await loadJSON("data/latest.json");
    renderMeta(data); renderDrafts(data); renderSignals(data); renderNotes(data); renderArchive(data); renderFeedErrors(data);
  }catch(err){
    document.getElementById("metaBox").textContent = err.message;
  }
})();
