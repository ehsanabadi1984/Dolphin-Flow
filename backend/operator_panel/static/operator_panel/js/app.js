document.addEventListener("DOMContentLoaded", () => {

    const layout = document.querySelector(".df-layout");
    const toggle = document.getElementById("df-sidebar-toggle");

    if (!layout || !toggle) {
        return;
    }

    toggle.addEventListener("click", () => {
        layout.classList.toggle("sidebar-collapsed");
    });

});
