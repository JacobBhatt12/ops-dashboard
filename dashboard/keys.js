const lockPanel = document.querySelector("#lock-panel");
const keysPanel = document.querySelector("#keys-panel");
const lockStatus = document.querySelector("#lock-status");
const pinForm = document.querySelector("#pin-form");
const pinInput = document.querySelector("#pin-input");
const unlockButton = document.querySelector("#unlock-button");
const lockAgainButton = document.querySelector("#lock-again");
const keysList = document.querySelector("#keys-list");

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

async function copyToClipboard(text, el) {
  const original = el.textContent;
  try {
    await navigator.clipboard.writeText(text);
    el.textContent = "Copied!";
  } catch (error) {
    el.textContent = "Couldn't copy";
  } finally {
    setTimeout(() => { el.textContent = original; }, 1200);
  }
}

function renderKeys(entries) {
  keysList.innerHTML = entries.map((entry) => `
    <div class="issue-client" data-searchable>
      <h4>${escapeHtml(entry.client)}</h4>
      ${Object.entries(entry.keys).map(([keyName, value]) => `
        <button type="button" class="key-row" data-value="${escapeHtml(value)}" title="Click to copy">
          <span class="key-row-top">
            <span class="key-label">${escapeHtml(keyName)}</span>
            <svg class="key-copy-icon icon" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          </span>
          <span class="key-value">${escapeHtml(value)}</span>
        </button>
      `).join("")}
    </div>
  `).join("") || '<div class="empty-state">No keys on file.</div>';

  keysList.querySelectorAll(".key-row").forEach((row) => {
    row.addEventListener("click", () => {
      const label = row.querySelector(".key-label");
      copyToClipboard(row.dataset.value, label);
    });
  });
}

async function unlock(event) {
  event.preventDefault();
  const pin = pinInput.value.trim();
  if (!pin) return;

  unlockButton.disabled = true;
  unlockButton.textContent = "Checking…";
  lockStatus.textContent = "Checking PIN…";

  try {
    const response = await fetch("/api/web3forms-keys/unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not unlock");

    renderKeys(data.entries || []);
    lockPanel.hidden = true;
    keysPanel.hidden = false;
    keysPanel.style.opacity = "1";
    Motion.rows(keysList);
  } catch (error) {
    lockStatus.textContent = error.message;
    pinInput.value = "";
    pinInput.focus();
  } finally {
    unlockButton.disabled = false;
    unlockButton.textContent = "Unlock";
  }
}

function lockAgain() {
  keysPanel.hidden = true;
  lockPanel.hidden = false;
  lockStatus.textContent = "Enter the PIN to view the keys.";
  pinInput.value = "";
  pinInput.focus();
  keysList.innerHTML = "";
}

pinForm.addEventListener("submit", unlock);
lockAgainButton.addEventListener("click", lockAgain);
