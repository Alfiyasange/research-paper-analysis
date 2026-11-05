
"use strict";

const $ = (selector) => document.querySelector(selector);

let cy = null;
let graphLoaded = false;
let papersCache = [];
let summaryRequestNumber = 0;

/* =========================================
   API HELPERS
========================================= */

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();

  let data;

  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(
      `Server returned an invalid response (${response.status}).`
    );
  }

  if (!response.ok) {
    throw new Error(
      data.error ||
      data.message ||
      `Request failed: ${response.status}`
    );
  }

  return data;
}

function post(url, body) {
  return api(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

function showError(element, error) {
  if (element) {
    element.textContent = `Error: ${error.message || error}`;
  }
}

function setText(selector, value) {
  const element = $(selector);

  if (element) {
    element.textContent = value;
  }
}
/* =========================================
   THEME: LIGHT AND DARK MODE
========================================= */

const themeToggle = $("#themeToggle");

function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;

    if (themeToggle) {
        themeToggle.textContent =
            theme === "dark" ? "☀️ Light Mode" : "🌙 Dark Mode";

        themeToggle.setAttribute(
            "aria-label",
            theme === "dark"
                ? "Switch to light mode"
                : "Switch to dark mode"
        );
    }

    // Refresh graph colors if the graph is loaded.
    if (cy) {
        updateGraphTheme();
    }
}

let savedTheme = "light";

try {
    savedTheme =
        localStorage.getItem("papergraph-theme") || "light";
} catch (error) {
    console.warn("Could not read saved theme.", error);
}

applyTheme(savedTheme);

if (themeToggle) {
    themeToggle.addEventListener("click", () => {
        const currentTheme =
            document.documentElement.dataset.theme || "light";

        const nextTheme =
            currentTheme === "dark" ? "light" : "dark";

        applyTheme(nextTheme);

        try {
            localStorage.setItem("papergraph-theme", nextTheme);
        } catch (error) {
            console.warn("Could not save theme preference.", error);
        }
    });
}

/* =========================================
   NAVIGATION LABEL
========================================= */

const pageNames = {
  "t-papers": "Research Library",
  "t-chat": "Ask Research",
  "t-graph": "Knowledge Graph",
  "t-compare": "Compare Papers"
};

document.querySelectorAll('[data-bs-toggle="pill"]').forEach((tab) => {
  tab.addEventListener("shown.bs.tab", (event) => {
    const target = event.target.getAttribute("data-bs-target");
    setText("#currentPage", pageNames[target?.replace("#", "")] || "Workspace");
  });
});

/* =========================================
   PAPER LIBRARY
========================================= */

function setOptions(select, papers, placeholder) {
  if (!select) return;

  const previousValue = select.value;

  select.innerHTML =
    `<option value="">${escapeHTML(placeholder)}</option>` +
    papers.map((paper) => `
      <option value="${escapeHTML(paper.id)}">
        ${escapeHTML(
          String(paper.title || "Untitled paper").slice(0, 100)
        )}
      </option>
    `).join("");

  if (papers.some((paper) => String(paper.id) === previousValue)) {
    select.value = previousValue;
  }
}

async function loadPapers() {
  const list = $("#paperList");

  if (!list) return;

  list.textContent = "Loading papers...";

  try {
    const result = await api("/api/papers");

    if (!Array.isArray(result)) {
      throw new Error("The papers API did not return a list.");
    }

    papersCache = result;

    if (result.length === 0) {
      list.innerHTML = `
        <div class="empty-state">
          No papers yet. Upload PDF files to begin.
        </div>
      `;
    } else {
      list.innerHTML = result.map((paper) => `
   <div class="list-group-item">
  <div>
    <strong>${escapeHTML(paper.title || "Untitled paper")}</strong>
    <small class="d-block text-muted">
      ${escapeHTML(paper.filename || "Unknown filename")}
    </small>
  </div><div class="d-flex gap-2">
  <button
    type="button"
    class="btn btn-outline-secondary summarize-btn"
    data-id="${escapeHTML(paper.id)}">
    Summarize
  </button>

  <button
    type="button"
    class="btn btn-outline-danger delete-paper-btn"
    data-id="${escapeHTML(paper.id)}">
    Delete
  </button>
</div>
        </div>
      `).join("");
    }

    setOptions($("#pa"), result, "Select first paper");
    setOptions($("#pb"), result, "Select second paper");

    const scope = $("#scope");

    if (scope) {
      const previousScope = scope.value;

      scope.innerHTML =
        '<option value="">All papers</option>' +
        result.map((paper) => `
          <option value="${escapeHTML(paper.id)}">
            ${escapeHTML(
              String(paper.title || "Untitled paper").slice(0, 100)
            )}
          </option>
        `).join("");

      if (result.some(
        (paper) => String(paper.id) === previousScope
      )) {
        scope.value = previousScope;
      }
    }

  } catch (error) {
    showError(list, error);
  }
}

/* =========================================
   PAPER SUMMARIES
   The result is displayed in the main workspace.
========================================= */

const paperList = $("#paperList");

if (paperList) {
  paperList.addEventListener("click", async (event) => {
    const button = event.target.closest(".summarize-btn");

    if (!button) return;

    const id = button.dataset.id;
    const output = $("#summary");
    const panel = $("#summaryPanel");
    const hint = $("#summaryHint");
    const title = $("#summaryTitle");

    if (!output || !panel) {
      console.error("Summary section is missing from index.html.");
      return;
    }

    const requestNumber = ++summaryRequestNumber;
    const oldText = button.textContent;

    button.disabled = true;
    button.textContent = "Summarizing...";

    output.textContent = "Generating summary. Please wait...";

    if (title) {
      title.textContent = "Paper summary";
    }

    if (hint) {
      const selectedPaper = papersCache.find(
        (paper) => String(paper.id) === String(id)
      );

      hint.textContent = selectedPaper
        ? `Generating a summary for ${selectedPaper.title || "your paper"}.`
        : "Your paper is being summarized.";
    }

    // Scroll the main page to the large summary panel.
    panel.scrollIntoView({
      behavior: "smooth",
      block: "start"
    });

    try {
      const result = await api(
        `/api/summarize/${encodeURIComponent(id)}`
      );

      // Prevent an older request from overwriting a newer summary.
      if (requestNumber !== summaryRequestNumber) return;

      output.textContent =
        result.summary ?? "No summary was returned.";

      if (hint) {
        hint.textContent = "Summary generated successfully.";
      }
    } catch (error) {
      if (requestNumber !== summaryRequestNumber) return;

      showError(output, error);

      if (hint) {
        hint.textContent = "Summary generation failed.";
      }
    } finally {
      button.disabled = false;
      button.textContent = oldText || "Summarize";
    }
  });
}
// Delete a research paper
if (paperList) {
  paperList.addEventListener("click", async (event) => {
    const button = event.target.closest(".delete-paper-btn");

    if (!button) return;

    const paperId = button.dataset.id;

    const confirmed = confirm(
      "Are you sure you want to delete this research paper? This cannot be undone."
    );

    if (!confirmed) return;

    button.disabled = true;
    button.textContent = "Deleting...";

    try {
      await api(`/api/papers/${encodeURIComponent(paperId)}`, {
        method: "DELETE"
      });

      await loadPapers();
      graphLoaded = false;

      alert("Research paper deleted successfully!");
    } catch (error) {
      alert("Could not delete paper: " + error.message);
      button.disabled = false;
      button.textContent = "Delete";
    }
  });
}
/* =========================================
   UPLOAD PDF FILES
========================================= */

const uploadForm = $("#upForm");

if (uploadForm) {
  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const form = event.currentTarget;
    const fileInput = form.querySelector('input[type="file"]');
    const button = form.querySelector('button[type="submit"]');
    const status = $("#uploadStatus");

    if (!fileInput || !fileInput.files.length) {
      if (status) {
        status.textContent = "Please select at least one PDF file.";
      }
      return;
    }

    const selectedFiles = Array.from(fileInput.files);

    const invalidFile = selectedFiles.find(
      (file) => !file.name.toLowerCase().endsWith(".pdf")
    );

    if (invalidFile) {
      if (status) {
        status.textContent = "Please select PDF files only.";
      }
      return;
    }

    const oldText = button?.textContent || "Upload papers";

    if (button) {
      button.disabled = true;
      button.textContent = "Uploading...";
    }

    if (status) {
      status.textContent = "Uploading and indexing your papers...";
    }

    try {
      await api("/api/upload", {
        method: "POST",
        body: new FormData(form)
      });

      form.reset();

      await loadPapers();
      graphLoaded = false;

      if (status) {
        status.textContent =
          "Upload completed. Your research library has been refreshed.";
      }

      const output = $("#summary");
      const hint = $("#summaryHint");

      if (output) {
        output.textContent =
          "Your papers have been uploaded. Select Summarize next to a paper to display its summary here.";
      }

      if (hint) {
        hint.textContent =
          "Select Summarize on a paper to view its key ideas.";
      }
    } catch (error) {
      if (status) {
        status.textContent = `Upload failed: ${error.message}`;
      }
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = oldText;
      }
    }
  });
}

