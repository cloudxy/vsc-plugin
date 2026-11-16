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
  let layerVersion = 0;
  let layerContext = null;

  function suspend(preserveRoute = false) {
    version++;
    loading = false;
    clearTimeout(searchTimer);
    observer?.disconnect();
    observer = null;
    closeLayer(false, !preserveRoute);
    if (!preserveRoute) updateWorkRoute("");
  }

  function params() {
    const search = new URLSearchParams({tag_id: tagId, offset: String(offset), limit: "20"});
    if (query.trim()) search.set("q", query.trim());
    return "/api/v1/featured-showcase?" + search;
  }

  async function load() {
    const workId = requestedWork();
    suspend(true);
    const current = version;
    offset = 0;
    items = [];
    await fetchPage(true);
    if (current !== version || !workId || requestedWork() !== workId || layerContext) return;
    const card = items.find(item => item.templateUuid === workId) || {templateUuid: workId, name: "制作过程", structureStatus: "ready"};
    const opener = [...root.querySelectorAll(".fs-process")].find(control => control.dataset.workId === workId);
    openProcess(card, opener);
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
    const play = button("", event => {
      event.stopPropagation();
      openPlayback(card, play);
    }, "fs-play-cover");
    play.dataset.workId = card.templateUuid || "";
    play.setAttribute("aria-label", "播放 " + (card.name || "成片"));
    const image = el("img", "fs-still");
    image.alt = card.name || "作品封面";
    image.src = card.coverUrl || "";
    if (card.hoverCoverUrl) {
      cover.addEventListener("pointerenter", () => { image.src = card.hoverCoverUrl; });
      cover.addEventListener("pointerleave", () => { image.src = card.coverUrl || ""; });
    }
    play.append(image);
    const viral = viralLabel(card);
    if (viral) play.append(el("span", "fs-viral", viral));
    cover.append(play);
    const process = el("button", "fs-process", "查看制作过程");
    process.type = "button";
    process.dataset.workId = card.templateUuid || "";
    process.setAttribute("aria-label", "查看制作过程");
    process.title = structureMessage(card) || "查看制作过程";
    process.addEventListener("click", event => {
      event.stopPropagation();
      openProcess(card, process);
    });
    cover.append(process);
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

  function localURL(value) {
    return typeof value === "string" && /^\/(?!\/)/.test(value) ? value : "";
  }

  function requestedWork() {
    if (typeof window === "undefined" || !window.location) return "";
    const route = new URLSearchParams(window.location.search || "");
    if (route.get("page") !== "featured-showcase" && !(window.location.pathname === "/show" && !route.has("page"))) return "";
    return route.get("showcase_work") || "";
  }

  function updateWorkRoute(workId, expected) {
    if (typeof window === "undefined" || !window.location || !window.history?.replaceState) return;
    const route = new URLSearchParams(window.location.search || "");
    if (route.get("page") !== "featured-showcase" && !(window.location.pathname === "/show" && !route.has("page"))) return;
    if (expected && route.get("showcase_work") !== expected) return;
    if (workId) route.set("showcase_work", workId);
    else route.delete("showcase_work");
    const search = route.toString();
    if (search === (window.location.search || "").replace(/^\?/, "")) return;
    window.history.replaceState(window.history.state ?? null, "", (window.location.pathname || "/") + (search ? "?" + search : "") + (window.location.hash || ""));
  }

  function structureMessage(card) {
    const status = card.structureStatus || (card.processReady ? "ready" : card.processAvailable === false ? "unpublished" : "missing");
    return ({unpublished: "这个作品的制作过程未公开。", missing: "制作过程尚未保存到本机。", invalid: "本机制作过程快照损坏，暂时无法查看。"})[status] || "";
  }

  function pauseMedia(container, release = false) {
    if (!container) return;
    for (const tag of ["video", "audio"]) for (const media of container.querySelectorAll(tag)) {
      media.pause?.();
      if (release) { media.removeAttribute("src"); media.load?.(); }
    }
  }

  function closeLayer(restoreFocus = true, clearRoute = true) {
    layerVersion++;
    const context = layerContext;
    if (context) {
      if (clearRoute) updateWorkRoute("", context.card.templateUuid);
      document.removeEventListener("keydown", context.onKey);
      pauseMedia(context.playback, true);
      pauseMedia(context.processView, true);
      pauseMedia(layer, true);
    }
    layer?.remove();
    layer = null;
    layerContext = null;
    if (restoreFocus && context) {
      let target = context.opener;
      if (!target || !document.body.contains(target)) {
        const selector = context.opener?.classList.contains("fs-play-cover") ? ".fs-play-cover" : ".fs-process";
        target = [...root.querySelectorAll(selector)].find(control => control.dataset.workId === context.card.templateUuid) || root;
      }
      target.focus?.({preventScroll: true});
    }
  }

  function createLayer(card, opener) {
    closeLayer(false);
    layer = el("div", "fs-process-layer");
    layer.setAttribute("role", "dialog");
    layer.setAttribute("aria-modal", "true");
    layer.setAttribute("aria-label", card.name || "制作过程");
    root.tabIndex = -1;
    const returnFocus = opener || (root.contains(document.activeElement) ? document.activeElement : root);
    const context = {card, opener: returnFocus, layer, serial: layerVersion, request: 0, playback: null, onEscape: null};
    context.onKey = event => {
      if (layerContext !== context) return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (context.onEscape) context.onEscape();
        else closeLayer();
      } else if (event.key === "Tab") {
        const controls = [];
        function collect(parent) {
          for (const node of parent.children) {
            if (node.hidden) continue;
            if (["BUTTON", "INPUT", "SELECT", "VIDEO", "AUDIO", "SUMMARY"].includes(node.tagName) && !node.disabled) controls.push(node);
            collect(node);
          }
        }
        collect(layer);
        const first = controls[0], last = controls.at(-1);
        if (first && (!layer.contains(document.activeElement) || (!event.shiftKey && document.activeElement === last) || (event.shiftKey && document.activeElement === first))) {
          event.preventDefault();
          (event.shiftKey ? last : first).focus();
        }
      }
    };
    layerContext = context;
    document.addEventListener("keydown", context.onKey);
    document.body.append(layer);
    return context;
  }

  function button(label, onClick, className = "") {
    const control = el("button", className, label);
    control.type = "button";
    control.addEventListener("click", onClick);
    return control;
  }

  function navigation(context, bar) {
    if (context.playback) bar.append(button("返回成片", () => showPlayback(context), "fs-back"));
    bar.append(button("关闭", () => closeLayer(), "fs-close"));
  }

  function openPlayback(card, opener) {
    if (!localURL(card.finalOutput)) { notice("成片尚未缓存到本机。"); return; }
    const context = createLayer(card, opener);
    const view = el("div", "fs-playback");
    const bar = el("div", "fs-process-bar");
    bar.append(el("strong", "fs-title", card.name || "成片"));
    const process = button("查看制作过程", () => openProcess(card, process, context), "fs-open-process");
    process.title = structureMessage(card) || "查看制作过程";
    bar.append(process);
    navigation(context, bar);
    const video = el("video", "fs-final-video");
    video.controls = true;
    video.autoplay = true;
    video.preload = "metadata";
    video.src = localURL(card.finalOutput);
    view.append(bar, video);
    context.playback = view;
    context.playbackButton = process;
    showPlayback(context);
  }

  function showPlayback(context) {
    if (layerContext !== context || !context.playback) return;
    context.request++;
    updateWorkRoute("", context.card.templateUuid);
    pauseMedia(layer);
    context.onEscape = null;
    layer.dataset.view = "playback";
    layer.replaceChildren(context.playback);
    context.playbackButton.focus?.({preventScroll: true});
  }

  async function openProcess(card, opener, existing) {
    const context = existing && layerContext === existing ? existing : createLayer(card, opener);
    updateWorkRoute(card.templateUuid || "");
    pauseMedia(context.playback);
    const current = version;
    const request = ++context.request;
    const active = () => current === version && layerContext === context && context.serial === layerVersion && request === context.request;
    if (context.processView) {
      layer.dataset.view = "process";
      layer.replaceChildren(context.processView);
      context.onEscape = context.processEscape;
      context.resumeProcess();
      return;
    }
    const shell = el("div", "fs-process-status");
    const bar = el("div", "fs-process-bar");
    bar.append(el("strong", "fs-title", card.name || "制作过程"));
    navigation(context, bar);
    const message = el("div", "fs-status-message");
    message.setAttribute("role", "status");
    shell.append(bar, message);
    layer.replaceChildren(shell);
    layer.dataset.view = "process-loading";
    context.onEscape = () => context.playback ? showPlayback(context) : closeLayer();
    bar.querySelector("button")?.focus?.();
    const unavailable = structureMessage(card);
    if (unavailable) {
      message.append(el("p", "", unavailable));
      layer.dataset.view = "process-unavailable";
      return;
    }
    message.append(el("p", "", "正在加载制作过程…"));
    try {
      const data = await api("/api/v1/featured-showcase/" + encodeURIComponent(card.templateUuid));
      if (!active()) return;
      if (!data.process) throw new Error("制作过程没有可读取的画布结构。");
      if (data.card) {
        context.card = {...card, ...data.card};
        layer.setAttribute("aria-label", context.card.name || "制作过程");
      }
      renderProcess(context, data);
    } catch (error) {
      if (!active()) return;
      layer.dataset.view = "process-error";
      message.replaceChildren(el("p", "", error.message || "制作过程读取失败。"), button("重试", () => openProcess(card, opener, context), "fs-retry"));
    }
  }

  function outputsFor(node) {
    if (Array.isArray(node.outputs)) return node.outputs;
    return node.url ? [{index: 0, url: node.url, status: node.mediaStatus || "local", metadata: node.resourceMeta || {}}] : [];
  }

  function mediaLabel(node) {
    if (!["audio", "image", "video"].includes(node.type)) return node.type === "group" ? "分组" : "只读内容";
    const outputs = outputsFor(node);
    const local = outputs.filter(output => localURL(output.url)).length;
    if (local) return local === outputs.length ? "已缓存" : `已缓存 ${local}/${outputs.length} 个输出`;
    if (node.mediaStatus === "empty" || outputs.some(output => output.status === "empty")) return "没有输出";
    if (outputs.some(output => ["failed", "error"].includes(output.status))) return "缓存失败";
    return "待缓存";
  }

  function preview(node) {
    const area = el("div", "fs-media-preview");
    const imageURL = localURL(node.type === "image" ? (localURL(node.url) || outputsFor(node).find(output => localURL(output.url))?.url) : node.poster);
    if (imageURL) {
      const image = el("img");
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      image.src = imageURL;
      area.append(image);
    } else {
      const glyph = node.type === "video" ? "▶" : node.type === "audio" ? "♫" : node.type === "image" ? "▧" : "T";
      area.append(el("span", "fs-media-glyph", glyph));
    }
    area.append(el("span", "fs-media-status", mediaLabel(node)));
    return area;
  }

  function renderProcess(context, data) {
    const card = context.card;
    const process = data.process;
    const nodes = Array.isArray(process.nodes) ? process.nodes : [];
    const byId = new Map(nodes.map(node => [node.id, node]));
    const counts = Object.fromEntries(["audio", "image", "video"].map(kind => [kind, nodes.filter(node => node.type === kind).length]));
    let mode = "workflow", selected = "", inspectorOpen = false, directoryOpen = false, assetKind = "video";
    let showEdges = true, scale = 0.1, originX = 40, originY = 40, fitPending = true;
    const view = el("div", "fs-process-view");
    const bar = el("div", "fs-process-bar");
    const modes = el("div", "fs-modes");
    const modeButtons = new Map();
    for (const [value, label] of [["workflow", "工作流"], ["board", "故事板"], ["assets", "项目素材"]]) {
      const control = button(label, () => { mode = value; paint(); });
      modeButtons.set(value, control);
      modes.append(control);
    }
    const directory = button("目录", () => { directoryOpen = !directoryOpen; paint(); }, "fs-directory-toggle");
    bar.append(directory, modes, el("span", "fs-readonly", "只读制作过程"));
    const copy = button("复制提示词", async () => {
      const prompts = nodes.filter(node => typeof node.prompt === "string" && node.prompt.trim());
      if (!prompts.length) { notice("这个作品没有可复制的提示词。"); return; }
      const text = [data.name || card.name || "制作过程", ...prompts.map(node => `${node.name || node.id}\n${node.prompt}`)].join("\n\n");
      copy.disabled = true;
      try {
        if (!navigator.clipboard?.writeText) throw new Error("剪贴板不可用");
        await navigator.clipboard.writeText(text);
        if (layerContext === context) notice(`已复制 ${prompts.length} 条提示词。`);
      } catch {
        if (layerContext === context) notice("复制失败，请检查浏览器剪贴板权限后重试。");
      } finally { copy.disabled = false; }
    }, "fs-copy");
    bar.append(copy);
    navigation(context, bar);
    const coverage = el("div", "fs-coverage");
    const local = process.coverage?.localMediaNodes ?? nodes.filter(node => ["audio", "image", "video"].includes(node.type) && outputsFor(node).some(output => localURL(output.url))).length;
    const mediaCount = counts.audio + counts.image + counts.video;
    coverage.append(el("strong", "fs-process-name", data.name || card.name || "制作过程"));
    coverage.append(el("span", "", `${nodes.length} 个节点 · 音频 ${counts.audio} · 图片 ${counts.image} · 视频 ${counts.video} · 已缓存 ${local}/${mediaCount} 个媒体节点`));
    if (process.coverage?.missingMediaNodes || local < mediaCount) coverage.append(el("span", "fs-coverage-warning", "部分媒体待缓存，结构仍可查看。"));
    if (process.issues?.length) {
      const issues = el("details", "fs-issues");
      issues.append(el("summary", "", `${process.issues.length} 项结构提示`), el("pre", "", JSON.stringify(process.issues, null, 2)));
      coverage.append(issues);
    }
    const body = el("div", "fs-process-body");
    view.append(bar, coverage, body);
    layer.dataset.view = "process";
    layer.replaceChildren(view);
    context.onEscape = () => {
      if (inspectorOpen) closeInspector();
      else if (directoryOpen) { directoryOpen = false; paint(); directory.focus(); }
      else if (context.playback) showPlayback(context);
      else closeLayer();
    };
    context.processView = view;
    context.processEscape = context.onEscape;
    context.resumeProcess = () => (inspectorOpen ? body.querySelector(".fs-detail-close") : modeButtons.get(mode))?.focus?.({preventScroll: true});

    function closeInspector() {
      inspectorOpen = false;
      paint();
      const target = [...body.querySelectorAll("button")].find(control => control.dataset.nodeId === String(selected));
      (target || modeButtons.get(mode)).focus?.({preventScroll: true});
    }

    function selectNode(id, focus = true) {
      if (!byId.has(id)) return;
      selected = id;
      inspectorOpen = true;
      paint();
      if (focus) body.querySelector(".fs-detail-close")?.focus?.({preventScroll: true});
    }

    function geometry(node) {
      return {x: Number(node.x) || 0, y: Number(node.y) || 0, width: Math.max(1, Number(node.width) || 240), height: Math.max(1, Number(node.height) || 160)};
    }

    function focusNode(id) {
      const node = byId.get(id);
      if (!node) return;
      mode = "workflow";
      const rect = body.querySelector(".fs-stage")?.getBoundingClientRect();
      const box = geometry(node);
      if (rect?.width) {
        originX = rect.width / 2 - (box.x + box.width / 2) * scale;
        originY = rect.height / 2 - (box.y + box.height / 2) * scale;
      }
      fitPending = false;
      selectNode(id);
    }

    function paint() {
      if (layerContext !== context || layer?.dataset.view !== "process") return;
      pauseMedia(body, true);
      for (const [value, control] of modeButtons) control.setAttribute("aria-pressed", String(mode === value));
      directory.setAttribute("aria-expanded", String(directoryOpen));
      body.replaceChildren();
      if (directoryOpen) body.append(outline());
      body.append(mode === "board" ? storyboard() : mode === "assets" ? assets() : canvas());
      if (inspectorOpen && byId.has(selected)) body.append(inspector(byId.get(selected)));
    }

    function outline() {
      const aside = el("aside", "fs-outline");
      aside.setAttribute("aria-label", "节点目录");
      const header = el("header");
      header.append(el("strong", "", data.name || card.name || "制作过程"), button("关闭目录", () => { directoryOpen = false; paint(); directory.focus(); }, "fs-directory-close"));
      const search = el("input");
      search.placeholder = "搜索节点";
      search.setAttribute("aria-label", "搜索节点");
      const filter = el("select");
      filter.setAttribute("aria-label", "筛选节点类型");
      for (const [value, label] of [["", "全部类型"], ["image", "图片"], ["video", "视频"], ["audio", "音频"], ["group", "分组"]]) {
        const option = el("option", "", label);
        option.value = value;
        filter.append(option);
      }
      header.append(search, filter);
      aside.append(header);
      const tree = el("div", "fs-tree");
      aside.append(tree);
      function refill() {
        const needle = search.value.trim().toLowerCase(), kind = filter.value;
        const matches = node => (!kind || node.type === kind) && (!needle || String(node.name || node.id).toLowerCase().includes(needle));
        const used = new Set();
        tree.replaceChildren();
        function jump(node) {
          const control = button(node.name || node.id, () => { directoryOpen = false; focusNode(node.id); }, "fs-jump");
          control.dataset.nodeId = String(node.id);
          control.setAttribute("aria-current", String(selected === node.id));
          return control;
        }
        for (const group of nodes.filter(node => node.type === "group")) {
          const children = (group.childIds || []).map(id => byId.get(id)).filter(Boolean);
          if (![group, ...children].some(matches)) continue;
          const details = el("details");
          details.open = true;
          details.append(el("summary", "", group.name || "分组"));
          if (matches(group)) details.append(jump(group));
          for (const child of children) if (child.type !== "group" && matches(child)) { details.append(jump(child)); used.add(child.id); }
          tree.append(details);
          used.add(group.id);
        }
        for (const node of nodes) if (!used.has(node.id) && matches(node)) tree.append(jump(node));
        if (!tree.childElementCount) tree.append(el("p", "", "没有匹配的节点。"));
      }
      search.addEventListener("input", refill);
      filter.addEventListener("change", refill);
      refill();
      return aside;
    }

    function canvas() {
      const stage = el("div", "fs-stage");
      stage.setAttribute("aria-label", "只读工作流画布");
      const world = el("div", "fs-world");
      const ordered = [...nodes.filter(node => node.type === "group"), ...nodes.filter(node => node.type !== "group")];
      if (showEdges && nodes.length) {
        const edges = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        edges.setAttribute("class", "fs-edges");
        for (const edge of process.edges || []) {
          const source = byId.get(edge.source), target = byId.get(edge.target);
          if (!source || !target) continue;
          const a = geometry(source), b = geometry(target);
          const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
          line.setAttribute("x1", a.x + a.width);
          line.setAttribute("y1", a.y + a.height / 2);
          line.setAttribute("x2", b.x);
          line.setAttribute("y2", b.y + b.height / 2);
          edges.append(line);
        }
        world.append(edges);
      }
      for (const node of ordered) {
        const box = geometry(node);
        const block = button("", event => { event.stopPropagation(); selectNode(node.id); }, "fs-node" + (node.type === "group" ? " group" : ""));
        block.style.left = box.x + "px";
        block.style.top = box.y + "px";
        block.style.width = box.width + "px";
        block.style.height = box.height + "px";
        if (node.groupColor) block.style.borderColor = node.groupColor;
        block.dataset.nodeId = String(node.id);
        block.setAttribute("aria-current", String(selected === node.id));
        block.setAttribute("aria-label", node.name || node.type || "节点");
        block.append(el("div", "fs-node-name", node.name || ACTION[node.action] || node.type));
        if (node.type !== "group") block.append(preview(node));
        world.append(block);
      }
      world.style.transform = `translate(${originX}px, ${originY}px) scale(${scale})`;
      stage.append(world);
      if (!nodes.length) stage.append(el("p", "fs-canvas-empty", "这个作品的画布没有节点。"));
      const controls = el("div", "fs-controls");
      const zoomLabel = el("span", "fs-zoom", `${Math.round(scale * 100)}%`);
      function applyScale(next) {
        const rect = stage.getBoundingClientRect();
        const previous = scale;
        scale = Math.min(1.6, Math.max(0.02, next));
        originX = rect.width / 2 - (rect.width / 2 - originX) * scale / previous;
        originY = rect.height / 2 - (rect.height / 2 - originY) * scale / previous;
        fitPending = false;
        world.style.transform = `translate(${originX}px, ${originY}px) scale(${scale})`;
        zoomLabel.textContent = `${Math.round(scale * 100)}%`;
      }
      controls.append(button("适应画布", () => { fit(stage); zoomLabel.textContent = `${Math.round(scale * 100)}%`; }), button(showEdges ? "隐藏节点连线" : "显示节点连线", () => { showEdges = !showEdges; paint(); }), button("−", () => applyScale(scale / 1.25)), zoomLabel, button("+", () => applyScale(scale * 1.25)));
      controls.querySelectorAll("button")[2].setAttribute("aria-label", "缩小画布");
      controls.querySelectorAll("button")[3].setAttribute("aria-label", "放大画布");
      stage.append(controls);
      stage.addEventListener("pointerdown", event => {
        if (event.target !== stage && event.target !== world) return;
        const startX = event.clientX, startY = event.clientY, ox = originX, oy = originY;
        stage.setPointerCapture?.(event.pointerId);
        function move(next) {
          originX = ox + next.clientX - startX;
          originY = oy + next.clientY - startY;
          fitPending = false;
          world.style.transform = `translate(${originX}px, ${originY}px) scale(${scale})`;
        }
        function up() {
          stage.removeEventListener("pointermove", move);
          stage.removeEventListener("pointerup", up);
          stage.removeEventListener("pointercancel", up);
        }
        stage.addEventListener("pointermove", move);
        stage.addEventListener("pointerup", up);
        stage.addEventListener("pointercancel", up);
      });
      stage.addEventListener("wheel", event => { event.preventDefault(); applyScale(scale * (event.deltaY > 0 ? 0.9 : 1.1)); }, {passive: false});
      if (fitPending) requestAnimationFrame(() => {
        if (layerContext === context && layer?.contains(stage) && layer.dataset.view === "process" && body.querySelector(".fs-stage") === stage && fitPending) {
          fit(stage);
          zoomLabel.textContent = `${Math.round(scale * 100)}%`;
        }
      });
      return stage;
    }

    function fit(stage) {
      if (!nodes.length) return;
      const boxes = nodes.map(geometry);
      const minX = Math.min(...boxes.map(box => box.x)), minY = Math.min(...boxes.map(box => box.y));
      const maxX = Math.max(...boxes.map(box => box.x + box.width)), maxY = Math.max(...boxes.map(box => box.y + box.height));
      const rect = stage.getBoundingClientRect();
      scale = Math.min(1, Math.max(0.02, Math.min(Math.max(1, rect.width - 48) / Math.max(1, maxX - minX), Math.max(1, rect.height - 48) / Math.max(1, maxY - minY))));
      originX = (rect.width - (maxX - minX) * scale) / 2 - minX * scale;
      originY = (rect.height - (maxY - minY) * scale) / 2 - minY * scale;
      fitPending = false;
      const world = stage.querySelector(".fs-world");
      if (world) world.style.transform = `translate(${originX}px, ${originY}px) scale(${scale})`;
    }

    function tile(node) {
      const control = button("", () => selectNode(node.id), "fs-media-tile");
      control.dataset.nodeId = String(node.id);
      control.setAttribute("aria-label", "查看节点 " + (node.name || node.id));
      control.setAttribute("aria-current", String(selected === node.id));
      control.append(preview(node), el("span", "fs-tile-name", node.name || node.id));
      return control;
    }

    function storyboard() {
      const board = el("div", "fs-board");
      const used = new Set();
      function section(title, list) {
        const videos = list.filter(node => node.type === "video" && !used.has(node.id));
        if (!videos.length) return;
        const block = el("section");
        block.append(el("h3", "", `${title} · ${videos.length}`));
        const grid = el("div", "fs-shots");
        for (const node of videos) { used.add(node.id); grid.append(tile(node)); }
        block.append(grid);
        board.append(block);
      }
      for (const group of nodes.filter(node => node.type === "group")) section(group.name || "分组", (group.childIds || []).map(id => byId.get(id)).filter(Boolean));
      section("未分组", nodes);
      if (!counts.video) board.append(el("p", "", "这个作品没有视频节点。"));
      return board;
    }

    function assets() {
      const panel = el("div", "fs-assets");
      const tabs = el("div", "fs-asset-tabs");
      for (const [kind, label] of [["audio", "音频"], ["image", "图片"], ["video", "视频"]]) {
        const control = button(`${label}（${counts[kind]}）`, () => { assetKind = kind; paint(); });
        control.setAttribute("aria-pressed", String(assetKind === kind));
        tabs.append(control);
      }
      const grid = el("div", "fs-shots");
      for (const node of nodes.filter(node => node.type === assetKind)) grid.append(tile(node));
      if (!counts[assetKind]) grid.append(el("p", "", "这个作品没有这类素材节点。"));
      panel.append(tabs, grid);
      return panel;
    }

    function metadata(title, value, open = false) {
      const details = el("details", "fs-metadata");
      details.open = open;
      details.append(el("summary", "", title), el("pre", "", JSON.stringify(value, null, 2)));
      return details;
    }

    function inspector(node) {
      const aside = el("aside", "fs-inspector");
      aside.setAttribute("aria-label", "节点详情");
      const header = el("header", "fs-inspector-head");
      header.append(el("h3", "", node.name || "节点"), button("关闭详情", closeInspector, "fs-detail-close"));
      aside.append(header, el("p", "", (ACTION[node.action] || node.type || "节点") + " · " + mediaLabel(node)));
      aside.append(button("定位到画布", () => focusNode(node.id), "fs-locate"));
      if (node.model) aside.append(el("p", "", "模型 " + node.model + (node.modeType ? " · " + node.modeType : "")));
      if (node.taskStatus != null) aside.append(el("p", "", node.taskStatus === 2 ? "生成状态 已完成" : "生成状态 " + node.taskStatus));
      if (node.prompt) aside.append(el("p", "fs-prompt", node.prompt));
      aside.append(metadata("完整生成参数", node.params ?? node.settings ?? {}, true));
      if (node.refs?.length) {
        aside.append(el("h4", "", "引用顺序"));
        const list = el("ol", "fs-refs");
        const refs = node.refs.map((ref, index) => ({ref, index})).sort((a, b) => (Number.isFinite(a.ref.order) ? a.ref.order : a.index) - (Number.isFinite(b.ref.order) ? b.ref.order : b.index));
        for (const {ref} of refs) {
          const item = el("li");
          const label = `${ref.label || ref.nodeId || "引用"} · ${ref.kind || "引用"}${ref.index != null ? ` · 位置 ${ref.index}` : ""}`;
          const jump = button(label, () => focusNode(ref.nodeId));
          jump.disabled = !byId.has(ref.nodeId);
          item.append(jump);
          if (jump.disabled) item.append(el("span", "", "引用节点不在当前快照中"));
          list.append(item);
        }
        aside.append(list);
      }
      const outputs = outputsFor(node);
      if (["audio", "image", "video"].includes(node.type)) {
        aside.append(el("h4", "", `输出（${outputs.length}）`));
        if (!outputs.length) aside.append(el("p", "", node.mediaStatus === "empty" ? "这个节点没有输出。" : "尚无本地输出，等待缓存。"));
      }
      for (const [position, output] of outputs.entries()) {
        const block = el("section", "fs-output");
        const url = localURL(output.url);
        block.append(el("h4", "", `输出 ${output.index ?? position}${url ? " · 已缓存" : output.status === "empty" ? " · 没有输出" : ["failed", "error"].includes(output.status) ? " · 缓存失败" : " · 待缓存"}`));
        const meta = {...(node.resourceMeta || {}), ...(output.metadata || {})};
        const dimensions = meta.width && meta.height ? `${meta.width} × ${meta.height}` : "";
        const duration = meta.duration != null ? `时长 ${meta.duration}` : meta.durationMs != null ? `时长 ${meta.durationMs} ms` : "";
        if (dimensions || duration) block.append(el("p", "", [dimensions, duration].filter(Boolean).join(" · ")));
        if (url && node.type === "image") {
          const image = el("img", "fs-output-image");
          image.src = url;
          image.alt = node.name || "图片输出";
          image.loading = "lazy";
          block.append(image);
        } else if (url && ["audio", "video"].includes(node.type)) {
          const slot = el("div", "fs-player-slot");
          const play = button(node.type === "audio" ? "播放音频" : "播放视频", () => {
            pauseMedia(aside);
            const media = el(node.type, "fs-output-player");
            media.controls = true;
            media.preload = "none";
            media.src = url;
            if (node.type === "video" && localURL(node.poster)) media.poster = localURL(node.poster);
            media.addEventListener("error", () => { notice("这个本地媒体无法播放，请检查缓存文件。"); });
            // The player is created only after this user action. Its native controls own later clicks.
            slot.replaceChildren(media);
            media.play?.()?.catch?.(() => {});
          }, "fs-play-output");
          play.setAttribute("aria-label", node.type === "audio" ? "播放音频" : "播放视频");
          if (node.type === "video" && localURL(node.poster)) play.prepend(preview(node));
          slot.append(play);
          block.append(slot);
        } else if (!url) block.append(el("p", "", output.status === "empty" ? "没有媒体输出。" : "本机尚未缓存这个输出。"));
        block.append(metadata("输出元数据", {mediaId: output.mediaId, ...meta}));
        aside.append(block);
      }
      const supported = ["group", "audio", "image", "video"].includes(node.type);
      if (!supported) aside.append(el("p", "fs-unsupported", "此节点类型暂不支持专用预览，可查看以下只读元数据。"));
      aside.append(metadata(supported ? "完整节点元数据" : "节点元数据", node, !supported));
      return aside;
    }

    paint();
    modeButtons.get(mode).focus?.({preventScroll: true});
  }

  return {load, suspend};
}
