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
 * ---------------------------------------------------------
 * Device Table + Add/Edit Modal
 * ---------------------------------------------------------
 */
(() => {

    const getModal = (groupCode) => {
        return document.querySelector(
            `.df-device-modal[data-device-modal="${groupCode}"]`
        );
    };

    const openModal = (modal) => {
        if (!modal) return;

        modal.hidden = false;
        document.body.classList.add("df-modal-open");

        const firstField = modal.querySelector(
            "[data-device-modal-field]"
        );

        firstField?.focus();
    };

    const closeModal = (modal) => {
        if (!modal) return;

        modal.hidden = true;
        document.body.classList.remove("df-modal-open");
    };

    const clearModalErrors = (modal) => {
        modal.querySelectorAll(
            ".df-device-modal-field"
        ).forEach((field) => {
            field.classList.remove("has-error");

            const error = field.querySelector(
                ".df-device-modal-error"
            );

            if (error) {
                error.textContent = "";
            }
        });
    };

    const resetModal = (modal) => {

        modal.querySelectorAll(
            "[data-device-modal-field]"
        ).forEach((field) => {

            if (
                field.tagName === "SELECT"
                || field.tagName === "TEXTAREA"
                || field.tagName === "INPUT"
            ) {
                if (field.type === "checkbox") {
                    field.checked = false;
                } else {
                    field.value = "";
                }
                field.disabled = false;
            }

        });

        clearModalErrors(modal);
    };

        const lookupDeviceByImei = async (modal) => {

        const imeiWrapper =
            modal.querySelector(
                '.df-device-modal-field[data-system-key="IMEI"]'
            );

        const imeiField =
            imeiWrapper?.querySelector(
                '[data-device-modal-field]'
            );

        if (!imeiField) {
            return;
        }

        const imei =
            imeiField.value.trim();

        if (!imei) {
            return;
        }

        const lookupUrl =
            modal.dataset.deviceLookupUrl;

        if (!lookupUrl) {
            console.warn(
                "Device lookup URL is not configured."
            );
            return;
        }

        try {

            const response =
                await fetch(
                    `${lookupUrl}?imei=${encodeURIComponent(imei)}`,
                    {
                        method: "GET",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    }
                );

            if (!response.ok) {
                throw new Error(
                    "Device lookup failed."
                );
            }

            const data =
                await response.json();

            const typeWrapper =
                modal.querySelector(
                    '.df-device-modal-field[data-system-key="DEVICE_TYPE"]'
                );

            const typeField =
                typeWrapper?.querySelector(
                    '[data-device-modal-field]'
                );

            const modelWrapper =
                modal.querySelector(
                    '.df-device-modal-field[data-system-key="DEVICE_MODEL"]'
                );

            const modelField =
                modelWrapper?.querySelector(
                    '[data-device-modal-field]'
                );

            if (!typeField || !modelField) {
                return;
            }

            if (data.exists) {

                /*
                 * Existing device.
                 *
                 * Type and Model are taken from
                 * the persistent Device record.
                 */

                typeField.value =
                    String(data.device_type_id);

                typeField.disabled = true;

                modelField.value =
                    String(data.device_model_id);

                modelField.disabled = true;

            } else {

                /*
                 * New device.
                 *
                 * Operator selects Type and Model.
                 */

                typeField.value = "";
                typeField.disabled = false;

                modelField.value = "";
                modelField.disabled = false;
            }

        } catch (error) {

            console.error(
                "Unable to lookup device by IMEI:",
                error
            );
        }
    };

    const validateModal = (modal) => {

        clearModalErrors(modal);

        let firstError = null;

        modal.querySelectorAll(
            ".df-device-modal-field"
        ).forEach((wrapper) => {

            const field = wrapper.querySelector(
                "[data-device-modal-field]"
            );

            if (!field) return;

            const required =
                wrapper.querySelector("label span");

            if (!required) return;

            if (!field.value.trim()) {

                wrapper.classList.add("has-error");

                const error =
                    wrapper.querySelector(
                        ".df-device-modal-error"
                    );

                if (error) {
                    error.textContent =
                        "این فیلد الزامی است.";
                }

                if (!firstError) {
                    firstError = field;
                }
            }

        });

        if (firstError) {
            firstError.focus();
            return false;
        }

        return true;
    };

const submitNewDevice = (modal, groupCode) => {

    if (!validateModal(modal)) {
        return;
    }

    const form = document.querySelector(
        ".workflow-instance form"
    );

    if (!form) {
        return;
    }

    const tbody = form.querySelector(
        `.df-device-table-body[data-group-code="${groupCode}"]`
    );

    if (!tbody) {
        return;
    }

    const existingRows = tbody.querySelectorAll(
        "[data-device-row]"
    );

    const newIndex = existingRows.length;

    const row = document.createElement("tr");

    row.className = "df-device-row";
    row.dataset.deviceRow = "";
    row.dataset.deviceIndex = newIndex;

    /*
     * Hidden InstanceDevice ID
     */
    const instanceDeviceId =
        document.createElement("input");

    instanceDeviceId.type = "hidden";
    instanceDeviceId.name =
        `${groupCode}_${newIndex}_instance_device_id`;
    instanceDeviceId.value = "";

    /*
     * Device fields
     */
    const fields = modal.querySelectorAll(
        "[data-device-modal-field]"
    );

    fields.forEach((field) => {

        const fieldCode =
            field.dataset.fieldCode;

        if (!fieldCode) {
            return;
        }

        const cell = document.createElement("td");

        /*
         * Display value
         */
        const display =
            document.createElement("span");

        display.className =
            "df-device-display";

        if (field.tagName === "SELECT") {

            const selected =
                field.options[field.selectedIndex];

            display.textContent =
                selected
                    ? selected.textContent
                    : "—";

        } else {

            display.textContent =
                field.value || "—";

        }

        cell.appendChild(display);

        /*
         * Editor
         */
        const editor =
            document.createElement("span");

        editor.className =
            "df-device-editor";

        editor.hidden = true;

        const input =
            field.cloneNode(true);

        input.removeAttribute(
            "data-device-modal-field"
        );

        input.name =
            `${groupCode}_${newIndex}_${fieldCode}`;

        input.classList.add(
            "df-device-generated-field"
        );

        editor.appendChild(input);

        cell.appendChild(editor);

        row.appendChild(cell);
    });

    /*
     * Actions
     */
    const actionsCell =
        document.createElement("td");

    actionsCell.className =
        "df-device-actions";

    /*
     * Hidden instance_device_id
     */
    actionsCell.appendChild(
        instanceDeviceId
    );

    /*
     * Edit button
     */
    const editButton =
        document.createElement("button");

    editButton.type = "button";
    editButton.className =
        "df-button df-button-secondary df-device-edit";

    editButton.textContent = "ویرایش";

    actionsCell.appendChild(
        editButton
    );

    /*
     * Cancel button
     */
    const cancelButton =
        document.createElement("button");

    cancelButton.type = "button";
    cancelButton.className =
        "df-button df-button-secondary df-device-cancel";

    cancelButton.hidden = true;
    cancelButton.textContent = "انصراف";

    actionsCell.appendChild(
        cancelButton
    );

    /*
     * Save button
     */
    const saveButton =
        document.createElement("button");

    saveButton.type = "submit";
    saveButton.className =
        "df-button df-device-save";

    saveButton.hidden = true;
    saveButton.textContent = "ذخیره";

    actionsCell.appendChild(
        saveButton
    );

    /*
     * Delete button
     */
    const deleteButton =
        document.createElement("button");

    deleteButton.type = "button";
    deleteButton.className =
        "df-button df-button-danger df-device-delete";

    deleteButton.textContent = "حذف";

    actionsCell.appendChild(
        deleteButton
    );

    row.appendChild(actionsCell);

    /*
     * Add row in NORMAL display mode.
     */
    tbody.appendChild(row);

    /*
     * Modal is closed only.
     * The form is NOT submitted here.
     */
    closeModal(modal);
};
    const setDeviceRowEditing = (row, editing) => {

        row.classList.toggle(
            "is-editing",
            editing
        );

        row.querySelectorAll(
            ".df-device-display"
        ).forEach((element) => {
            element.hidden = editing;
        });

        row.querySelectorAll(
            ".df-device-editor"
        ).forEach((element) => {
            element.hidden = !editing;
        });

        row.querySelectorAll(
            ".df-device-edit, .df-device-delete"
        ).forEach((element) => {
            element.hidden = editing;
        });

        row.querySelectorAll(
            ".df-device-cancel, .df-device-save"
        ).forEach((element) => {
            element.hidden = !editing;
        });
    };

    document.addEventListener("click", (event) => {

        /*
         * ADD
         */
        const addButton =
            event.target.closest(".df-device-add");

        if (addButton) {

            const groupCode =
                addButton.dataset.groupCode;

            const modal =
                getModal(groupCode);

            if (!modal) return;

            resetModal(modal);
            openModal(modal);

            return;
        }

        /*
         * MODAL CLOSE
         */
        const closeButton =
            event.target.closest(
                ".df-device-modal-close, .df-device-modal-cancel"
            );

        if (closeButton) {

            const modal =
                event.target.closest(".df-device-modal");

            closeModal(modal);

            return;
        }

        /*
         * MODAL BACKDROP
         */
        if (
            event.target.classList.contains(
                "df-device-modal-backdrop"
            )
        ) {

            const modal =
                event.target.closest(".df-device-modal");

            closeModal(modal);

            return;
        }

        /*
         * MODAL SUBMIT
         */
        const modalSubmit =
            event.target.closest(
                ".df-device-modal-submit"
            );

        if (modalSubmit) {

            const groupCode =
                modalSubmit.dataset.groupCode;

            const modal =
                getModal(groupCode);

            if (!modal) return;

            submitNewDevice(
                modal,
                groupCode
            );

            return;
        }

        /*
         * EXISTING DEVICE ROW
         */
        const row =
            event.target.closest(
                "[data-device-row]"
            );

        if (!row) return;

        if (
            event.target.closest(
                ".df-device-edit"
            )
        ) {

            setDeviceRowEditing(
                row,
                true
            );

            return;
        }

        if (
            event.target.closest(
                ".df-device-cancel"
            )
        ) {

            const id =
                row.querySelector(
                    'input[name$="_instance_device_id"]'
                )?.value;

            if (!id) {
                row.remove();
            } else {
                setDeviceRowEditing(
                    row,
                    false
                );
            }

            return;
        }

        if (
            event.target.closest(
                ".df-device-delete"
            )
        ) {

            if (
                !window.confirm(
                    "آیا از حذف این دستگاه از فرآیند مطمئن هستید؟"
                )
            ) {
                event.preventDefault();
            }

        }

        });

})();

