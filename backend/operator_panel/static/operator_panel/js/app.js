document.addEventListener("DOMContentLoaded", () => {

    /*
     * ---------------------------------------------------------
     * Sidebar
     * ---------------------------------------------------------
     */

    const layout = document.querySelector(".df-layout");
    const toggle = document.getElementById("df-sidebar-toggle");

    if (layout && toggle) {
        toggle.addEventListener("click", () => {
            layout.classList.toggle("sidebar-collapsed");
        });
    }


    /*
     * ---------------------------------------------------------
     * Notifications
     * ---------------------------------------------------------
     */

    const notificationToggle = document.getElementById(
        "df-notification-toggle"
    );

    const notificationMenu = document.getElementById(
        "df-notification-menu"
    );

    const notificationList = document.getElementById(
        "df-notification-list"
    );

    const notificationBadge = document.getElementById(
        "df-notification-badge"
    );

    const notificationCount = document.getElementById(
        "df-notification-menu-count"
    );


    if (
        !notificationToggle ||
        !notificationMenu ||
        !notificationList
    ) {
        return;
    }


    /*
     * Open / close notification menu
     */

    notificationToggle.addEventListener("click", async (event) => {

        event.stopPropagation();

        const isOpen = notificationMenu.classList.contains("open");

        if (isOpen) {
            notificationMenu.classList.remove("open");

            notificationToggle.setAttribute(
                "aria-expanded",
                "false"
            );

            return;
        }


        notificationMenu.classList.add("open");

        notificationToggle.setAttribute(
            "aria-expanded",
            "true"
        );


        await loadNotifications();

    });


    /*
     * Close when clicking outside
     */

    document.addEventListener("click", (event) => {

        if (
            !notificationMenu.contains(event.target) &&
            !notificationToggle.contains(event.target)
        ) {

            notificationMenu.classList.remove("open");

            notificationToggle.setAttribute(
                "aria-expanded",
                "false"
            );
        }

    });


    /*
     * Load notifications
     */

    async function loadNotifications() {

        try {

            const notificationsUrl =
                notificationToggle.dataset.notificationsUrl;

            const response = await fetch(
                notificationsUrl,
                {
                    method: "GET",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                    },
                }
            );


            if (!response.ok) {
                throw new Error(
                    "Notification request failed."
                );
            }


            const data = await response.json();

            renderNotifications(data);


        } catch (error) {

            console.error(
                "Notification loading error:",
                error
            );

            notificationList.innerHTML = `
                <div class="df-notification-empty">
                    دریافت اعلان‌ها با خطا مواجه شد.
                </div>
            `;

        }

    }

    loadNotifications();
    /*
     * Render notifications
     */

    function renderNotifications(data) {

        const notifications = data.notifications || [];

        const count = data.count || 0;


        /*
         * Badge
         */

        if (count > 0) {

            notificationBadge.textContent = count;

            notificationBadge.hidden = false;

        } else {

            notificationBadge.hidden = true;

        }


        /*
         * Header count
         */

        notificationCount.textContent =
            `${count} اعلان`;


        /*
         * Empty state
         */

        if (notifications.length === 0) {

            notificationList.innerHTML = `
                <div class="df-notification-empty">
                    اعلان جدیدی ندارید.
                </div>
            `;

            return;
        }


        /*
         * Notification items
         */

        notificationList.innerHTML = notifications
            .map((notification) => {

                return `
                    <div
                        class="df-notification-item"
                        data-notification-id="${notification.id}"
                    >

                        <div class="df-notification-item-title">
                            ${escapeHtml(notification.title)}
                        </div>

                        <div class="df-notification-item-message">
                            ${escapeHtml(notification.message)}
                        </div>

                        <div class="df-notification-item-meta">
                            ${formatNotificationDate(
                                notification.created_at
                            )}
                        </div>

                    </div>
                `;

            })
            .join("");

    }


    /*
     * Escape HTML
     *
     * Important:
     * Notification content comes from the database.
     * Never insert it into innerHTML without escaping.
     */

    function escapeHtml(value) {

        const div = document.createElement("div");

        div.textContent = value ?? "";

        return div.innerHTML;

    }


    /*
     * Format notification date
     */

    function formatNotificationDate(value) {

        if (!value) {
            return "";
        }


        const date = new Date(value);


        if (Number.isNaN(date.getTime())) {
            return "";
        }


        return date.toLocaleString(
            "fa-IR",
            {
                dateStyle: "short",
                timeStyle: "short",
            }
        );

    }

});