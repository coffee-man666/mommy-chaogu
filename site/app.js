(function () {
  "use strict";

  const topbar = document.querySelector("[data-topbar]");
  const menuToggle = document.querySelector("[data-menu-toggle]");
  const mobileNav = document.querySelector("[data-mobile-nav]");

  if (topbar && menuToggle && mobileNav) {
    menuToggle.addEventListener("click", function () {
      const open = topbar.classList.toggle("menu-open");
      menuToggle.setAttribute("aria-expanded", String(open));
      menuToggle.setAttribute("aria-label", open ? "关闭导航菜单" : "打开导航菜单");
    });
    mobileNav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        topbar.classList.remove("menu-open");
        menuToggle.setAttribute("aria-expanded", "false");
        menuToggle.setAttribute("aria-label", "打开导航菜单");
      });
    });
  }

  const commandElement = document.querySelector("#install-command");
  const copyButton = document.querySelector("[data-copy-command]");
  if (commandElement) {
    const fallbackOrigin = "https://coffee-man666.github.io/mommy-chaogu";
    const isHttp = window.location.protocol === "http:" || window.location.protocol === "https:";
    const pathname = window.location.pathname;
    const directory = pathname.endsWith("/") ? pathname.slice(0, -1) : pathname.slice(0, pathname.lastIndexOf("/"));
    const base = isHttp ? window.location.origin + directory : fallbackOrigin;
    const command = [
      `curl -fL ${base}/install-skill.py -o install-skill.py`,
      `curl -fL ${base}/skills/basket-analysis-v1.2.1.zip -o basket-analysis-v1.2.1.zip`,
      "python3 install-skill.py --target codex basket-analysis-v1.2.1.zip",
    ].join("\n");
    commandElement.textContent = command;
    if (copyButton) {
      copyButton.addEventListener("click", async function () {
        try {
          await navigator.clipboard.writeText(command);
          copyButton.textContent = "已复制";
        } catch (error) {
          copyButton.textContent = "请手动复制";
        }
        window.setTimeout(function () { copyButton.textContent = "复制命令"; }, 1800);
      });
    }
  }
})();
