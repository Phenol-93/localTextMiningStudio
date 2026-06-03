(function () {
  let graphData = { nodes: [], edges: [], filters: {}, meta: {} };
  let cy = null;
  let selectedNodeId = "";

  const elements = {
    search: document.getElementById("searchInput"),
    relation: document.getElementById("relationFilter"),
    type: document.getElementById("typeFilter"),
    status: document.getElementById("statusFilter"),
    topN: document.getElementById("topNInput"),
    hopMode: document.getElementById("hopMode"),
    reset: document.getElementById("resetButton"),
    summary: document.getElementById("summary"),
    details: document.getElementById("detailsBody"),
  };

  window.loadGraphData = function (data) {
    graphData = data || graphData;
    elements.topN.value = String(graphData.meta && graphData.meta.default_top_n ? graphData.meta.default_top_n : 50);
    populateFilters();
    render();
  };

  function populateFilters() {
    fillSelect(elements.relation, "全部关系", graphData.filters.relations || []);
    fillSelect(elements.type, "全部实体类型", graphData.filters.entity_types || []);
    fillSelect(elements.status, "全部状态", graphData.filters.statuses || []);
  }

  function fillSelect(select, label, values) {
    select.innerHTML = "";
    const all = document.createElement("option");
    all.value = "";
    all.textContent = label;
    select.appendChild(all);
    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });
  }

  function render() {
    const payload = filteredElements();
    if (!cy) {
      cy = cytoscape({
        container: document.getElementById("cy"),
        elements: payload,
        layout: { name: "cose", animate: false, fit: true, padding: 36 },
        style: [
          {
            selector: "node",
            style: {
              "background-color": "#4f7cac",
              label: "data(label)",
              color: "#1f2937",
              "font-size": 11,
              "text-valign": "bottom",
              "text-margin-y": 6,
              width: "mapData(source_count, 1, 20, 24, 54)",
              height: "mapData(source_count, 1, 20, 24, 54)",
            },
          },
          {
            selector: "edge",
            style: {
              width: "mapData(weight, 1, 10, 1, 6)",
              "line-color": "#9aa7b9",
              "target-arrow-color": "#9aa7b9",
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              label: "data(label)",
              "font-size": 10,
              "text-background-color": "#ffffff",
              "text-background-opacity": 0.85,
              "text-background-padding": 2,
            },
          },
          {
            selector: ":selected",
            style: {
              "background-color": "#d45d79",
              "line-color": "#d45d79",
              "target-arrow-color": "#d45d79",
            },
          },
        ],
      });
      cy.on("tap", "node", (event) => {
        selectedNodeId = event.target.id();
        elements.hopMode.value = "one";
        showNodeDetails(event.target);
        render();
      });
      cy.on("tap", "edge", (event) => showEdgeDetails(event.target));
    } else {
      cy.elements().remove();
      cy.add(payload);
      cy.layout({ name: "cose", animate: false, fit: true, padding: 36 }).run();
    }
    updateSummary(payload);
  }

  function filteredElements() {
    const search = elements.search.value.trim().toLowerCase();
    const relation = elements.relation.value;
    const entityType = elements.type.value;
    const status = elements.status.value;
    const topN = Math.max(1, parseInt(elements.topN.value || "50", 10));
    const mode = elements.hopMode.value;

    let nodes = graphData.nodes.slice();
    if (search) {
      nodes = nodes.filter((node) => node.data.label.toLowerCase().includes(search) || node.data.id.toLowerCase().includes(search));
    }
    if (entityType) {
      nodes = nodes.filter((node) => node.data.type === entityType);
    }

    const topIds = new Set(graphData.nodes.slice(0, topN).map((node) => node.data.id));
    let visibleIds = new Set(nodes.map((node) => node.data.id));
    if (mode === "top") {
      visibleIds = intersection(visibleIds, topIds);
    } else if (selectedNodeId) {
      visibleIds = hopIds(selectedNodeId, mode === "two" ? 2 : 1);
      visibleIds = intersection(visibleIds, new Set(nodes.map((node) => node.data.id)));
    }

    let edges = graphData.edges.filter((edge) => visibleIds.has(edge.data.source) && visibleIds.has(edge.data.target));
    if (relation) {
      edges = edges.filter((edge) => edge.data.relation === relation);
    }
    if (status) {
      edges = edges.filter((edge) => (edge.data.statuses || []).includes(status));
    }

    const edgeNodeIds = new Set();
    edges.forEach((edge) => {
      edgeNodeIds.add(edge.data.source);
      edgeNodeIds.add(edge.data.target);
    });
    const finalNodes = graphData.nodes.filter((node) => visibleIds.has(node.data.id) && (edgeNodeIds.size === 0 || edgeNodeIds.has(node.data.id)));
    return finalNodes.concat(edges);
  }

  function hopIds(startId, depth) {
    const result = new Set([startId]);
    let frontier = new Set([startId]);
    for (let i = 0; i < depth; i += 1) {
      const next = new Set();
      graphData.edges.forEach((edge) => {
        if (frontier.has(edge.data.source)) next.add(edge.data.target);
        if (frontier.has(edge.data.target)) next.add(edge.data.source);
      });
      next.forEach((id) => result.add(id));
      frontier = next;
    }
    return result;
  }

  function intersection(left, right) {
    return new Set([...left].filter((value) => right.has(value)));
  }

  function showNodeDetails(node) {
    const data = node.data();
    elements.details.innerHTML = [
      row("节点", data.label),
      row("类型", data.type || ""),
      row("来源次数", data.source_count),
      row("Degree", data.degree),
      row("InDegree", data.in_degree),
      row("OutDegree", data.out_degree),
    ].join("");
  }

  function showEdgeDetails(edge) {
    const data = edge.data();
    elements.details.innerHTML = [
      row("关系", data.relation),
      row("权重", data.weight),
      row("状态", data.status),
      row("置信度", data.confidence),
      row("来源文档", data.source_doc),
      row("证据", data.evidence),
    ].join("");
  }

  function row(label, value) {
    return `<div class="detail-row"><div class="detail-label">${escapeHtml(label)}</div><div class="detail-value">${escapeHtml(String(value || ""))}</div></div>`;
  }

  function updateSummary(payload) {
    const nodeCount = payload.filter((item) => !item.data.source).length;
    const edgeCount = payload.filter((item) => item.data.source).length;
    const meta = graphData.meta || {};
    elements.summary.innerHTML = [
      pill(`显示节点 ${nodeCount}`),
      pill(`显示边 ${edgeCount}`),
      pill(`全图节点 ${meta.node_count || 0}`),
      pill(`全图边 ${meta.edge_count || 0}`),
      meta.truncated ? pill("已截断") : "",
    ].join("");
  }

  function pill(text) {
    return `<span class="summary-pill">${escapeHtml(text)}</span>`;
  }

  function escapeHtml(value) {
    return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }

  [elements.search, elements.relation, elements.type, elements.status, elements.topN, elements.hopMode].forEach((element) => {
    element.addEventListener("input", render);
    element.addEventListener("change", render);
  });
  elements.reset.addEventListener("click", () => {
    selectedNodeId = "";
    elements.search.value = "";
    elements.relation.value = "";
    elements.type.value = "";
    elements.status.value = "";
    elements.hopMode.value = "top";
    render();
  });

  if (window.__GRAPH_DATA__) {
    window.loadGraphData(window.__GRAPH_DATA__);
  }
})();