/*
 * Device IMEI lookup
 */

document.addEventListener(
    "change",
    async (event) => {

        const imeiField =
            event.target.closest(
                '[data-device-modal-field][data-system-key="IMEI"]'
            );

        if (!imeiField) {
            return;
        }

        const modal =
            imeiField.closest(
                ".df-device-modal"
            );

        if (!modal) {
            return;
        }

        const imei =
            imeiField.value.trim();

        if (!imei) {
            return;
        }

        const lookupUrl =
            modal.dataset.deviceLookupUrl;

        if (!lookupUrl) {
            console.warn(
                "Device lookup URL is not configured."
            );
            return;
        }

        try {

            const response =
                await fetch(
                    `${lookupUrl}?imei=${encodeURIComponent(imei)}`,
                    {
                        method: "GET",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    }
                );

            if (!response.ok) {
                throw new Error(
                    "Device lookup failed."
                );
            }

            const data =
                await response.json();

            console.log(
                "IMEI LOOKUP RESULT:",
                data
            );

            const typeField =
                modal.querySelector(
                    '[data-device-modal-field][data-system-key="DEVICE_TYPE"]'
                );

            const modelField =
                modal.querySelector(
                    '[data-device-modal-field][data-system-key="DEVICE_MODEL"]'
                );

            if (!typeField || !modelField) {
                return;
            }

            if (data.exists) {

                typeField.value =
                    String(data.device_type_id);

                typeField.disabled = true;

                modelField.value =
                    String(data.device_model_id);

                modelField.disabled = true;

            } else {

                typeField.value = "";
                typeField.disabled = false;

                modelField.value = "";
                modelField.disabled = false;
            }

        } catch (error) {

            console.error(
                "Unable to lookup device by IMEI:",
                error
            );
        }
    }
);
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


    /*
 * ---------------------------------------------------------
 * Repeatable Groups
 * ---------------------------------------------------------
 */

