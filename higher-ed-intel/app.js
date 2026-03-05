async function loadJSON(url){
  const res = await fetch(url, {cache: "no-store"});
  if(!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
  return await res.json();
}

function el(tag, attrs={}, children=[]){
  const n = document.createElement(tag);
  for(const [k,v] of Object.entries(attrs)){
    if(k === "class") n.className = v;
    else if(k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for(const c of children){
    if(typeof c === "string") n.appendChild(document.createTextNode(c));
    else if(c) n.appendChild(c);
  }
  return n;
}

function render(data){
  document.getElementById("metaLine").textContent =
    `${data.week_of} • Generated ${data.generated_at} • ${data.items.length} items • v${data.schema_version}`;

  document.getElementById("rssLink").href = data.rss_url || "data/rss.xml";

  const grid = document.getElementById("categoryGrid");
  grid.innerHTML = "";
  const cats = data.categories || [];

  for(const cat of cats){
    const items = data.items.filter(x => x.category === cat);
    const box = el("div", {class:"cat"}, [
      el("h3", {}, [cat]),
      el("div", {class:"meta"}, [items.length ? `${items.length} item(s)` : "No items this week."])
    ]);

    for(const it of items){
      const badges = el("div", {class:"badges"}, [
        ...(it.tags||[]).slice(0,6).map(t => el("span",{class:"badge"},[t])),
        it.score != null ? el("span",{class:"badge"},[`score: ${it.score}`]) : null
      ].filter(Boolean));

      const title = el("div",{class:"title"},[
        el("a",{href: it.url, target:"_blank", rel:"noopener"},[it.title])
      ]);

      const src = el("div",{class:"meta"},[
        `${it.source || ""}${it.published ? " • " + it.published : ""}`
      ]);

      const why = el("div",{class:"why"},[it.why_it_matters || it.summary || ""]);

      box.appendChild(el("div",{class:"item"},[title, src, why, badges]));
    }

    grid.appendChild(box);
  }

  const draftsWrap = document.getElementById("linkedinDrafts");
  draftsWrap.innerHTML = "";
  (data.linkedin_drafts || []).forEach((d, idx) => {
    const copyBtn = el("a", {class:"btn", href:"#", onclick:(e)=>{e.preventDefault(); navigator.clipboard.writeText(d.text);} }, ["Copy"]);
    draftsWrap.appendChild(
      el("div",{class:"draft"},[
        el("div",{class:"topline"},[
          el("h3",{},[d.title || `Draft ${idx+1}`]),
          copyBtn
        ]),
        el("pre",{},[d.text || ""])
      ])
    );
  });

  document.getElementById("copyAllBtn").addEventListener("click", async (e)=>{
    e.preventDefault();
    const all = (data.linkedin_drafts||[]).map(d=>d.text).join("\n\n---\n\n");
    await navigator.clipboard.writeText(all);
    e.target.textContent = "Copied!";
    setTimeout(()=>e.target.textContent="Copy LinkedIn drafts", 1200);
  });

  const archive = document.getElementById("archiveList");
  archive.innerHTML = "";
  (data.archive || []).forEach(a=>{
    archive.appendChild(
      el("li",{},[
        el("a",{href:a.url, target:"_blank", rel:"noopener"},[a.label])
      ])
    );
  });
}

(async ()=>{
  try{
    const data = await loadJSON("data/latest.json");
    render(data);
  }catch(err){
    document.getElementById("metaLine").textContent = err.message;
    console.error(err);
  }
})();
