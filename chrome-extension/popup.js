const wordInput = document.getElementById("word");
const addBtn = document.getElementById("add");
const statusDiv = document.getElementById("status");

function setStatus(text, cls) {
  statusDiv.textContent = text;
  statusDiv.className = cls;
}

addBtn.addEventListener("click", async () => {
  const word = wordInput.value.trim();
  if (!word) return;

  addBtn.disabled = true;
  setStatus("Processing...", "loading");

  chrome.runtime.sendMessage({ type: "add-word", word }, (resp) => {
    addBtn.disabled = false;
    if (!resp) {
      setStatus("No response from background", "error");
      return;
    }
    if (resp.status === "error") {
      setStatus(resp.message || "Unknown error", "error");
    } else {
      const msg = resp.word
        ? `${resp.status}: ${resp.word} (${resp.pinyin}) - ${resp.meaning}`
        : resp.message || JSON.stringify(resp);
      setStatus(msg, "success");
      wordInput.value = "";
    }
  });
});

wordInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") addBtn.click();
});

// Show last result on open
chrome.storage.local.get("lastResult", ({ lastResult }) => {
  if (lastResult && lastResult.word) {
    setStatus(
      `Last: ${lastResult.status} - ${lastResult.word} (${lastResult.pinyin})`,
      lastResult.status === "error" ? "error" : "success"
    );
  }
});
