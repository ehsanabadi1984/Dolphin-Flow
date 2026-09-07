(function () {
    "use strict";

    var STATUS = document.getElementById("df-section-layout-status");
    var FORM = document.getElementById("df-section-layout-form");
    var LIST = document.getElementById("df-section-layout-list");
    var SAVE = document.getElementById("df-section-layout-save");

    if (!FORM || !LIST || !SAVE) {
        return;
    }

    var initializing = false;

    function setStatus(message, isError) {
        if (!STATUS) {
            return;
        }

        STATUS.textContent = message || "";
        STATUS.className = "df-section-layout-status" +
            (isError ? " df-section-layout-status-error" : "");
    }

    function itemCssValues() {
        var items = [];

        Array.prototype.forEach.call(LIST.children, function (node) {
            var id = node.getAttribute("data-item-id");
            var type = node.getAttribute("data-item-type");
            items.push({
                id: id,
                type: type
            });
        });

        return items;
    }

    function applyDocumentOrder() {
        var items = itemCssValues();
        var ordered = {};

        Array.prototype.forEach.call(LIST.children, function (node) {
            var id = node.getAttribute("data-item-id");
            ordered[id] = node;
        });

        items.forEach(function (item) {
            var node = ordered[item.id];
            if (node && node.parentNode !== LIST) {
                LIST.appendChild(node);
            }
        });
    }

    function dragStart(e) {
        if (initializing) {
            return;
        }

        var node = e.target.closest(".df-layout-item");
        if (!node) {
            return;
        }

        if (!e.target.classList.contains("df-layout-item-grip")) {
            e.preventDefault();
        }

        node.setAttribute("draggable", "true");
        node.classList.add("df-layout-item-dragging");
        e.dataTransfer.setData("text/plain", node.getAttribute("data-item-id"));
        e.dataTransfer.effectAllowed = "move";
    }

    function dragOver(e) {
        var node = e.target.closest(".df-layout-item");
        if (!node) {
            return;
        }

        e.preventDefault();
        e.dataTransfer.dropEffect = "move";

        var dragging = LIST.querySelector(".df-layout-item-dragging");
        if (!dragging || node === dragging) {
            return;
        }

        var rect = node.getBoundingClientRect();
        var insertAfter = (e.clientX - rect.left) > (rect.width / 2);

        if (insertAfter) {
            LIST.insertBefore(dragging, node.nextSibling);
        } else {
            LIST.insertBefore(dragging, node);
        }
    }

    function dragEnd(e) {
        var dragging = LIST.querySelector(".df-layout-item-dragging");
        if (dragging) {
            dragging.removeAttribute("draggable");
            dragging.classList.remove("df-layout-item-dragging");
        }
    }

    function initSortable() {
        if (LIST.dataset.sectionLayoutDesignerInitialized === "true") {
            return;
        }

        initializing = true;

        LIST.addEventListener("dragstart", dragStart);
        LIST.addEventListener("dragover", dragOver);
        LIST.addEventListener("dragend", dragEnd);

        var items = LIST.querySelectorAll(".df-layout-item");
        Array.prototype.forEach.call(items, function (node) {
            node.setAttribute("draggable", "true");
        });

        initializing = false;
        LIST.dataset.sectionLayoutDesignerInitialized = "true";
    }

    function buildPayloadFromDom() {
        var items = itemCssValues();
        var seen = {};
        var payload = [];

        items.forEach(function (item) {
            if (!item.id || !item.type) {
                return;
            }

            if (seen[item.id]) {
                return;
            }
            seen[item.id] = true;

            payload.push({
                type: item.type,
                id: Number(item.id)
            });
        });

        return payload;
    }

    function submitLayout(animateButton) {
        if (animateButton) {
            SAVE.disabled = true;
            SAVE.textContent = "در حال ذخیره...";
            setStatus("");
        }

        var payload = buildPayloadFromDom();

        return fetch(FORM.action, {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": getCookie("csrftoken")
            },
            body: JSON.stringify(payload)
        }).then(function (response) {
            if (!response.ok) {
                return response.json().then(function (data) {
                    throw new Error(
                        data && data.error ? data.error : "ذخیره ترتیب با خطا مواجه شد."
                    );
                });
            }

            return response.json();
        }).then(function () {
            SAVE.textContent = "ذخیره ترتیب";
            setStatus("ترتیب با موفقیت ذخیره شد.", false);
        }).catch(function (error) {
            SAVE.textContent = "ذخیره ترتیب";
            setStatus(error.message || "ذخیره ترتیب با خطا مواجه شد.", true);
            throw error;
        }).finally(function () {
            SAVE.disabled = false;
        });
    }

    function getCookie(name) {
        var value = null;
        var cookies = document.cookie.split(";");
        Array.prototype.forEach.call(cookies, function (cookie) {
            cookie = cookie.trim();
            if (cookie.indexOf(name + "=") === 0) {
                value = decodeURIComponent(cookie.substring(name.length + 1));
            }
        });
        return value;
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            initSortable();
        }, { once: true });
    } else {
        initSortable();
    }

    FORM.addEventListener("submit", function (e) {
        e.preventDefault();

        if (SAVE.disabled) {
            return;
        }

        submitLayout(true).catch(function () {
            SAVE.disabled = false;
            SAVE.textContent = "ذخیره ترتیب";
        });
    });
})();