/* =========================================
   ASK RESEARCH
========================================= */

async function sendQuestion() {
  const input = $("#q");
  const chat = $("#chat");

  if (!input || !chat) return;

  const question = input.value.trim();

  if (!question) return;

  const button = $("#send");

  if (button) {
    button.disabled = true;
  }

  // Display the user's question safely.
  const userMessage = document.createElement("div");
  userMessage.className = "msg";

  const userLabel = document.createElement("b");
  userLabel.textContent = "You: ";

  userMessage.append(
    userLabel,
    document.createTextNode(question)
  );

  chat.appendChild(userMessage);

  // Display a temporary answer.
  const answerMessage = document.createElement("div");
  answerMessage.className = "msg";
  answerMessage.textContent = "Assistant: Thinking...";

  chat.appendChild(answerMessage);

  input.value = "";
  chat.scrollTop = chat.scrollHeight;

  try {
    const scope = $("#scope")?.value || "";

    const result = await post("/api/ask", {
      question,
      mode: $("#mode")?.value || "qa",
      paper_ids: scope ? [scope] : []
    });

    answerMessage.replaceChildren();

    const label = document.createElement("b");
    label.textContent = "Assistant: ";

    answerMessage.appendChild(label);
    answerMessage.appendChild(
      document.createTextNode(
        result.answer ?? result.response ?? "No answer was returned."
      )
    );

    if (Array.isArray(result.sources) && result.sources.length) {
      const sources = document.createElement("div");
      sources.className = "src";

      sources.textContent = "Sources: " + result.sources.map((source) => {
        const paper = source.paper ?? source.title ?? "Unknown paper";
        const page = source.page != null ? ` p.${source.page}` : "";

        return `${paper}${page}`;
      }).join("; ");

      answerMessage.appendChild(sources);
    }
  } catch (error) {
    answerMessage.textContent = `Error: ${error.message}`;
  } finally {
    if (button) {
      button.disabled = false;
    }

    chat.scrollTop = chat.scrollHeight;
    input.focus();
  }
}

