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

/*
 * ---------------------------------------------------------
 * Notification Alerts
 * ---------------------------------------------------------
 */

let knownNotificationIds = new Set();

let notificationAudioUnlocked = false;

let notificationsInitialized = false;

async function requestNotificationPermission() {

    if (!("Notification" in window)) {
        console.warn(
            "Browser Notification API is not supported."
        );
        return false;
    }

    if (Notification.permission === "granted") {
        return true;
    }

    if (Notification.permission === "denied") {
        console.warn(
            "Browser notifications are blocked."
        );
        return false;
    }

    const permission =
        await Notification.requestPermission();

    return permission === "granted";
}

/*
 * Unlock browser audio after user interaction.
 */

function unlockNotificationAudio() {

    notificationAudioUnlocked = true;
}
document.addEventListener(
    "click",
    unlockNotificationAudio,
    {
        once: true,
    }
);



/*
 * Play notification sound.
 */

function playNotificationSound() {

    if (!notificationAudioUnlocked) {
        return;
    }

    const audio = new Audio(
        "/static/operator_panel/audio/notification.mp3"
    );

    audio.volume = 0.7;

    audio.play().catch((error) => {

        console.warn(
            "Notification sound could not be played:",
            error
        );

    });

}


/*
 * Speak notification message.
 */



/*
 * Trigger alert for a new notification.
 */

function triggerNotificationAlert(notification) {

    if (!notification) {
        return;
    }

    playNotificationSound();

    console.log(
        "=== TRIGGER NOTIFICATION ALERT ===",
        {
            hidden: document.hidden,
            permission:
                "Notification" in window
                    ? Notification.permission
                    : "unsupported",
            supported:
                "Notification" in window,
            notification: notification,
        }
    );

    if (
        document.hidden &&
        "Notification" in window &&
        Notification.permission === "granted"
    ) {

        console.log(
            "=== CREATING DESKTOP NOTIFICATION ===",
            notification
        );

        const desktopNotification = new Notification(
            notification.title || "Dolphin Flow",
            {
                body:
                    notification.message ||
                    "You have a new notification.",
            }
        );

        desktopNotification.onshow = () => {
            console.log("=== DESKTOP NOTIFICATION SHOWN ===");
        };

        desktopNotification.onerror = (event) => {
            console.error(
                "=== DESKTOP NOTIFICATION ERROR ===",
                event
            );
        };

        desktopNotification.onclose = () => {
            console.log(
                "=== DESKTOP NOTIFICATION CLOSED ==="
            );
        };

    }

}

/*
 * ---------------------------------------------------------
 * Notification WebSocket
 * ---------------------------------------------------------
 */

let notificationSocket = null;
let notificationSocketReconnectTimer = null;

function connectNotificationWebSocket() {

    if (
        notificationSocket &&
        (
            notificationSocket.readyState === WebSocket.OPEN ||
            notificationSocket.readyState === WebSocket.CONNECTING
        )
    ) {
        return;
    }

    const protocol =
        window.location.protocol === "https:"
            ? "wss:"
            : "ws:";

    const socketUrl =
        `${protocol}//${window.location.host}/ws/notifications/`;

    notificationSocket = new WebSocket(
        socketUrl
    );

    notificationSocket.addEventListener(
        "open",
        () => {

            console.log(
                "Notification WebSocket connected."
            );

        }
    );

    notificationSocket.addEventListener(
        "message",
        (event) => {

            try {

                const notification =
                    JSON.parse(event.data);

                console.log(
                    "Notification received:",
                    notification
                );
                
                handleIncomingNotification(
                    notification
                );    

            } catch (error) {

                console.warn(
                    "Invalid notification WebSocket payload:",
                    error
                );

            }

        }
    );

    notificationSocket.addEventListener(
        "close",
        (event) => {

            console.error(
                "!!! NOTIFICATION SOCKET CLOSED !!!",
                {
                    code: event.code,
                    reason: event.reason,
                    wasClean: event.wasClean,
                    visibility: document.visibilityState,
                }
            );

            console.warn(
                "Notification WebSocket disconnected.",
                {
                    code: event.code,
                    reason: event.reason,
                    wasClean: event.wasClean,
                }
            );

        }
    );

    notificationSocket.addEventListener(
        "error",
        (error) => {

            console.warn(
                "Notification WebSocket error:",
                error
            );

        }
    );
}

function handleIncomingNotification(notification) {

    if (
        !notification ||
        !notification.id
    ) {
        return;
    }

    if (
        knownNotificationIds.has(
            notification.id
        )
    ) {
        return;
    }

    knownNotificationIds.add(
        notification.id
    );

    triggerNotificationAlert(
        notification
    );

    loadNotifications();
}

connectNotificationWebSocket();

/*
 * Notification menu
 */

function closeNotificationMenu() {

    notificationMenu.classList.remove("open");

    notificationToggle.setAttribute(
        "aria-expanded",
        "false"
    );

    notificationMenu.setAttribute(
        "aria-hidden",
        "true"
    );
}


function openNotificationMenu() {

    notificationMenu.classList.add("open");

    notificationToggle.setAttribute(
        "aria-expanded",
        "true"
    );

    notificationMenu.setAttribute(
        "aria-hidden",
        "false"
    );
}