document.addEventListener("click", (event) => {

    const addButton = event.target.closest(
        ".df-repeatable-add"
    );

    if (!addButton) {
        return;
    }

    const groupCode =
        addButton.dataset.groupCode;

    if (!groupCode) {
        console.error(
            "Repeatable group code not found."
        );

        return;
    }

    const group =
        document.querySelector(
            `.df-repeatable-group[data-repeatable-group="${groupCode}"]`
        );

    if (!group) {
        console.error(
            "Repeatable group not found:",
            groupCode
        );

        return;
    }

    const itemsContainer =
        group.querySelector(
            ".df-repeatable-items"
        );

    if (!itemsContainer) {
        console.error(
            "Repeatable items container not found:",
            groupCode
        );

        return;
    }

    const items =
        itemsContainer.querySelectorAll(
            "[data-repeatable-item]:not([data-repeatable-template])"
        );

    /*
     * ---------------------------------------------------------
     * Find source item
     * ---------------------------------------------------------
     *
     * For an existing group, clone the last real item.
     *
     * For an empty group, use the server-rendered template.
     */

    let sourceItem;

    if (items.length > 0) {

        sourceItem =
            items[items.length - 1];

    } else {

        sourceItem =
            itemsContainer.querySelector(
                "[data-repeatable-item][data-repeatable-template]"
            );

        if (!sourceItem) {
            console.error(
                "No repeatable item or template available:",
                groupCode
            );

            return;
        }
    }

    /*
     * Clone the source.
     */

    const newItem =
        sourceItem.cloneNode(true);

    /*
     * This is now a real item, not a template.
     */

    newItem.removeAttribute(
        "data-repeatable-template"
    );
    newItem.style.display = "";

    /*
     * ---------------------------------------------------------
     * Calculate new index
     * ---------------------------------------------------------
     */

    const newIndex =
        items.length;

    /*
     * ---------------------------------------------------------
     * Update fields
     * ---------------------------------------------------------
     */

    const fields =
        newItem.querySelectorAll(
            "input, textarea, select"
        );

    fields.forEach((field) => {

        const oldName =
            field.getAttribute("name");

        /*
         * Replace only the numeric repeatable index.
         *
         * Example:
         *
         * devices_0_imei
         * devices_1_imei
         */

        if (oldName) {

            const prefix =
                `${groupCode}_`;

            if (oldName.startsWith(prefix)) {

                const remainder =
                    oldName.slice(prefix.length);

                const separatorIndex =
                    remainder.indexOf("_");

                if (separatorIndex !== -1) {

                    const fieldCode =
                        remainder.slice(
                            separatorIndex + 1
                        );

                    field.name =
                        `${groupCode}_${newIndex}_${fieldCode}`;
                }
            }
        }

        /*
         * -----------------------------------------------------
         * IDs
         * -----------------------------------------------------
         */

        const oldId =
            field.getAttribute("id");

        if (oldId) {

            const newId =
                oldId.replace(
                    /-\d+-/,
                    `-${newIndex}-`
                );

            field.id = newId;
        }

        /*
         * -----------------------------------------------------
         * IMPORTANT:
         * A cloned item is ALWAYS a new item.
         *
         * Therefore instance_device_id MUST be empty.
         * -----------------------------------------------------
         */

        if (
            field.type === "hidden" &&
            oldName &&
            oldName.endsWith("_instance_device_id")
        ) {

            field.value = "";

            return;
        }

        /*
         * -----------------------------------------------------
         * Clear normal values
         * -----------------------------------------------------
         */

        if (
            field.type === "checkbox" ||
            field.type === "radio"
        ) {

            field.checked = false;

        } else if (
            field.tagName === "SELECT"
        ) {

            field.selectedIndex = 0;

        } else {

            field.value = "";
        }
    });

    /*
     * ---------------------------------------------------------
     * Update label references
     * ---------------------------------------------------------
     */

    const labels =
        newItem.querySelectorAll(
            "label[for]"
        );

    labels.forEach((label) => {

        const oldFor =
            label.getAttribute("for");

        if (!oldFor) {
            return;
        }

        const newFor =
            oldFor.replace(
                /-\d+-/,
                `-${newIndex}-`
            );

        label.setAttribute(
            "for",
            newFor
        );
    });

    /*
     * ---------------------------------------------------------
     * Remove empty-state message
     * ---------------------------------------------------------
     */

    const emptyState =
        itemsContainer.querySelector(
            ".df-empty-state"
        );

    if (emptyState) {
        emptyState.remove();
    }

    /*
     * ---------------------------------------------------------
     * Append the new item
     * ---------------------------------------------------------
     */

    itemsContainer.appendChild(
        newItem
    );

    console.log(
        "Repeatable item added:",
        {
            groupCode,
            index: newIndex,
        }
    );
});
});