const sendButton = $("#send");

if (sendButton) {
  sendButton.addEventListener("click", sendQuestion);
}

const questionInput = $("#q");

if (questionInput) {
  questionInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendQuestion();
    }
  });
}

/* =========================================
   COMPARE PAPERS
========================================= */

const compareButton = $("#cmp");

if (compareButton) {
  compareButton.addEventListener("click", async () => {
    const a = $("#pa")?.value;
    const b = $("#pb")?.value;
    const output = $("#cmpOut");
    const shared = $("#shared");

    if (!a || !b) {
      if (output) {
        output.textContent = "Please select both papers.";
      }
      return;
    }

    if (a === b) {
      if (output) {
        output.textContent = "Please select two different papers.";
      }
      return;
    }

    compareButton.disabled = true;

    if (output) {
      output.textContent = "Comparing papers...";
    }

    if (shared) {
      shared.textContent = "Finding shared concepts...";
    }

    try {
      const result = await post("/api/compare", {
        a,
        b,
        aspect: $("#aspect")?.value.trim() ||
          "main methods and findings"
      });

      if (output) {
        output.textContent =
          result.comparison ??
          result.answer ??
          "No comparison was returned.";
      }

      const concepts = Array.isArray(result.shared_concepts)
        ? result.shared_concepts
        : [];

      if (shared) {
        shared.textContent = concepts.length
          ? "Shared concepts: " + concepts.join(", ")
          : "Shared concepts: none reported.";
      }
    } catch (error) {
      showError(output, error);

      if (shared) {
        shared.textContent = "Could not retrieve shared concepts.";
      }
    } finally {
      compareButton.disabled = false;
    }
  });
}
/* =========================================
   KNOWLEDGE GRAPH
========================================= */

