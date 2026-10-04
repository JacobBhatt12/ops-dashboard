const recipientList = document.querySelector("#recipient-list");
const selectionCount = document.querySelector("#selection-count");
const footerCount = document.querySelector("#footer-count");
const selectAllButton = document.querySelector("#select-all");
const clearAllButton = document.querySelector("#clear-all");
const sendButton = document.querySelector("#send-emails");
const message = document.querySelector("#message");
const systemStatus = document.querySelector("#system-status");

const scheduleEnabled = document.querySelector("#schedule-enabled");
const scheduleToggleLabel = document.querySelector("#schedule-toggle-label");
const scheduleDay = document.querySelector("#schedule-day");
const scheduleTime = document.querySelector("#schedule-time");
const scheduleSave = document.querySelector("#schedule-save");
const scheduleStatus = document.querySelector("#schedule-status");
const scheduleNext = document.querySelector("#schedule-next");
const scheduleNextValue = document.querySelector("#schedule-next-value");

const statContacts = document.querySelector("#stat-contacts");
const statContactsNote = document.querySelector("#stat-contacts-note");
const contactsBars = document.querySelector("#contacts-bars");
const statSelected = document.querySelector("#stat-selected");
const statSelectedNote = document.querySelector("#stat-selected-note");
const selectedProgressFill = document.querySelector("#selected-progress-fill");
const statToday = document.querySelector("#stat-today");
const statTodayNote = document.querySelector("#stat-today-note");
const todaySpark = document.querySelector("#today-spark");
const statSchedule = document.querySelector("#stat-schedule");
const statScheduleNote = document.querySelector("#stat-schedule-note");
const statSchedulePill = document.querySelector("#stat-schedule-pill");


let recipients = [];
let isSending = false;

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value == null ? "" : String(value);
  return element.innerHTML;
}

function setStatus(state, label) {
  systemStatus.className = `system-status ${state}`.trim();
  systemStatus.querySelector("span").textContent = label;
}

function showMessage(text, type = "") {
  message.textContent = text;
  message.className = `message ${type}`.trim();
  message.hidden = false;
  Motion.pulse(message);
}

/* ── Recipients ─────────────────────────────────────────────────── */
function selectedIds() {
  return [...document.querySelectorAll('input[name="recipient"]:checked')].map((input) => input.value);
}

function updateSelection() {
  const selected = selectedIds().length;
  const total = recipients.length;

  selectionCount.textContent = `${selected} of ${total} selected`;
  footerCount.textContent = selected ? `${selected} contact${selected === 1 ? "" : "s"} selected` : "No recipients selected";
  selectAllButton.disabled = isSending || total === 0 || selected === total;
  clearAllButton.disabled = isSending || selected === 0;
  sendButton.disabled = isSending || selected === 0;

  Motion.countUp(statSelected, selected, { duration: 0.5 });
  statSelectedNote.textContent = selected === 0 ? "Nobody picked yet" : `${selected} of ${total} will receive this report`;
  selectedProgressFill.dataset.width = total > 0 ? String(Math.round((selected / total) * 100)) : "0";
  Motion.fillBars(selectedProgressFill.parentElement);
}

function setAllRecipients(checked) {
  document.querySelectorAll('input[name="recipient"]').forEach((input) => { input.checked = checked; });
  updateSelection();
}

