document.addEventListener("DOMContentLoaded", () => {
    const activeCount = document.getElementById("df-sidebar-active-count");
    const taskCount = document.getElementById("df-sidebar-task-count");
    const pendingCount = document.getElementById("df-sidebar-pending-count");

    function setCount(element, value) {
        if (!element) return;

        element.textContent = String(value);
        element.hidden = Number(value) === 0;
    }

    async function refreshSidebarCounts() {
        try {
            const response = await fetch(
                "/operator/dashboard/realtime/",
                {
                    method: "GET",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    credentials: "same-origin",
                    cache: "no-store",
                }
            );

            if (!response.ok) return;

            const data = await response.json();
            setCount(activeCount, data.active);
            setCount(taskCount, data.tasks);
            setCount(pendingCount, data.pending);
        } catch (error) {
            console.warn("Could not refresh workflow sidebar counts:", error);
        }
    }

    function handleWorkflowUpdate(event) {
        if (!event || event.type !== "workflow.updated") return;

        refreshSidebarCounts();

        if (document.querySelector("[data-dashboard-page='true']")) {
            window.location.reload();
        }
    }

    window.addEventListener("workflow.updated", (event) => {
        handleWorkflowUpdate(event.detail);
    });

    let socket = null;
    let reconnectTimer = null;

    function connectWorkflowSocket() {
        if (
            socket &&
            (socket.readyState === WebSocket.OPEN ||
                socket.readyState === WebSocket.CONNECTING)
        ) {
            return;
        }

        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(
            `${protocol}//${window.location.host}/ws/notifications/`
        );

        socket.addEventListener("message", (message) => {
            try {
                const payload = JSON.parse(message.data);

                if (payload && payload.type === "workflow.updated") {
                    window.dispatchEvent(
                        new CustomEvent("workflow.updated", {
                            detail: payload,
                        })
                    );
                }
            } catch (error) {
                console.warn("Invalid workflow realtime payload:", error);
            }
        });

        socket.addEventListener("close", () => {
            clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(connectWorkflowSocket, 3000);
        });
    }

    connectWorkflowSocket();
});