function graphIsDark() {
  return document.documentElement.dataset.theme === "dark";
}

function updateGraphTheme() {
  if (!cy) return;

  const dark = graphIsDark();

  cy.style()
    .selector("node")
    .style({
      "background-color": dark ? "#d5a94f" : "#e2ad53",
      color: dark ? "#17191e" : "#242832",
      "text-outline-color": dark ? "#202329" : "#ffffff",
      "text-outline-width": 1
    })
    .selector("node[type='paper']")
    .style({
      "background-color": dark ? "#7188f0" : "#4057a8",
      color: "#ffffff",
      "text-outline-color": dark ? "#35406e" : "#4057a8"
    })
    .selector("edge")
    .style({
      "line-color": dark ? "#626b7b" : "#c5cad3",
      "target-arrow-color": dark ? "#626b7b" : "#c5cad3"
    })
    .selector(".graph-dimmed")
    .style({
      opacity: 0.15
    })
    .selector(".graph-highlight")
    .style({
      opacity: 1,
      "border-width": 4,
      "border-color": dark ? "#b9f36b" : "#4d7c0f"
    })
    .selector("edge.graph-edge-highlight")
    .style({
      opacity: 1,
      width: 3,
      "line-color": dark ? "#b9f36b" : "#4d7c0f"
    })
    .update();
}

function updateGraphStats() {
  if (!cy) return;

  const nodes = cy.nodes();

  const papers = nodes.filter((node) =>
    node.data("type") === "paper"
  );

  const concepts = nodes.filter((node) =>
    node.data("type") !== "paper"
  );

  setText("#graphNodeCount", String(nodes.length));
  setText("#graphEdgeCount", String(cy.edges().length));
  setText("#graphPaperCount", String(papers.length));
  setText("#graphConceptCount", String(concepts.length));
}

function clearGraphHighlight() {
  if (!cy) return;

  cy.elements().removeClass(
    "graph-dimmed graph-highlight graph-edge-highlight"
  );
}

function showGraphNodeDetails(node) {
  const output = $("#graphNodeDetails");

  if (!output || !node || node.empty()) return;

  const connectedNodes = node.neighborhood("node");

  const title = node.data("label") || node.id();
  const type = node.data("type") || "concept";

  output.replaceChildren();

  function addDetail(label, value) {
    const item = document.createElement("div");
    item.className = "graph-detail-item";

    const caption = document.createElement("span");
    caption.textContent = label;

    const valueElement = document.createElement("strong");
    valueElement.textContent = String(value);

    item.append(caption, valueElement);
    output.appendChild(item);
  }

  addDetail("Name", title);
  addDetail("Type", type === "paper" ? "Research paper" : "Concept");
  addDetail("Connections", String(node.degree()));

  if (connectedNodes.length) {
    const item = document.createElement("div");
    item.className = "graph-detail-item";

    const caption = document.createElement("span");
    caption.textContent = "Connected nodes";

    const list = document.createElement("ul");
    list.className = "graph-connected-list";

    connectedNodes.forEach((connectedNode) => {
      const li = document.createElement("li");
      li.textContent =
        connectedNode.data("label") || connectedNode.id();
      list.appendChild(li);
    });

    item.append(caption, list);
    output.appendChild(item);
  } else {
    addDetail("Connections", "No connected nodes");
  }
}