function renderRecipients() {
  const clients = new Map();
  recipients.forEach((recipient) => {
    const key = `${recipient.client_name}|${recipient.website}`;
    if (!clients.has(key)) clients.set(key, []);
    clients.get(key).push(recipient);
  });

  Motion.countUp(statContacts, recipients.length);
  statContactsNote.textContent = clients.size === 1 ? "Across 1 client" : `Across ${clients.size} clients`;
  const maxContacts = Math.max(...[...clients.values()].map((c) => c.length), 1);
  contactsBars.innerHTML = [...clients.values()].map((c) =>
    `<i style="height:${Math.round((c.length / maxContacts) * 100)}%" title="${escapeHtml(c[0].client_name)}: ${c.length}"></i>`
  ).join("");
  if (Motion.animate) gsap.from(contactsBars.children, { scaleY: 0, duration: 0.8, ease: "power3.out", stagger: 0.08, delay: 0.3 });

  if (!recipients.length) {
    recipientList.innerHTML = '<div class="empty-state">No client contacts are configured yet.</div>';
    updateSelection();
    return;
  }

  recipientList.innerHTML = [...clients.entries()].map(([key, contacts]) => {
    const [clientName, website] = key.split("|");
    const rows = contacts.map((contact) => `
      <label class="recipient-row" data-searchable>
        <input type="checkbox" name="recipient" value="${escapeHtml(contact.id)}">
        <span class="recipient-name">${escapeHtml(contact.contact_name)}</span>
        <span class="recipient-email">${escapeHtml(contact.email)}</span>
      </label>
    `).join("");
    return `
      <section class="client-group" data-search-group aria-label="${escapeHtml(clientName)} contacts">
        <div class="client-heading">
          <h3>${escapeHtml(clientName)}</h3>
          <a href="https://${escapeHtml(website)}" target="_blank" rel="noreferrer">${escapeHtml(website)}</a>
        </div>
        ${rows}
      </section>
    `;
  }).join("");

  recipientList.querySelectorAll('input[name="recipient"]').forEach((input) => input.addEventListener("change", updateSelection));
  selectAllButton.disabled = false;
  updateSelection();
  Motion.rows(recipientList);
  document.dispatchEvent(new Event("listrendered"));
}

