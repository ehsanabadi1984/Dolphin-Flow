document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("df-share-inbox");
    const inboxLink = document.getElementById("df-file-share-inbox-link");
    const apiUrl = root?.dataset.apiUrl || inboxLink?.dataset.apiUrl;
    const unreadBadge = document.getElementById("df-file-share-unread-badge");

    async function refreshUnreadCount() {
        if (!apiUrl || !unreadBadge) return;
        try {
            const separator = apiUrl.includes("?") ? "&" : "?";
            const response = await fetch(apiUrl + separator + "counts_only=1", {
                credentials: "same-origin",
                cache: "no-store",
                headers: { "Accept": "application/json" },
            });
            if (!response.ok) return;
            const data = await response.json();
            const count = Number(data.unread_messages_count || 0);
            unreadBadge.textContent = String(count);
            unreadBadge.hidden = count < 1;
        } catch (error) {
            console.warn("Unable to refresh unread file-share count:", error);
        }
    }

    if (apiUrl && unreadBadge) {
        refreshUnreadCount();
        window.setInterval(refreshUnreadCount, 10000);
        window.addEventListener("df:file-share-notification", refreshUnreadCount);
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) refreshUnreadCount();
        });
    }

    if (!root) return;
    const list = document.getElementById("df-share-inbox-items");
    const detail = document.getElementById("df-share-inbox-detail");
    const tabs = Array.from(root.querySelectorAll("[data-share-tab]"));
    let payload = { messages: [], sent_messages: [], drafts: [] };
    let activeTab = "received";
    let initialMessageOpened = false;

    const interactionLabels = {
        VIEW: "اشتراک‌گذاری برای مشاهده",
        RESPONSE: "درخواست پاسخ یا دریافت اطلاعات",
        ACTION: "درخواست انجام اقدام",
        REVIEW: "درخواست بررسی یا تأیید فایل",
    };
    const statusLabels = {
        PENDING: "خوانده‌نشده",
        READ: "مشاهده‌شده",
        RESPONDED: "پاسخ‌داده‌شده",
        COMPLETED: "تکمیل‌شده",
        CANCELLED: "لغوشده",
        EXPIRED: "منقضی‌شده",
        DRAFT: "پیش‌نویس",
    };

    function node(tag, className, value) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (value !== undefined) element.textContent = value;
        return element;
    }
    function csrf() {
        const item = document.cookie.split("; ").find((part) => part.startsWith("csrftoken="));
        return item ? decodeURIComponent(item.split("=").slice(1).join("=")) : "";
    }
    function setFeedback(message) {
        const feedback = detail.querySelector("[data-share-feedback]");
        if (feedback) feedback.textContent = message;
    }
    function formatBytes(value) {
        const bytes = Number(value);
        if (!Number.isFinite(bytes) || bytes < 0) return "نامشخص";
        if (bytes < 1024) return bytes + " بایت";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " کیلوبایت";
        return (bytes / (1024 * 1024)).toFixed(1) + " مگابایت";
    }
    function formatContentType(value) {
        const type = String(value || "").toLowerCase();
        if (type.startsWith("image/")) return "تصویر " + type.slice(6).toUpperCase();
        if (type === "application/pdf") return "سند PDF";
        if (type.includes("word")) return "سند Word";
        if (type.includes("spreadsheet") || type.includes("excel")) return "فایل صفحه‌گسترده";
        if (type.startsWith("text/")) return "فایل متنی";
        return type || "نامشخص";
    }
    function appendFileDetails(message) {
        const file = message.file_details || {};
        const details = node("dl", "df-share-inbox-file-details");
        const rows = [
            ["فیلد", file.field_label || "فایل پیوست"],
            ["نام فایل", file.original_name || message.file_name || "نامشخص"],
            ["حجم فایل", formatBytes(file.file_size ?? message.file_size)],
            ["نوع فایل", formatContentType(file.content_type || message.content_type)],
        ];
        rows.forEach(([label, value]) => {
            details.append(node("dt", "", label), node("dd", "", value));
        });
        detail.appendChild(details);
    }
    async function request(url, options) {
        const response = await fetch(url, {
            credentials: "same-origin",
            headers: { "Accept": "application/json", ...(options && options.headers || {}) },
            ...(options || {}),
        });
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {
            throw new Error("پاسخ سرور قابل پردازش نیست. لطفاً صفحه را تازه‌سازی کنید.");
        }
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "انجام عملیات ناموفق بود.");
        return data;
    }
    function renderList() {
        tabs.forEach((tab) => tab.setAttribute("aria-pressed", String(tab.dataset.shareTab === activeTab)));
        list.replaceChildren();
        const items = activeTab === "received" ? payload.messages :
            activeTab === "sent" ? payload.sent_messages : payload.drafts;
        if (!items.length) {
            list.appendChild(node("div", "df-share-inbox-empty",
                activeTab === "received" ? "پیام دریافتی وجود ندارد." :
                activeTab === "sent" ? "پیام ارسالی وجود ندارد." : "پیش‌نویسی وجود ندارد."));
            return;
        }
        items.forEach((item) => {
            const card = node("article", "df-share-inbox-item");
            if (activeTab === "received" && item.status === "PENDING") card.classList.add("is-unread");
            card.appendChild(node("strong", "", item.subject || item.file_name || "بدون موضوع"));
            card.appendChild(node("span", "df-share-inbox-meta",
                activeTab === "received" ? "فرستنده: " + item.sender : "گیرنده: " + item.recipient));
            card.appendChild(node("span", "df-share-inbox-meta",
                "وضعیت: " + (statusLabels[item.status] || item.status || "پیش‌نویس") +
                (item.file_name ? " · " + item.file_name : "")));
            if (activeTab === "received") {
                const open = node("button", "df-button df-button-secondary", "مشاهده پیام");
                open.type = "button";
                open.addEventListener("click", () => openMessage(item.url));
                card.appendChild(open);
            } else if (activeTab === "sent" &&
                ["PENDING", "READ", "RESPONDED"].includes(item.status)) {
                const recall = node("button", "df-button df-button-danger", "لغو پیام");
                recall.type = "button";
                recall.addEventListener("click", () => recallMessage(item.recall_url));
                card.appendChild(recall);
            } else if (activeTab === "drafts") {
                const actions = node("div", "df-share-inbox-actions");
                const edit = node("button", "df-button df-button-secondary", "ویرایش");
                edit.type = "button";
                edit.addEventListener("click", async () => {
                    const subject = window.prompt("موضوع پیش‌نویس:", item.subject || "");
                    if (subject === null) return;
                    const body = window.prompt("توضیحات پیش‌نویس:", item.body || "");
                    if (body === null) return;
                    try {
                        await request(item.update_url, {
                            method: "POST",
                            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
                            body: JSON.stringify({ subject, body }),
                        });
                        await load();
                    } catch (error) { window.alert(error.message); }
                });
                const remove = node("button", "df-button df-button-danger", "حذف پیش‌نویس");
                remove.type = "button";
                remove.addEventListener("click", async () => {
                    if (!window.confirm("این پیش‌نویس حذف شود؟")) return;
                    try {
                        await request(item.delete_url, {
                            method: "POST",
                            headers: { "X-CSRFToken": csrf() },
                        });
                        await load();
                    } catch (error) { window.alert(error.message); }
                });
                actions.append(edit, remove);
                card.appendChild(actions);
            }
            list.appendChild(card);
        });
    }
    async function load() {
        try {
            payload = await request(apiUrl);
            renderList();
            refreshUnreadCount();
            const messageId = new URLSearchParams(window.location.search).get("message_id");
            if (!initialMessageOpened && messageId) {
                initialMessageOpened = true;
                const target = payload.messages.find((item) => String(item.id) === messageId);
                if (target) await openMessage(target.url);
            }
        } catch (error) {
            list.textContent = error.message;
        }
    }
    async function openMessage(url) {
        detail.replaceChildren(node("p", "df-share-inbox-empty", "در حال دریافت پیام..."));
        try {
            const message = await request(url);
            detail.replaceChildren();
            detail.appendChild(node("h2", "", message.subject || "پیام اشتراک‌گذاری فایل"));
            detail.appendChild(node("p", "", "فرستنده: " + message.sender));
            detail.appendChild(node("p", "", "نوع تعامل: " + (interactionLabels[message.interaction_type] || message.interaction_type)));
            detail.appendChild(node("p", "", "وضعیت: " + (statusLabels[message.status] || message.status)));
            if (message.body) detail.appendChild(node("p", "", message.body));
            if (message.unavailable) {
                detail.appendChild(node(
                    "p",
                    "df-share-inbox-empty",
                    message.unavailable_message || "این پیام دیگر فعال نیست و فایل آن قابل دریافت نیست."
                ));
                refreshUnreadCount();
                return;
            }
            appendFileDetails(message);
            const download = node("a", "df-share-inbox-file", "دانلود فایل: " + message.file_name);
            download.href = message.download_url;
            download.setAttribute("download", "");
            detail.appendChild(download);
            const actions = node("div", "df-share-inbox-actions");
            if (message.interaction_type !== "VIEW" &&
                ["PENDING", "READ"].includes(message.status)) {
                const response = node("textarea", "df-share-inbox-response");
                response.placeholder = "پاسخ خود را بنویسید...";
                response.setAttribute("aria-label", "متن پاسخ");
                detail.appendChild(response);
                const send = node("button", "df-button df-button-primary", "ارسال پاسخ");
                send.type = "button";
                send.addEventListener("click", async () => {
                    try {
                        await request(url + "respond/", {
                            method: "POST",
                            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
                            body: JSON.stringify({ response: response.value }),
                        });
                        await load();
                        await openMessage(url);
                    } catch (error) { setFeedback(error.message); }
                });
                actions.appendChild(send);
            }
            if (message.status === "RESPONDED") {
                const complete = node("button", "df-button df-button-primary", "تکمیل درخواست");
                complete.type = "button";
                complete.addEventListener("click", async () => {
                    try {
                        await request(url + "complete/", {
                            method: "POST",
                            headers: { "X-CSRFToken": csrf() },
                        });
                        await load();
                        await openMessage(url);
                    } catch (error) { setFeedback(error.message); }
                });
                actions.appendChild(complete);
            }
            detail.appendChild(actions);
            const feedback = node("p", "df-share-inbox-meta", "");
            feedback.dataset.shareFeedback = "1";
            detail.appendChild(feedback);
            refreshUnreadCount();
        } catch (error) {
            detail.replaceChildren(node("p", "df-share-inbox-empty", error.message));
        }
    }
    async function recallMessage(url) {
        if (!window.confirm("این پیام لغو شود؟")) return;
        try {
            await request(url, { method: "POST", headers: { "X-CSRFToken": csrf() } });
            await load();
            detail.replaceChildren(node("p", "df-share-inbox-empty", "پیام لغو شد."));
        } catch (error) {
            detail.replaceChildren(node("p", "df-share-inbox-empty", error.message));
        }
    }
    tabs.forEach((tab) => tab.addEventListener("click", () => {
        activeTab = tab.dataset.shareTab;
        renderList();
        detail.replaceChildren(node("h2", "", "جزئیات پیام"),
            node("p", "df-share-inbox-empty", "برای مشاهده جزئیات، یک پیام را انتخاب کنید."));
    }));
    load();
});