function highlightGraphNode(node) {
  if (!cy || !node || node.empty()) return;

  clearGraphHighlight();

  const neighborhood = node.closedNeighborhood();

  cy.elements().addClass("graph-dimmed");
  neighborhood.removeClass("graph-dimmed");
  neighborhood.nodes().addClass("graph-highlight");

  node.connectedEdges().addClass("graph-edge-highlight");

  showGraphNodeDetails(node);
}

function searchGraph() {
  if (!cy) return;

  const input = $("#graphSearch");
  const query = input?.value.trim().toLowerCase() || "";

  clearGraphHighlight();

  if (!query) {
    setText("#graphNodeDetails", "Enter a search term or select a node.");
    return;
  }

  const matches = cy.nodes().filter((node) => {
    const label = String(
      node.data("label") || node.id()
    ).toLowerCase();

    return label.includes(query);
  });

  if (!matches.length) {
    setText("#graphNodeDetails", "No matching nodes found.");
    return;
  }

  cy.elements().addClass("graph-dimmed");

  matches.forEach((node) => {
    node.closedNeighborhood().removeClass("graph-dimmed");
    node.closedNeighborhood().nodes().addClass("graph-highlight");
    node.connectedEdges().addClass("graph-edge-highlight");
  });

  cy.fit(matches, 70);

  if (matches.length === 1) {
    showGraphNodeDetails(matches[0]);
  } else {
    setText(
      "#graphNodeDetails",
      `${matches.length} matching nodes found. Select a node to see its details.`
    );
  }
}

async function loadGraph() {
  const container = $("#cy");

  if (!container) return;

  if (graphLoaded && cy) {
    cy.resize();
    cy.fit(undefined, 30);
    return;
  }

  if (typeof cytoscape === "undefined") {
    container.textContent =
      "Cytoscape could not load. Check your internet connection.";
    return;
  }

  container.textContent = "Loading knowledge graph...";

  try {
    const elements = await api("/api/graph");

    if (!Array.isArray(elements)) {
      throw new Error("The graph API did not return an element list.");
    }

    if (cy) {
      cy.destroy();
      cy = null;
    }

    container.replaceChildren();

    cy = cytoscape({
      container,
      elements,
      layout: {
        name: "cose",
        animate: false,
        padding: 35
      },
      minZoom: 0.15,
      maxZoom: 3,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "font-size": 13,
            "font-family": "DM Sans, sans-serif",
            "text-wrap": "wrap",
            "text-max-width": 135,
            "text-valign": "bottom",
            "text-margin-y": 8,
            "background-color": "#e2ad53",
            color: "#242832",
            "text-outline-color": "#ffffff",
            "text-outline-width": 1,
            width: 38,
            height: 38,
            "border-width": 1,
            "border-color": "#ffffff",
            "min-zoomed-font-size": 9
          }
        },
        {
          selector: "node[type='paper']",
          style: {
            "background-color": "#4057a8",
            color: "#ffffff",
            width: 50,
            height: 50,
            "font-size": 13,
            "font-weight": 700
          }
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#c5cad3",
            "curve-style": "bezier",
            opacity: 0.9
          }
        },
        {
          selector: ":selected",
          style: {
            "border-width": 4,
            "border-color": "#68a6dc"
          }
        },
        {
          selector: ".graph-dimmed",
          style: {
            opacity: 0.15
          }
        },
        {
          selector: ".graph-highlight",
          style: {
            opacity: 1,
            "border-width": 4,
            "border-color": "#4d7c0f"
          }
        },
        {
          selector: "edge.graph-edge-highlight",
          style: {
            opacity: 1,
            width: 3,
            "line-color": "#4d7c0f"
          }
        }
      ]
    });

    cy.on("tap", "node", (event) => {
      const node = event.target;

      highlightGraphNode(node);

      if (node.data("type") === "paper") {
        const id = node.id();

        const matchingPaper = papersCache.find(
          (paper) => String(paper.id) === String(id)
        );

        if (matchingPaper && $("#scope")) {
          $("#scope").value = String(matchingPaper.id);
        }
      }
    });

    cy.on("tap", (event) => {
      if (event.target === cy) {
        clearGraphHighlight();

        const details = $("#graphNodeDetails");
        if (details) {
          details.textContent = "Select a node to inspect its details.";
        }
      }
    });

    updateGraphTheme();
    updateGraphStats();

    graphLoaded = true;
  } catch (error) {
    container.textContent =
      `Could not load graph: ${error.message}`;
  }
}

