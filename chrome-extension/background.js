const API_URL = "https://anki.aeonneo.com/api/card";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "add-to-anki",
    title: "Add to Anki",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "add-to-anki") return;
  const word = info.selectionText?.trim();
  if (!word) return;

  const { apiKey } = await chrome.storage.sync.get("apiKey");
  if (!apiKey) {
    chrome.action.setBadgeText({ text: "KEY", tabId: tab.id });
    chrome.action.setBadgeBackgroundColor({ color: "#F59E0B", tabId: tab.id });
    setTimeout(() => chrome.action.setBadgeText({ text: "", tabId: tab.id }), 4000);
    return;
  }

  // Show loading state
  chrome.action.setBadgeText({ text: "...", tabId: tab.id });
  chrome.action.setBadgeBackgroundColor({ color: "#3B82F6", tabId: tab.id });

  try {
    const resp = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({ word }),
    });

    const data = await resp.json();

    if (resp.ok && data.status !== "error") {
      chrome.action.setBadgeText({ text: "OK", tabId: tab.id });
      chrome.action.setBadgeBackgroundColor({ color: "#10B981", tabId: tab.id });
      // Store last result for popup display
      chrome.storage.local.set({ lastResult: data });
    } else {
      chrome.action.setBadgeText({ text: "ERR", tabId: tab.id });
      chrome.action.setBadgeBackgroundColor({ color: "#EF4444", tabId: tab.id });
      chrome.storage.local.set({ lastResult: data });
    }
  } catch (err) {
    chrome.action.setBadgeText({ text: "ERR", tabId: tab.id });
    chrome.action.setBadgeBackgroundColor({ color: "#EF4444", tabId: tab.id });
    chrome.storage.local.set({ lastResult: { status: "error", message: err.message } });
  }

  setTimeout(() => chrome.action.setBadgeText({ text: "", tabId: tab.id }), 4000);
});

// Handle messages from popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "add-word") {
    (async () => {
      const { apiKey } = await chrome.storage.sync.get("apiKey");
      if (!apiKey) {
        sendResponse({ status: "error", message: "API key not set. Go to extension options." });
        return;
      }

      try {
        const resp = await fetch(API_URL, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${apiKey}`,
          },
          body: JSON.stringify({ word: msg.word, context: msg.context || "" }),
        });
        const data = await resp.json();
        sendResponse(data);
      } catch (err) {
        sendResponse({ status: "error", message: err.message });
      }
    })();
    return true; // keep channel open for async response
  }
});
