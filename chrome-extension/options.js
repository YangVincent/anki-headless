const apiKeyInput = document.getElementById("apiKey");
const saveBtn = document.getElementById("save");
const msg = document.getElementById("msg");

// Load saved key
chrome.storage.sync.get("apiKey", ({ apiKey }) => {
  if (apiKey) apiKeyInput.value = apiKey;
});

saveBtn.addEventListener("click", () => {
  const apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    msg.textContent = "API key cannot be empty.";
    msg.style.color = "#991b1b";
    return;
  }
  chrome.storage.sync.set({ apiKey }, () => {
    msg.textContent = "Saved!";
    msg.style.color = "#065f46";
  });
});