async function loadRecipients() {
  try {
    const response = await fetch("/api/recipients", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load recipients");
    recipients = (await response.json()).recipients;
    renderRecipients();
  } catch (error) {
    recipientList.innerHTML = '<div class="empty-state">Could not load your client list. Restart the dashboard and try again.</div>';
    selectionCount.textContent = "Client list unavailable";
    showMessage(error.message, "error");
  }
}

async function sendEmails() {
  const recipientIds = selectedIds();
  if (!recipientIds.length || isSending) return;

  isSending = true;
  sendButton.classList.add("is-busy");
  sendButton.querySelector("span").textContent = "Sending…";
  setStatus("busy", "Sending");
  showMessage("Running website checks and building each report. Keep this window open.");
  document.querySelectorAll('input[name="recipient"]').forEach((input) => { input.disabled = true; });
  updateSelection();

  try {
    const response = await fetch("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipient_ids: recipientIds }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The emails could not be sent");

    if (data.failed_count) {
      showMessage(`Sent ${data.sent_count} email${data.sent_count === 1 ? "" : "s"}. ${data.failed_count} failed. The send log at /outreach lists every send with its error.`, "error");
    } else {
      showMessage(`Sent ${data.sent_count} report${data.sent_count === 1 ? "" : "s"} successfully.`, "success");
      setAllRecipients(false);
    }
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    isSending = false;
    sendButton.classList.remove("is-busy");
    sendButton.querySelector("span").textContent = "Send reports";
    setStatus("", "Ready");
    document.querySelectorAll('input[name="recipient"]').forEach((input) => { input.disabled = false; });
    updateSelection();
    loadToday();
      }
}

/* ── Schedule ───────────────────────────────────────────────────── */
function ordinal(day) {
  if (day % 10 === 1 && day !== 11) return `${day}st`;
  if (day % 10 === 2 && day !== 12) return `${day}nd`;
  if (day % 10 === 3 && day !== 13) return `${day}rd`;
  return `${day}th`;
}

function populateDayOptions() {
  scheduleDay.innerHTML = Array.from({ length: 28 }, (_, i) => i + 1)
    .map((day) => `<option value="${day}">${ordinal(day)}</option>`).join("");
}

function formatNextRun(isoString) {
  if (!isoString) return "";
  return new Date(isoString).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatTime(hour, minute) {
  const d = new Date();
  d.setHours(hour, minute, 0, 0);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function setScheduleStatus(schedule) {
  scheduleToggleLabel.textContent = schedule.enabled ? "On" : "Off";
  if (schedule.enabled) {
    const nextRun = formatNextRun(schedule.next_run);
    scheduleStatus.textContent = `Every ${ordinal(schedule.day)} at ${formatTime(schedule.hour, schedule.minute)}`;
    scheduleNext.hidden = !nextRun;
    scheduleNextValue.textContent = nextRun;
    statSchedule.textContent = "On";
    statScheduleNote.textContent = nextRun ? `Next: ${nextRun}` : `Every ${ordinal(schedule.day)}`;
    statScheduleNote.className = "kpi-delta up";
    statSchedulePill.className = "pill ok";
    statSchedulePill.textContent = "Automatic";
  } else {
    scheduleStatus.textContent = "Reports only send when you press Send reports.";
    scheduleNext.hidden = true;
    statSchedule.textContent = "Off";
    statScheduleNote.textContent = "Manual sends only";
    statScheduleNote.className = "kpi-delta";
    statSchedulePill.className = "pill muted";
    statSchedulePill.textContent = "Manual only";
  }
}

function applyScheduleToForm(schedule) {
  scheduleEnabled.checked = schedule.enabled;
  scheduleDay.value = String(schedule.day);
  scheduleTime.value = `${String(schedule.hour).padStart(2, "0")}:${String(schedule.minute).padStart(2, "0")}`;
  setScheduleStatus(schedule);
}

function enableScheduleControls() {
  [scheduleEnabled, scheduleDay, scheduleTime, scheduleSave].forEach((el) => { el.disabled = false; });
}

async function loadSchedule() {
  populateDayOptions();
  try {
    const response = await fetch("/api/schedule", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load the schedule");
    applyScheduleToForm(await response.json());
    enableScheduleControls();
  } catch (error) {
    scheduleStatus.textContent = "Could not load the schedule. Restart the dashboard and try again.";
  }
}

async function saveSchedule() {
  const [hourText, minuteText] = scheduleTime.value.split(":");
  const payload = { enabled: scheduleEnabled.checked, day: Number(scheduleDay.value), hour: Number(hourText), minute: Number(minuteText) };
  if (!scheduleTime.value || Number.isNaN(payload.hour) || Number.isNaN(payload.minute)) {
    showMessage("Choose a time for the automatic send.", "error");
    return;
  }
  scheduleSave.disabled = true;
  scheduleSave.textContent = "Saving…";
  try {
    const response = await fetch("/api/schedule", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The schedule could not be saved");
    setScheduleStatus(data);
    showMessage(data.enabled ? "Automatic monthly send is on." : "Automatic monthly send is off.", "success");
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    scheduleSave.disabled = false;
    scheduleSave.textContent = "Save schedule";
  }
}

scheduleEnabled.addEventListener("change", () => { scheduleToggleLabel.textContent = scheduleEnabled.checked ? "On" : "Off"; });

/* ── Reports sent today (client reports only; outreach lives on /outreach) ── */
async function loadToday() {
  try {
    const [todayRes, activityRes] = await Promise.all([
      fetch("/api/sent-today", { cache: "no-store" }),
      fetch("/api/send-activity?days=14", { cache: "no-store" }),
    ]);
    if (!todayRes.ok || !activityRes.ok) throw new Error("Could not load today's sends");
    const { counts } = await todayRes.json();
    const { days } = await activityRes.json();
    Motion.countUp(statToday, counts.reports);
    statTodayNote.className = counts.failed ? "kpi-delta down" : counts.reports ? "kpi-delta up" : "kpi-delta";
    statTodayNote.textContent = counts.failed
      ? `${counts.failed} failed · ${counts.reports} sent`
      : counts.reports ? `${counts.reports} Website Care report${counts.reports === 1 ? "" : "s"} today` : "No reports sent yet today";
    Motion.sparkline(todaySpark, days.map((d) => d.reports), { delay: 0.4 });
  } catch (error) {
    statTodayNote.textContent = "Send log unavailable";
  }
}

/* ── Wire up ────────────────────────────────────────────────────── */
selectAllButton.addEventListener("click", () => setAllRecipients(true));
clearAllButton.addEventListener("click", () => setAllRecipients(false));
sendButton.addEventListener("click", sendEmails);
scheduleSave.addEventListener("click", saveSchedule);


loadRecipients();
loadSchedule();
loadToday();
loadActivity();
setInterval(loadToday, 60000);
