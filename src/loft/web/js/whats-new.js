/**
 * What's New popup for displaying changelog on updates.
 * Shows automatically on first visit after version update.
 */

export class WhatsNewPopup {
  constructor() {
    this.storageKey = "loft_last_seen_version";
    this.versionKey = "loft_app_version";
  }

  async init() {
    try {
      // Get current version from API
      const pingResponse = await fetch("/api/ping");
      const { version } = await pingResponse.json();

      // Check if user has seen this version's changelog
      const lastSeen = localStorage.getItem(this.storageKey);

      if (lastSeen !== version && version !== "dev") {
        // User is on a new version, show What's New
        await this.showWhatsNew(version);
        localStorage.setItem(this.storageKey, version);
      }
    } catch (err) {
      console.error("Failed to initialize What's New:", err);
    }
  }

  async showWhatsNew(version) {
    try {
      const response = await fetch("/api/changelog/latest");
      const changelog = await response.json();

      this.renderPopup(changelog);
    } catch (err) {
      console.error("Failed to fetch changelog:", err);
    }
  }

  renderPopup(changelog) {
    // Create overlay
    const overlay = document.createElement("div");
    overlay.className = "whats-new-overlay";
    overlay.id = "whats-new-overlay";

    // Create modal
    const modal = document.createElement("div");
    modal.className = "whats-new-modal";

    // Header
    const header = document.createElement("div");
    header.className = "whats-new-header";
    header.innerHTML = `
      <h2>What's New in Loft ${changelog.version}</h2>
      <button class="whats-new-close" aria-label="Close">✕</button>
    `;

    // Content
    const content = document.createElement("div");
    content.className = "whats-new-content";

    // Add sections from changelog
    for (const [section, items] of Object.entries(changelog.sections || {})) {
      const sectionDiv = document.createElement("div");
      sectionDiv.className = "whats-new-section";

      const sectionTitle = document.createElement("h3");
      sectionTitle.textContent = section;
      sectionDiv.appendChild(sectionTitle);

      const list = document.createElement("ul");
      for (const item of items) {
        const li = document.createElement("li");
        li.textContent = item;
        list.appendChild(li);
      }
      sectionDiv.appendChild(list);
      content.appendChild(sectionDiv);
    }

    // Footer with buttons
    const footer = document.createElement("div");
    footer.className = "whats-new-footer";
    footer.innerHTML = `
      <button class="whats-new-btn whats-new-changelog">View full changelog</button>
      <button class="whats-new-btn whats-new-primary">Got it!</button>
    `;

    // Assemble modal
    modal.appendChild(header);
    modal.appendChild(content);
    modal.appendChild(footer);

    // Assemble overlay
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Add event listeners
    const closeBtn = overlay.querySelector(".whats-new-close");
    const gotItBtn = overlay.querySelector(".whats-new-primary");
    const changelogBtn = overlay.querySelector(".whats-new-changelog");

    const close = () => {
      overlay.remove();
    };

    closeBtn.addEventListener("click", close);
    gotItBtn.addEventListener("click", close);

    changelogBtn.addEventListener("click", () => {
      // Could open a changelog page or link
      window.location.hash = "#changelog";
      close();
    });

    // Close on overlay click (outside modal)
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });
  }
}

// Auto-initialize on page load
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    new WhatsNewPopup().init();
  });
} else {
  new WhatsNewPopup().init();
}
