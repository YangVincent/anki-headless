let toastTimer = null;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== "anki-toast") return;

  const existing = document.getElementById("anki-toast");
  if (existing) existing.remove();
  if (toastTimer) clearTimeout(toastTimer);

  const bg = msg.isError ? "#EF4444" : msg.isLoading ? "#3B82F6" : "#10B981";

  const toast = document.createElement("div");
  toast.id = "anki-toast";
  toast.style.cssText = `
    position: fixed; top: 20px; right: 20px; z-index: 2147483647;
    max-width: 360px; padding: 14px 18px; border-radius: 10px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px; line-height: 1.4; color: #fff;
    background: ${bg};
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    opacity: 0; transform: translateX(40px);
    transition: opacity 0.3s, transform 0.3s;
  `;
  toast.innerHTML = `<div style="font-weight:600;margin-bottom:2px">${msg.title}</div><div style="opacity:0.95">${msg.message}</div>`;

  document.body.appendChild(toast);
  requestAnimationFrame(() => {
    toast.style.opacity = "1";
    toast.style.transform = "translateX(0)";
  });

  // Loading toasts stay until replaced; success/error auto-dismiss
  if (!msg.isLoading) {
    toastTimer = setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(40px)";
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }
});
