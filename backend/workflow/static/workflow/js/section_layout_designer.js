(function () {
    "use strict";

    var STATUS = document.getElementById("df-section-layout-status");
    var FORM = document.getElementById("df-section-layout-form");
    var LIST = document.getElementById("df-section-layout-list");
    var SAVE = document.getElementById("df-section-layout-save");
    var dragging = null;
    var placeholder = null;

    if (!FORM || !LIST || !SAVE) {
        return;
    }

    function setStatus(message, isError) {
        if (!STATUS) {
            return;
        }

        STATUS.textContent = message || "";
        STATUS.className = "df-section-layout-status" +
            (isError ? " df-section-layout-status-error" : "");
    }

    function itemValues() {
        var items = [];

        Array.prototype.forEach.call(LIST.children, function (node) {
            var id = node.getAttribute("data-item-id");
            var type = node.getAttribute("data-item-type");

            if (!id || !type || node.classList.contains("df-layout-item-placeholder")) {
                return;
            }

            items.push({
                id: id,
                type: type
            });
        });

        return items;
    }

    function typedIdentity(item) {
        return item.type + ":" + item.id;
    }

    function createPlaceholder(node) {
        if (placeholder) {
            return;
        }

        placeholder = document.createElement("div");
        placeholder.className = "df-layout-item-placeholder";
        placeholder.setAttribute("aria-hidden", "true");
        placeholder.style.height = node.getBoundingClientRect().height + "px";
    }

    function movePlaceholder(e) {
        if (!dragging || !placeholder) {
            return;
        }

        var node = e.target.closest(".df-layout-item");
        if (!node || node === dragging || !LIST.contains(node)) {
            return;
        }

        var rect = node.getBoundingClientRect();
        var insertAfter = (e.clientY - rect.top) > (rect.height / 2);

        if (insertAfter) {
            LIST.insertBefore(placeholder, node.nextSibling);
        } else {
            LIST.insertBefore(placeholder, node);
        }
    }

    function dragStart(e) {
        var node = e.target.closest(".df-layout-item");
        if (!node || !LIST.contains(node)) {
            return;
        }

        dragging = node;
        createPlaceholder(node);

        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData(
            "text/plain",
            typedIdentity({
                id: node.getAttribute("data-item-id"),
                type: node.getAttribute("data-item-type")
            })
        );

        window.setTimeout(function () {
            if (dragging) {
                dragging.classList.add("df-layout-item-dragging");
            }
        }, 0);
    }

    function dragOver(e) {
        if (!dragging) {
            return;
        }

        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        movePlaceholder(e);
    }

    function drop(e) {
        if (!dragging || !placeholder) {
            return;
        }

        e.preventDefault();

        LIST.insertBefore(dragging, placeholder);
        placeholder.remove();
        placeholder = null;
    }

    function dragEnd() {
        if (placeholder) {
            placeholder.remove();
            placeholder = null;
        }

        if (dragging) {
            dragging.classList.remove("df-layout-item-dragging");
            dragging.setAttribute("draggable", "true");
        }

        dragging = null;
    }

    function initSortable() {
        if (LIST.dataset.sectionLayoutDesignerInitialized === "true") {
            return;
        }

        LIST.addEventListener("dragstart", dragStart);
        LIST.addEventListener("dragover", dragOver);
        LIST.addEventListener("drop", drop);
        LIST.addEventListener("dragend", dragEnd);

        Array.prototype.forEach.call(
            LIST.querySelectorAll(".df-layout-item"),
            function (node) {
                node.setAttribute("draggable", "true");
            }
        );

        LIST.dataset.sectionLayoutDesignerInitialized = "true";
    }

    function buildPayloadFromDom() {
        var payload = [];
        var seen = {};

        itemValues().forEach(function (item) {
            var identity = typedIdentity(item);

            if (seen[identity]) {
                return;
            }

            seen[identity] = true;
            payload.push({
                type: item.type,
                id: Number(item.id)
            });
        });

        return payload;
    }

    function getCookie(name) {
        var value = null;
        var cookies = document.cookie.split(";");

        Array.prototype.forEach.call(cookies, function (cookie) {
            cookie = cookie.trim();
            if (cookie.indexOf(name + "=") === 0) {
                value = decodeURIComponent(
                    cookie.substring(name.length + 1)
                );
            }
        });

        return value;
    }

    function submitLayout() {
        SAVE.disabled = true;
        SAVE.textContent = "در حال ذخیره...";
        setStatus("");

        return fetch(FORM.action, {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": getCookie("csrftoken") || "",
                "Content-Type": "application/json"
            },
            body: JSON.stringify(buildPayloadFromDom())
        }).then(function (response) {
            return response.text().then(function (text) {
                var data = {};

                try {
                    data = text ? JSON.parse(text) : {};
                } catch (error) {
                    data = {};
                }

                if (!response.ok) {
                    throw new Error(
                        data && data.error
                            ? data.error
                            : "ذخیره ترتیب با خطا مواجه شد."
                    );
                }

                return data;
            });
        }).then(function () {
            SAVE.textContent = "ذخیره ترتیب";
            setStatus("ترتیب با موفقیت ذخیره شد.", false);
        }).catch(function (error) {
            SAVE.textContent = "ذخیره ترتیب";
            setStatus(
                error.message || "ذخیره ترتیب با خطا مواجه شد.",
                true
            );
        }).finally(function () {
            SAVE.disabled = false;
        });
    }

    function init() {
        initSortable();

        if (FORM.dataset.sectionLayoutSubmitInitialized === "true") {
            return;
        }

        FORM.addEventListener("submit", function (e) {
            e.preventDefault();

            if (SAVE.disabled) {
                return;
            }

            submitLayout();
        });

        FORM.dataset.sectionLayoutSubmitInitialized = "true";
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
