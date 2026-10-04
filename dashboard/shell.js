/* Shared shell behaviour: theme, sidebar (mobile drawer + desktop collapse +
   collapsible sections), the topbar filter box, and the sidebar send-count
   badges. Loaded on every page before the page's own script. */
const THEME_KEY = "theraweb-theme";
const COLLAPSE_KEY = "theraweb-sidebar-collapsed";
const SECTION_KEY = "theraweb-sidebar-sections";

function currentEffectiveTheme() {
  let stored = null;
  try { stored = localStorage.getItem(THEME_KEY); } catch (error) { /* private mode etc. */ }
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  document.dispatchEvent(new CustomEvent("themechange", { detail: currentEffectiveTheme() }));
}

function toggleTheme() {
  const next = currentEffectiveTheme() === "dark" ? "light" : "dark";
  try { localStorage.setItem(THEME_KEY, next); } catch (error) { /* private mode etc. */ }
  applyTheme(next);
}

function initSidebar() {
  const menuButton = document.querySelector("#sidebar-menu-button");
  const sidebar = document.querySelector("#sidebar");
  const overlay = document.querySelector("#sidebar-overlay");
  const collapseButton = document.querySelector("#sidebar-collapse");
  if (!sidebar) return;

  function close() {
    document.body.classList.remove("sidebar-open");
    if (menuButton) menuButton.setAttribute("aria-expanded", "false");
    if (overlay) overlay.hidden = true;
  }
  function open() {
    document.body.classList.add("sidebar-open");
    if (menuButton) menuButton.setAttribute("aria-expanded", "true");
    if (overlay) overlay.hidden = false;
  }

  if (menuButton) {
    menuButton.addEventListener("click", () => {
      document.body.classList.contains("sidebar-open") ? close() : open();
    });
  }
  if (overlay) overlay.addEventListener("click", close);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
  sidebar.querySelectorAll("a").forEach((link) => link.addEventListener("click", close));

  // Desktop collapse (icons only), remembered per browser.
  if (collapseButton) {
    collapseButton.addEventListener("click", () => {
      const collapsed = document.body.classList.toggle("sidebar-collapsed");
      collapseButton.setAttribute("aria-expanded", String(!collapsed));
      try { localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0"); } catch (error) { /* ignore */ }
    });
  }

  // Collapsible nav sections.
  let sectionState = {};
  try { sectionState = JSON.parse(localStorage.getItem(SECTION_KEY) || "{}"); } catch (error) { sectionState = {}; }
  sidebar.querySelectorAll(".sidebar-section").forEach((section) => {
    const key = section.dataset.section;
    const label = section.querySelector(".sidebar-section-label");
    if (!label) return;
    if (sectionState[key] === false) {
      section.dataset.open = "false";
      label.setAttribute("aria-expanded", "false");
    }
    label.addEventListener("click", () => {
      const isOpen = section.dataset.open !== "false";
      section.dataset.open = isOpen ? "false" : "true";
      label.setAttribute("aria-expanded", String(!isOpen));
      sectionState[key] = !isOpen;
      try { localStorage.setItem(SECTION_KEY, JSON.stringify(sectionState)); } catch (error) { /* ignore */ }
    });
  });
}

/* Topbar filter: hides any [data-searchable] row on the page whose text
   doesn't contain the query, and any [data-search-group] left empty. */
function initPageSearch() {
  const input = document.querySelector("#page-search");
  if (!input) return;

  function apply() {
    const query = input.value.trim().toLowerCase();
    document.querySelectorAll("[data-searchable]").forEach((row) => {
      row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
    });
    document.querySelectorAll("[data-search-group]").forEach((group) => {
      const rows = group.querySelectorAll("[data-searchable]");
      group.hidden = rows.length > 0 && [...rows].every((row) => row.hidden);
    });
    document.dispatchEvent(new CustomEvent("pagesearch", { detail: query }));
  }

  input.addEventListener("input", apply);
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      input.focus();
      input.select();
    }
  });
  // Re-apply after a page re-renders its list.
  document.addEventListener("listrendered", apply);
}

/* "Sent today" counts in the sidebar, like the Orders badge in the reference. */
async function loadSidebarBadges() {
  try {
    const response = await fetch("/api/sent-today", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    const reports = document.querySelector('[data-badge="reports"]');
    const outreach = document.querySelector('[data-badge="outreach"]');
    if (reports) reports.textContent = data.counts.reports ? String(data.counts.reports) : "";
    if (outreach) outreach.textContent = data.counts.outreach ? String(data.counts.outreach) : "";
  } catch (error) { /* badge is decoration only */ }
  try {
    const response = await fetch("/api/leads/summary", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    const leads = document.querySelector('[data-badge="leads"]');
    if (leads) leads.textContent = data.counts.ready ? data.counts.ready.toLocaleString() : "";
  } catch (error) { /* badge is decoration only */ }
}

(function restoreCollapsedState() {
  try {
    if (localStorage.getItem(COLLAPSE_KEY) === "1") document.body.classList.add("sidebar-collapsed");
  } catch (error) { /* ignore */ }
})();

/* The sidebar's "Owner · host:port" line is static markup in every page
   (leftover from when this only ever ran on localhost). Fill in the real
   address the browser is actually connected to — matters now that this
   can be a remote server reached over Tailscale, not just 127.0.0.1. */
function updateSidebarHost() {
  document.querySelectorAll(".sidebar-user span").forEach((el) => {
    if (/^Owner ·/.test(el.textContent)) el.textContent = `Owner · ${window.location.host}`;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => button.addEventListener("click", toggleTheme));
  initSidebar();
  initPageSearch();
  loadSidebarBadges();
  updateSidebarHost();
});