/*
 * Open / close notification menu
 */

notificationToggle.addEventListener("click", async (event) => {

    event.stopPropagation();

    const isOpen =
        notificationMenu.classList.contains("open");

    if (isOpen) {

        closeNotificationMenu();

        return;
    }

    await requestNotificationPermission();

    openNotificationMenu();

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

        closeNotificationMenu();

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

            console.warn(
                "Unable to refresh notifications:",
                error
            );


        }
    }
    /*
    * ---------------------------------------------------------
    * Notification Polling
    * ---------------------------------------------------------
    */

    const NOTIFICATION_POLL_INTERVAL = 10000;

    let notificationPollingTimer = null;
    let notificationPollingInProgress = false;


    /*
    * Poll notifications safely.
    */

    async function pollNotifications() {

        /*
        * Prevent overlapping requests.
        */

        if (notificationPollingInProgress) {
            scheduleNotificationPolling();
            return;
        }


        /*
        * Do not poll while the page is hidden.
        */

        if (document.hidden) {
            scheduleNotificationPolling();
            return;
        }


        notificationPollingInProgress = true;


        try {

            await loadNotifications();

        } catch (error) {

            /*
            * Network errors should not break
            * the notification UI.
            */

            console.warn(
                "Notification polling temporarily unavailable."
            );

        } finally {

            notificationPollingInProgress = false;

            scheduleNotificationPolling();

        }

    }


    /*
    * Schedule the next polling request.
    */

    function scheduleNotificationPolling() {

        if (notificationPollingTimer) {

            clearTimeout(
                notificationPollingTimer
            );

        }


        notificationPollingTimer = setTimeout(
            pollNotifications,
            NOTIFICATION_POLL_INTERVAL
        );

    }


    /*
    * Immediately refresh notifications
    * when the user returns to the tab.
    */

    document.addEventListener(
        "visibilitychange",
        () => {

            console.log("=== VISIBILITY CHANGE ===");

            console.log({
                visibility: document.visibilityState,
                hidden: document.hidden,
                socketState: notificationSocket?.readyState,
                socketStateName: {
                    0: "CONNECTING",
                    1: "OPEN",
                    2: "CLOSING",
                    3: "CLOSED",
                }[notificationSocket?.readyState],
            });


            if (!document.hidden) {

                pollNotifications();

            }

        }
    );


    /*
    * Initial notification load.
    */

    pollNotifications();

    /*
     * Render notifications
     */

    function renderNotifications(data) {

        const notifications = data.notifications || [];

        const count = data.count || 0;


        /*
        * Detect newly received notifications.
        */

        const newNotifications = [];

        notifications.forEach((notification) => {

            if (
                !knownNotificationIds.has(
                    notification.id
                )
            ) {

                newNotifications.push(
                    notification
                );

                knownNotificationIds.add(
                    notification.id
                );

            }

        });

         /*
         * First load only initializes known IDs.
         */

        if (!notificationsInitialized) {

            notificationsInitialized = true;

        } else {

            newNotifications.forEach(
                (notification) => {

                    triggerNotificationAlert(
                        notification
                    );

                }
            );

        }


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
                        role="button"
                        tabindex="0"
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

    async function markNotificationAsRead(notificationItem) {

        const notificationId =
            notificationItem.dataset.notificationId;

        if (!notificationId) {
            return;
        }

        const notificationsUrl =
            notificationToggle.dataset.notificationsUrl;

        const readUrl =
            `${notificationsUrl}${notificationId}/read/`;

        try {

            const response = await fetch(
                readUrl,
                {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": getCsrfToken(),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                }
            );

            if (!response.ok) {
                throw new Error(
                    "Unable to mark notification as read."
                );
            }

            const data = await response.json();

            if (!data.success) {
                throw new Error(
                    "Notification was not marked as read."
                );
            }

            /*
            * Remove notification from current unread list.
            */

            notificationItem.remove();


            /*
            * Update badge and count.
            */

            const currentCount =
                Number(
                    notificationBadge.textContent
                ) || 0;

            const newCount =
                Math.max(currentCount - 1, 0);


            if (newCount > 0) {

                notificationBadge.textContent =
                    newCount;

                notificationBadge.hidden = false;

            } else {

                notificationBadge.textContent = "0";
                notificationBadge.hidden = true;

            }


            notificationCount.textContent =
                `${newCount} اعلان`;


        /*
         * Empty state
         */

        if (
            notificationList.children.length === 0
        ) {

            notificationList.innerHTML = `
                <div class="df-notification-empty">
                    اعلان جدیدی ندارید.
                </div>
            `;

        }

    } catch (error) {

        console.error(
            "Mark notification as read error:",
            error
        );

    }
}

    function getCsrfToken() {

        const cookie = document.cookie
            .split("; ")
            .find(
                row => row.startsWith("csrftoken=")
            );

        if (!cookie) {
            return "";
        }

        return decodeURIComponent(
            cookie.split("=")[1]
        );
    }

    notificationList.addEventListener(
        "click",
        async (event) => {

            const notificationItem =
                event.target.closest(
                    ".df-notification-item"
                );

            if (!notificationItem) {
                return;
            }

            await markNotificationAsRead(
                notificationItem
            );

        }
    );

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