(() => {
    const storageKey = "df-theme";
    const root = document.documentElement;

    function applyTheme(theme) {
        const isLight = theme === "light";
        root.classList.toggle("theme-light", isLight);

        const toggle = document.getElementById("df-theme-toggle");
        if (toggle) {
            toggle.setAttribute(
                "aria-label",
                isLight ? "فعال‌سازی تم تاریک" : "فعال‌سازی تم روشن"
            );
            toggle.setAttribute(
                "title",
                isLight ? "تم تاریک" : "تم روشن"
            );
        }
    }

    const savedTheme = localStorage.getItem(storageKey);
    applyTheme(savedTheme === "light" ? "light" : "dark");

    document.addEventListener("DOMContentLoaded", () => {
        const toggle = document.getElementById("df-theme-toggle");
        if (!toggle) return;

        toggle.addEventListener("click", () => {
            const nextTheme = root.classList.contains("theme-light")
                ? "dark"
                : "light";

            localStorage.setItem(storageKey, nextTheme);
            applyTheme(nextTheme);
        });
    });
})();
