const customersList = document.querySelector("#customers-list");
const customersCount = document.querySelector("#customers-count");
const search = document.querySelector("#page-search");
const statClients = document.querySelector("#stat-clients");
const statCount = document.querySelector("#stat-count");
const statCountNote = document.querySelector("#stat-count-note");

let customers = [];

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

function initials(name) {
  return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join("") || "?";
}

function renderStats() {
  Motion.countUp(statCount, customers.length);
  const uniqueEmails = new Set(customers.map((c) => c.email)).size;
  statCountNote.textContent = `${uniqueEmails} unique email${uniqueEmails === 1 ? "" : "es"}`;

  const uniqueClients = new Set(customers.map((c) => c.client)).size;
  Motion.countUp(statClients, uniqueClients);
}

function renderList(filtered) {
  customersCount.textContent = `${filtered.length} of ${customers.length} shown`;

  if (!filtered.length) {
    customersList.innerHTML = '<div class="empty-state">No contacts match your search.</div>';
    return;
  }

  const head = `
    <div class="table-row table-head customer-row">
      <span>Contact</span>
      <span>Email</span>
      <span>Client</span>
      <span>Website</span>
    </div>
  `;

  const rows = filtered.map((c) => `
    <div class="table-row customer-row">
      <span class="row-with-avatar">
        <span class="row-avatar" aria-hidden="true">${escapeHtml(initials(c.contact_name))}</span>
        <span class="ellipsis">${escapeHtml(c.contact_name)}</span>
      </span>
      <span class="muted ellipsis">${escapeHtml(c.email)}</span>
      <span class="muted ellipsis">${escapeHtml(c.client)}</span>
      <span class="ellipsis"><a href="https://${escapeHtml(c.website)}" target="_blank" rel="noreferrer" style="text-decoration:none">${escapeHtml(c.website)}</a></span>
    </div>
  `).join("");

  customersList.innerHTML = head + rows;
  Motion.rows(customersList);
}

function applySearch() {
  const query = search.value.trim().toLowerCase();
  const filtered = query
    ? customers.filter((c) =>
        c.contact_name.toLowerCase().includes(query) ||
        c.email.toLowerCase().includes(query) ||
        c.client.toLowerCase().includes(query) ||
        c.website.toLowerCase().includes(query)
      )
    : customers;
  renderList(filtered);
}

async function loadCustomers() {
  try {
    const response = await fetch("/api/customers", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load customers");
    const data = await response.json();
    customers = (data.customers || []).sort((a, b) => a.client.localeCompare(b.client));
    renderStats();
    applySearch();
  } catch (error) {
    customersList.innerHTML = '<div class="empty-state">Could not load customers. Restart the dashboard and try again.</div>';
    customersCount.textContent = "Unavailable";
  }
}

search.addEventListener("input", applySearch);
loadCustomers();