/* Graph toolbar controls */
$("#graphSearchBtn")?.addEventListener("click", searchGraph);

$("#graphSearch")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    searchGraph();
  }
});

$("#graphZoomIn")?.addEventListener("click", () => {
  if (!cy) return;

  cy.zoom({
    level: Math.min(cy.zoom() * 1.25, cy.maxZoom()),
    renderedPosition: {
      x: cy.width() / 2,
      y: cy.height() / 2
    }
  });
});

$("#graphZoomOut")?.addEventListener("click", () => {
  if (!cy) return;

  cy.zoom({
    level: Math.max(cy.zoom() / 1.25, cy.minZoom()),
    renderedPosition: {
      x: cy.width() / 2,
      y: cy.height() / 2
    }
  });
});

$("#graphFit")?.addEventListener("click", () => {
  if (!cy) return;

  clearGraphHighlight();
  cy.fit(undefined, 35);
});

$("#graphReset")?.addEventListener("click", () => {
  if (!cy) return;

  clearGraphHighlight();

  const search = $("#graphSearch");
  if (search) search.value = "";

  const details = $("#graphNodeDetails");
  if (details) {
    details.textContent = "Select a node to inspect its details.";
  }

  cy.elements().unselect();
  cy.layout({
    name: "cose",
    animate: false,
    padding: 35
  }).run();

  cy.fit(undefined, 35);
});

$("#graphClearSelection")?.addEventListener("click", () => {
  if (!cy) return;

  clearGraphHighlight();
  cy.elements().unselect();

  const details = $("#graphNodeDetails");
  if (details) {
    details.textContent = "Select a node to inspect its details.";
  }
});

const graphTab = $("#graphTab");

if (graphTab) {
  graphTab.addEventListener("shown.bs.tab", loadGraph);
}


/* =========================================
   INITIALIZATION
========================================= */

loadPapers();
// ===============================
// RESEARCH HISTORY
// ===============================

async function loadResearchHistory() {
    const historyList = document.getElementById("historyList");

    if (!historyList) return;

    historyList.textContent = "Loading history...";

    try {
        const response = await fetch("/api/history");

        if (!response.ok) {
            throw new Error("Unable to load history.");
        }

        const history = await response.json();

        historyList.innerHTML = "";

        if (history.length === 0) {
            historyList.textContent = "No research history available yet.";
            return;
        }

     history.forEach(item => {
    const card = document.createElement("div");
    card.className = "history-item";
    card.dataset.type = item.type;

    const heading = document.createElement("h5");
    heading.textContent =
        item.type === "chat" ? "AI Question" :
        item.type === "summary" ? "Paper Summary" :
        item.type === "comparison" ? "Paper Comparison" :
        "Research Activity";

    const title = document.createElement("strong");
    title.textContent = item.title || "Untitled activity";

    const content = document.createElement("p");
    content.textContent = item.content || "No content available.";

    const date = document.createElement("small");
    date.textContent = item.created_at || "";

    card.append(heading, title, content, date);
    historyList.appendChild(card);
});

    } catch (error) {
        historyList.textContent = error.message;
        console.error("History error:", error);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const historyTab = document.querySelector(
        '[data-bs-target="#t-history"]'
    );

    const refreshButton = document.getElementById("refreshHistory");

    if (historyTab) {
        historyTab.addEventListener("shown.bs.tab", loadResearchHistory);
    }

    if (refreshButton) {
        refreshButton.addEventListener("click", loadResearchHistory);
    }
});