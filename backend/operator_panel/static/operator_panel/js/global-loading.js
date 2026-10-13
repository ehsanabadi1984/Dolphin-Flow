(function () {
    "use strict";

    const overlay = document.getElementById("df-global-loading");
    if (!overlay) return;

    let loadingShown = false;

    function showLoading() {
        if (loadingShown) return;
        loadingShown = true;
        overlay.classList.add("is-visible");
        overlay.setAttribute("aria-hidden", "false");
    }

    function hideLoading() {
        loadingShown = false;
        overlay.classList.remove("is-visible");
        overlay.setAttribute("aria-hidden", "true");
    }

    /*
     * Workflow transitions are important POST actions. Handle them in
     * capture phase so another submit listener cannot hide the loading
     * indicator by preventing the event later in the bubble phase.
     * Prevent repeated clicks while the server executes the transition.
     */
    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (!form.matches("[data-workflow-transition]")) return;
        if (form.dataset.transitionSubmitting === "1") {
            event.preventDefault();
            return;
        }

        form.dataset.transitionSubmitting = "1";
        form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (button) {
            button.disabled = true;
            if (button instanceof HTMLButtonElement) {
                button.setAttribute("aria-busy", "true");
            }
        });

        showLoading();
    }, true);

    /*
     * Standard form submits: native browser validation runs before
     * the submit event. Skip AJAX/opt-out forms and submissions targeted
     * at another browsing context.
     */
    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (event.defaultPrevented) return;
        if (form.dataset.noGlobalLoading !== undefined) return;
        if (form.dataset.ajax !== undefined) return;
        if ((form.getAttribute("method") || "get").toLowerCase() === "dialog") return;

        const target = (form.getAttribute("target") || "").toLowerCase();
        if (target && target !== "_self") return;

        showLoading();
    });

    /*
     * Same-tab, same-origin navigation only. Ignore downloads, new tabs,
     * modified clicks, in-page anchors, and links handled by JS.
     */
    document.addEventListener("click", function (event) {
        if (event.defaultPrevented) return;
        if (event.button !== 0 || event.metaKey || event.ctrlKey ||
            event.shiftKey || event.altKey) return;

        const link = event.target.closest("a[href]");
        if (!link) return;
        if (link.hasAttribute("download")) return;
        if (link.dataset.noGlobalLoading !== undefined) return;
        if (link.getAttribute("aria-disabled") === "true") return;

        const target = (link.getAttribute("target") || "").toLowerCase();
        if (target && target !== "_self") return;

        const rawHref = link.getAttribute("href");
        if (!rawHref || rawHref.trim() === "" || rawHref.trim().startsWith("#")) return;

        let destination;
        try {
            destination = new URL(rawHref, window.location.href);
        } catch (_) {
            return;
        }

        if (destination.origin !== window.location.origin) return;
        if (destination.pathname === window.location.pathname &&
            destination.search === window.location.search &&
            destination.hash) return;

        if (link.closest("[data-no-global-loading]")) return;
        showLoading();
    });

    // A page restored from the browser back/forward cache must not stay covered.
    window.addEventListener("pageshow", hideLoading);
})();
