document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("df-user-menu-toggle");
    const menu = document.getElementById("df-user-menu");

    if (!toggle || !menu) {
        return;
    }

    const closeMenu = () => {
        menu.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
    };

    toggle.addEventListener("click", (event) => {
        event.stopPropagation();
        const open = menu.classList.toggle("open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    document.addEventListener("click", (event) => {
        if (!menu.contains(event.target) && !toggle.contains(event.target)) {
            closeMenu();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeMenu();
        }
    });
});
