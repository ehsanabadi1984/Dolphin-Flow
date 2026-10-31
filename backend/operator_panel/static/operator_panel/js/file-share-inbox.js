document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("df-share-inbox");
    if (!root) return;
    const apiUrl = root.dataset.apiUrl;
    const list = document.getElementById("df-share-inbox-items");
    const detail = document.getElementById("df-share-inbox-detail");
    const tabs = Array.from(root.querySelectorAll("[data-share-tab]"));
    let payload = { messages: [], sent_messages: [], drafts: [] };
    let activeTab = "received";

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
            card.appendChild(node("strong", "", item.subject || item.file_name || "بدون موضوع"));
            card.appendChild(node("span", "df-share-inbox-meta",
                activeTab === "received" ? "فرستنده: " + item.sender : "گیرنده: " + item.recipient));
            card.appendChild(node("span", "df-share-inbox-meta",
                "وضعیت: " + (item.status || "پیش‌نویس") + (item.file_name ? " · " + item.file_name : "")));
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
            }
            list.appendChild(card);
        });
    }
    async function request(url, options) {
        const response = await fetch(url, {
            credentials: "same-origin",
            headers: { "Accept": "application/json", ...(options && options.headers || {}) },
            ...(options || {}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "انجام عملیات ناموفق بود.");
        return data;
    }
    async function load() {
        try {
            payload = await request(apiUrl);
            renderList();
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
            detail.appendChild(node("p", "", "نوع تعامل: " + message.interaction_type));
            detail.appendChild(node("p", "", "وضعیت: " + message.status));
            if (message.body) detail.appendChild(node("p", "", message.body));
            const download = node("a", "df-share-inbox-file", "دانلود فایل: " + message.file_name);
            download.href = message.download_url;
            download.setAttribute("download", "");
            detail.appendChild(download);
            if (message.form_snapshot && Object.keys(message.form_snapshot).length) {
                detail.appendChild(node("h3", "", "اطلاعات ثبت‌شده همراه پیام"));
                const snapshot = node("pre", "df-share-inbox-snapshot",
                    JSON.stringify(message.form_snapshot, null, 2));
                detail.appendChild(snapshot);
            }
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
            detail.appendChild(node("p", "df-share-inbox-meta", ""));
            const feedback = node("p", "df-share-inbox-meta", "");
            feedback.dataset.shareFeedback = "1";
            detail.appendChild(feedback);
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
