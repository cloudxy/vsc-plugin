const BADGE = {先锋: "#B0BBCC", 专业: "#00C5B2", 荣誉: "#FFC746"};
const ACTION = {video_generate: "视频生成", image_generate: "图片生成", video_resource: "视频素材", image_resource: "图片素材", audio_resource: "音频素材", group: "分组"};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function installCSS() {
  if (document.querySelector("link[data-featured-showcase]")) return;
  const css = el("link");
  css.rel = "stylesheet";
  css.href = "/static/featured-showcase.css";
  css.dataset.featuredShowcase = "";
  document.head.append(css);
}

function viralLabel(card) {
  const tag = (card.tags || []).find(item => String(item.code || "").startsWith("viral_likes") && item.label);
  return tag ? tag.label : "";
}

export function createFeaturedShowcase(root, {api, notice}) {
  installCSS();
  let tagId = "0";
  let query = "";
  let items = [];
  let tags = [];
  let offset = 0;
  let total = 0;
  let hasMore = false;
  let ready = true;
  let loading = false;
  let version = 0;
  let searchTimer = 0;
  let observer = null;
  let layer = null;

  function suspend() {
    version++;
    loading = false;
    clearTimeout(searchTimer);
    observer?.disconnect();
    observer = null;
    layer?.remove();
    layer = null;
  }

  function params() {
    const search = new URLSearchParams({tag_id: tagId, offset: String(offset), limit: "20"});
    if (query.trim()) search.set("q", query.trim());
    return "/api/v1/featured-showcase?" + search;
  }

  async function load() {
    suspend();
    offset = 0;
    items = [];
    await fetchPage(true);
  }

  async function fetchPage(reset) {
    if (loading) return;
    const current = version;
    loading = true;
    try {
      const data = await api(params());
      if (current !== version) return;
      ready = data.ready !== false;
      tags = data.tags || tags;
      total = data.total || 0;
      hasMore = !!data.hasMore;
      items = reset ? (data.items || []) : items.concat(data.items || []);
      offset = items.length;
      render();
    } catch (error) {
      if (current !== version) return;
      notice(error.message || "创作精选读取失败");
      if (!items.length) render();
    } finally {
      if (current === version) loading = false;
    }
  }

  function render() {
    observer?.disconnect();
    observer = null;
    root.replaceChildren();
    root.classList.add("featured-showcase");
    const head = el("div", "fs-head");
    head.append(el("h1", "", "创作精选"));
    const search = el("label", "fs-search");
    const input = el("input");
    input.type = "search";
    input.placeholder = "请输入搜索内容";
    input.value = query;
    input.setAttribute("aria-label", "请输入搜索内容");
    input.addEventListener("input", () => {
      query = input.value;
      suspend();
      searchTimer = setTimeout(() => load().catch(error => notice(error.message)), 280);
    });
    search.append(input);
    head.append(search);
    root.append(head);
    const tablist = el("div", "fs-tabs");
    tablist.setAttribute("role", "tablist");
    const choices = tags.length ? tags : [{id: 0, label: "全部", count: 0}];
    for (const tag of choices) {
      const button = el("button", "", tag.label || "全部");
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(String(tag.id) === String(tagId)));
      button.addEventListener("click", () => {
        tagId = String(tag.id);
        load().catch(error => notice(error.message));
      });
      tablist.append(button);
    }
    root.append(tablist);
    if (!ready) {
      root.append(el("p", "fs-empty", "创作精选快照还没有保存到本机。"));
      return;
    }
    if (!items.length) {
      root.append(el("p", "fs-empty", total ? "没有匹配的作品。" : "这一栏还没有作品。"));
      return;
    }
    const grid = el("div", "fs-grid");
    for (const card of items) grid.append(cardView(card));
    root.append(grid);
    const more = el("div", "fs-more", hasMore ? "继续加载" : `共 ${total} 个作品`);
    root.append(more);
    if (hasMore && typeof IntersectionObserver === "function") {
      const current = version;
      observer = new IntersectionObserver(entries => {
        if (current === version && entries.some(entry => entry.isIntersecting)) fetchPage(false);
      }, {rootMargin: "400px"});
      observer.observe(more);
    }
  }

  function cardView(card) {
    const article = el("article", "fs-card");
    const cover = el("div", "fs-cover");
    const image = el("img", "fs-still");
    image.alt = card.name || "作品封面";
    image.src = card.coverUrl || "";
    if (card.hoverCoverUrl) {
      cover.addEventListener("pointerenter", () => { image.src = card.hoverCoverUrl; });
      cover.addEventListener("pointerleave", () => { image.src = card.coverUrl || ""; });
    }
    cover.append(image);
    const viral = viralLabel(card);
    if (viral) cover.append(el("span", "fs-viral", viral));
    const process = el("button", "fs-process", "✦");
    process.type = "button";
    process.setAttribute("aria-label", "查看创作过程");
    const disabled = !card.processAvailable;
    if (disabled || !card.processReady) {
      process.setAttribute("aria-disabled", "true");
      process.title = disabled ? "画布未公开" : "创作过程尚未保存到本机";
    } else {
      process.title = "查看创作过程";
      process.addEventListener("click", event => {
        event.stopPropagation();
        openProcess(card).catch(error => notice(error.message));
      });
    }
    cover.append(process);
    cover.addEventListener("click", () => openPlayback(card));
    article.append(cover);
    const body = el("div", "fs-body");
    body.append(el("h2", "", card.name || "无标题"));
    const meta = el("div", "fs-meta");
    if (card.avatar) {
      const avatar = el("img");
      avatar.alt = "";
      avatar.src = card.avatar;
      meta.append(avatar);
    }
    meta.append(el("span", "fs-name", card.nickname || "未知用户"));
    const badge = (card.userTags || [])[0];
    if (badge?.name && BADGE[badge.name]) {
      const chip = el("span", "fs-badge", badge.name);
      chip.style.color = BADGE[badge.name];
      meta.append(chip);
    }
    if (card.likeCount) meta.append(el("span", "fs-likes", `♥ ${card.likeCount}`));
    body.append(meta);
    if (card.skillNames?.length) body.append(el("p", "fs-skills", card.skillNames.join(" · ")));
    article.append(body);
    return article;
  }

  function openPlayback(card) {
    if (!card.finalOutput) return;
    closeLayer();
    layer = el("div", "fs-process-layer");
    const bar = el("div", "fs-process-bar");
    bar.append(el("strong", "", card.name || "成片"));
    const close = el("button", "fs-close", "关闭");
    close.type = "button";
    close.addEventListener("click", closeLayer);
    bar.append(close);
    layer.append(bar);
    const video = el("video");
    video.controls = true;
    video.autoplay = true;
    video.src = card.finalOutput;
    video.style.cssText = "flex:1;width:100%;background:#000;max-height:calc(100% - 52px)";
    layer.append(video);
    document.body.append(layer);
  }

  async function openProcess(card) {
    const current = version;
    let data;
    try {
      data = await api("/api/v1/featured-showcase/" + encodeURIComponent(card.templateUuid));
    } catch (error) {
      if (current !== version) return;
      throw error;
    }
    if (current !== version) return;
    closeLayer();
    const process = data.process || {nodes: [], edges: []};
    const nodes = process.nodes || [];
    const byId = Object.fromEntries(nodes.map(node => [node.id, node]));
    let mode = "workflow";
    let selected = "";
    let showEdges = true;
    let scale = 0.1;
    let originX = 40;
    let originY = 40;
    layer = el("div", "fs-process-layer");
    const bar = el("div", "fs-process-bar");
    const modes = el("div", "fs-modes");
    const workflow = el("button", "", "工作流");
    const board = el("button", "", "故事板");
    workflow.type = "button";
    board.type = "button";
    modes.append(workflow, board);
    bar.append(modes);
    bar.append(el("span", "fs-readonly", "只读模式，如需创建请点击"));
    const copy = el("button", "fs-copy", "复制项目");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      const lines = nodes.filter(node => node.prompt).slice(0, 40).map(node => `${node.name || node.id}\n${node.prompt}`);
      const text = [`${data.name || card.name}`, ...lines].join("\n\n");
      try { await navigator.clipboard.writeText(text); } catch { /* 页面没有剪贴板权限时仍给出说明 */ }
      notice("当前是只读创作过程，已保留在本机，不会提交到生成服务。");
    });
    const close = el("button", "fs-close", "关闭");
    close.type = "button";
    close.addEventListener("click", closeLayer);
    bar.append(copy, close);
    layer.append(bar);
    const body = el("div", "fs-process-body");
    layer.append(body);
    document.body.append(layer);
    document.addEventListener("keydown", onKey);

    function onKey(event) {
      if (event.key === "Escape") closeLayer();
    }

    function closeLayer() {
      document.removeEventListener("keydown", onKey);
      layer?.remove();
      layer = null;
    }

    function focusNode(id) {
      selected = id;
      const node = byId[id];
      if (!node) return;
      if (!stage()) paint();
      const rect = stage()?.getBoundingClientRect();
      if (rect?.width) {
        originX = rect.width / 2 - (node.x + node.width / 2) * scale;
        originY = rect.height / 2 - (node.y + node.height / 2) * scale;
      }
      paint();
    }

    function stage() {
      return layer?.querySelector(".fs-stage");
    }

    function paint() {
      workflow.setAttribute("aria-pressed", String(mode === "workflow"));
      board.setAttribute("aria-pressed", String(mode === "board"));
      body.replaceChildren();
      body.append(outline());
      if (mode === "board") body.append(storyboard());
      else body.append(canvas());
      if (selected && byId[selected]) body.append(inspector(byId[selected]));
    }

    function outline() {
      const aside = el("aside", "fs-outline");
      const header = el("header");
      header.append(el("strong", "", data.name || card.name || "创作过程"));
      const search = el("input");
      search.placeholder = "搜索节点";
      search.setAttribute("aria-label", "搜索节点");
      const filter = el("select");
      filter.setAttribute("aria-label", "筛选");
      for (const [value, label] of [["", "筛选：全部"], ["image", "图片"], ["video", "视频"], ["audio", "音频"], ["group", "分组"]]) {
        const option = el("option", "", label);
        option.value = value;
        filter.append(option);
      }
      header.append(search, filter);
      aside.append(header);
      const tree = el("div", "fs-tree");
      aside.append(tree);
      function refill() {
        const needle = search.value.trim().toLowerCase();
        const kind = filter.value;
        tree.replaceChildren();
        const groups = nodes.filter(node => node.type === "group");
        const loose = nodes.filter(node => node.type !== "group" && !node.parentId);
        for (const group of groups) {
          const children = (group.childIds || []).map(id => byId[id]).filter(Boolean);
          const visible = [group, ...children].filter(node => (!kind || node.type === kind) && (!needle || String(node.name || "").toLowerCase().includes(needle)));
          if (!visible.length) continue;
          const details = el("details");
          details.open = true;
          const summary = el("summary", "", group.name || "分组");
          details.append(summary);
          const jump = el("button", "fs-jump", "定位到分组 " + (group.name || ""));
          jump.type = "button";
          jump.addEventListener("click", () => { mode = "workflow"; focusNode(group.id); });
          details.append(jump);
          for (const child of children) {
            if (kind && child.type !== kind) continue;
            if (needle && !String(child.name || "").toLowerCase().includes(needle)) continue;
            const button = el("button", "fs-jump", "定位到节点 " + (child.name || child.id));
            button.type = "button";
            button.setAttribute("aria-current", String(selected === child.id));
            button.addEventListener("click", () => { mode = "workflow"; focusNode(child.id); });
            details.append(button);
          }
          tree.append(details);
        }
        for (const node of loose) {
          if (kind && node.type !== kind) continue;
          if (needle && !String(node.name || "").toLowerCase().includes(needle)) continue;
          const button = el("button", "fs-jump", node.name || node.id);
          button.type = "button";
          button.addEventListener("click", () => { mode = "workflow"; focusNode(node.id); });
          tree.append(button);
        }
      }
      search.addEventListener("input", refill);
      filter.addEventListener("change", refill);
      refill();
      return aside;
    }

    function canvas() {
      const stageNode = el("div", "fs-stage");
      const world = el("div", "fs-world");
      const edges = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      edges.setAttribute("class", "fs-edges");
      world.append(edges);
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      const ordered = [...nodes.filter(node => node.type === "group"), ...nodes.filter(node => node.type !== "group")];
      for (const node of ordered) {
        minX = Math.min(minX, node.x);
        minY = Math.min(minY, node.y);
        maxX = Math.max(maxX, node.x + node.width);
        maxY = Math.max(maxY, node.y + node.height);
        const block = el("button", "fs-node" + (node.type === "group" ? " group" : ""));
        block.type = "button";
        block.style.left = node.x + "px";
        block.style.top = node.y + "px";
        block.style.width = node.width + "px";
        block.style.height = node.height + "px";
        if (node.groupColor) block.style.borderColor = node.groupColor;
        block.setAttribute("aria-current", String(selected === node.id));
        block.setAttribute("aria-label", node.name || node.type);
        block.append(el("div", "fs-node-name", node.name || ACTION[node.action] || node.type));
        if (node.type === "image" && node.url) {
          const picture = el("img");
          picture.alt = "";
          picture.src = node.url;
          block.append(picture);
        }
        block.addEventListener("click", event => {
          event.stopPropagation();
          selected = node.id;
          paint();
        });
        world.append(block);
      }
      if (showEdges) {
        const width = Math.max(1, maxX - minX);
        const height = Math.max(1, maxY - minY);
        edges.setAttribute("viewBox", `${minX} ${minY} ${width} ${height}`);
        edges.style.left = minX + "px";
        edges.style.top = minY + "px";
        edges.style.width = width + "px";
        edges.style.height = height + "px";
        for (const edge of process.edges || []) {
          const source = byId[edge.source];
          const target = byId[edge.target];
          if (!source || !target) continue;
          const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
          line.setAttribute("x1", source.x + source.width);
          line.setAttribute("y1", source.y + source.height / 2);
          line.setAttribute("x2", target.x);
          line.setAttribute("y2", target.y + target.height / 2);
          line.setAttribute("stroke", "rgba(180,180,190,.45)");
          line.setAttribute("stroke-width", "2");
          edges.append(line);
        }
      }
      world.style.transform = `translate(${originX}px, ${originY}px) scale(${scale})`;
      stageNode.append(world);
      const controls = el("div", "fs-controls");
      const minimap = el("button", "", "切换小地图");
      minimap.type = "button";
      minimap.addEventListener("click", () => fit(stageNode));
      const wires = el("button", "", showEdges ? "隐藏节点连线" : "显示节点连线");
      wires.type = "button";
      wires.addEventListener("click", () => { showEdges = !showEdges; paint(); });
      const zoom = el("button", "", `缩放选项 ${Math.round(scale * 100)}%`);
      zoom.type = "button";
      zoom.addEventListener("click", () => { scale = Math.min(1.6, scale * 1.25); paint(); });
      controls.append(minimap, wires, zoom);
      stageNode.append(controls);
      stageNode.addEventListener("pointerdown", event => {
        if (event.target !== stageNode && event.target !== world) return;
        const startX = event.clientX;
        const startY = event.clientY;
        const ox = originX;
        const oy = originY;
        function move(next) {
          originX = ox + next.clientX - startX;
          originY = oy + next.clientY - startY;
          world.style.transform = `translate(${originX}px, ${originY}px) scale(${scale})`;
        }
        function up() {
          stageNode.removeEventListener("pointermove", move);
          stageNode.removeEventListener("pointerup", up);
        }
        stageNode.addEventListener("pointermove", move);
        stageNode.addEventListener("pointerup", up);
      });
      stageNode.addEventListener("wheel", event => {
        event.preventDefault();
        const next = event.deltaY > 0 ? scale * 0.9 : scale * 1.1;
        scale = Math.min(1.6, Math.max(0.02, next));
        world.style.transform = `translate(${originX}px, ${originY}px) scale(${scale})`;
        zoom.textContent = `缩放选项 ${Math.round(scale * 100)}%`;
      }, {passive: false});
      if (!selected) requestAnimationFrame(() => fit(stageNode));
      return stageNode;
    }

    function fit(stageNode) {
      if (!nodes.length) return;
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (const node of nodes) {
        minX = Math.min(minX, node.x);
        minY = Math.min(minY, node.y);
        maxX = Math.max(maxX, node.x + node.width);
        maxY = Math.max(maxY, node.y + node.height);
      }
      const rect = stageNode.getBoundingClientRect();
      const spanX = Math.max(1, maxX - minX);
      const spanY = Math.max(1, maxY - minY);
      scale = Math.min(1, (rect.width - 48) / spanX, (rect.height - 48) / spanY);
      originX = 24 - minX * scale;
      originY = 24 - minY * scale;
      const world = stageNode.querySelector(".fs-world");
      if (world) world.style.transform = `translate(${originX}px, ${originY}px) scale(${scale})`;
    }

    function storyboard() {
      const boardNode = el("div", "fs-board");
      const groups = nodes.filter(node => node.type === "group").sort((a, b) => a.y - b.y || a.x - b.x);
      const used = new Set();
      function shots(list) {
        return list.filter(node => node.type === "video" && node.url).sort((a, b) => a.x - b.x);
      }
      function section(title, list) {
        const videos = shots(list);
        if (!videos.length) return;
        const block = el("section");
        block.append(el("h3", "", title));
        const grid = el("div", "fs-shots");
        for (const node of videos) {
          used.add(node.id);
          const article = el("article");
          const video = el("video");
          video.controls = true;
          video.preload = "none";
          video.src = node.url;
          if (node.poster) video.poster = node.poster;
          article.append(video, el("p", "", node.name || "视频"));
          article.addEventListener("click", () => { selected = node.id; paint(); });
          grid.append(article);
        }
        block.append(grid);
        boardNode.append(block);
      }
      for (const group of groups) section(group.name || "分组", (group.childIds || []).map(id => byId[id]).filter(Boolean));
      section("未分组", nodes.filter(node => !used.has(node.id)));
      if (!boardNode.childElementCount) boardNode.append(el("p", "", "这个作品没有可播放的视频节点。"));
      return boardNode;
    }

    function inspector(node) {
      const aside = el("aside", "fs-inspector");
      aside.append(el("h3", "", node.name || "节点"));
      aside.append(el("p", "", ACTION[node.action] || node.type || ""));
      if (node.model) aside.append(el("p", "", "模型 " + node.model + (node.modeType ? " · " + node.modeType : "")));
      const setting = Object.entries(node.settings || {}).map(([key, value]) => `${key} ${value}`).join(" · ");
      if (setting) aside.append(el("p", "", setting));
      if (node.taskStatus != null) aside.append(el("p", "", node.taskStatus === 2 ? "生成状态 已完成" : "生成状态 " + node.taskStatus));
      if (node.prompt) aside.append(el("p", "fs-prompt", node.prompt));
      if (node.refs?.length) {
        const list = el("ul");
        for (const ref of node.refs) {
          const item = el("li");
          const button = el("button", "", (ref.label || ref.nodeId) + " · " + ref.kind);
          button.type = "button";
          button.addEventListener("click", () => focusNode(ref.nodeId));
          item.append(button);
          list.append(item);
        }
        aside.append(list);
      }
      if (node.url && node.type !== "group") {
        const media = node.type === "audio" ? el("audio") : node.type === "image" ? el("img") : el("video");
        if (media.tagName !== "IMG") { media.controls = true; media.src = node.url; }
        else { media.src = node.url; media.alt = node.name || ""; }
        media.style.width = "100%";
        aside.append(media);
      }
      return aside;
    }

    workflow.addEventListener("click", () => { mode = "workflow"; paint(); });
    board.addEventListener("click", () => { mode = "board"; paint(); });
    paint();
  }

  function closeLayer() {
    layer?.remove();
    layer = null;
  }

  return {load, suspend};
}
