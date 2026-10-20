(() => {
    "use strict";

    const fallbackImage = "/static/images/product-placeholder.svg";

    document.querySelectorAll("[data-menu-toggle]").forEach((button) => {
        const menu = document.getElementById(button.getAttribute("aria-controls"));
        if (!menu) return;
        button.addEventListener("click", () => {
            const isOpen = menu.classList.toggle("is-open");
            button.setAttribute("aria-expanded", String(isOpen));
        });
    });

    document.querySelectorAll("[data-password-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.getElementById(button.dataset.passwordToggle);
            if (!input) return;
            const show = input.type === "password";
            input.type = show ? "text" : "password";
            button.textContent = show ? "Hide" : "Show";
            button.setAttribute("aria-pressed", String(show));
        });
    });

    document.querySelectorAll("[data-dismiss]").forEach((button) => {
        button.addEventListener("click", () => button.closest(".flash")?.remove());
    });

    document.querySelectorAll("[data-image-fallback]").forEach((image) => {
        image.addEventListener("error", () => {
            if (image.dataset.fallbackApplied) return;
            image.dataset.fallbackApplied = "true";
            image.src = fallbackImage;
        });
    });

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm || "Continue with this action?")) {
                event.preventDefault();
            }
        });
    });

    document.querySelectorAll("form").forEach((form) => {
        form.addEventListener("submit", () => {
            if (!form.reportValidity()) return;
            const button = form.querySelector('button[type="submit"]');
            if (!button || button.disabled || form.dataset.confirm) return;
            button.disabled = true;
            button.classList.add("is-loading");
            button.setAttribute("aria-busy", "true");
            button.textContent = "Please wait…";
        });
    });

    const scheduleItems = [...document.querySelectorAll("[data-auction-id]")];
    const countdowns = [...document.querySelectorAll("[data-countdown]")];
    const formatCountdown = (target, mode) => {
        const remaining = new Date(target).getTime() - Date.now();
        if (!Number.isFinite(remaining)) return "Schedule unavailable";
        if (remaining <= 0) return mode === "start" ? "Starting now" : "Auction ended";
        const totalSeconds = Math.floor(remaining / 1000);
        const days = Math.floor(totalSeconds / 86400);
        const hours = Math.floor((totalSeconds % 86400) / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        if (days > 0) return `${days}d ${hours}h left`;
        if (hours > 0) return `${hours}h ${minutes}m left`;
        if (minutes > 0) return `${minutes}m ${seconds}s left`;
        return `${seconds}s left`;
    };
    const updateCountdowns = () => countdowns.forEach((item) => {
        item.textContent = formatCountdown(item.dataset.countdown, item.dataset.countdownMode);
    });
    if (countdowns.length) {
        updateCountdowns();
        window.setInterval(updateCountdowns, 1000);
    }

    const refreshSchedules = async () => {
        if (!scheduleItems.length) return;
        const endpoint = scheduleItems.find((item) => item.dataset.scheduleUrl)?.dataset.scheduleUrl;
        if (!endpoint) return;
        const ids = [...new Set(scheduleItems.map((item) => item.dataset.auctionId).filter(Boolean))].slice(0, 100);
        if (!ids.length) return;
        const url = new URL(endpoint, window.location.href);
        ids.forEach((id) => url.searchParams.append("id", id));
        try {
            const response = await fetch(url, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                cache: "no-store",
            });
            if (!response.ok) return;
            const schedules = await response.json();
            let statusChanged = false;
            scheduleItems.forEach((item) => {
                const schedule = schedules[item.dataset.auctionId];
                if (!schedule) return;
                if (item.hasAttribute("data-auction-status")) {
                    const oldStatus = item.textContent.trim();
                    if (oldStatus && oldStatus !== schedule.status) statusChanged = true;
                    item.classList.remove("status-live", "status-upcoming", "status-ended");
                    item.classList.add(`status-${schedule.status.toLowerCase()}`);
                    item.lastChild.textContent = schedule.status;
                }
                if (item.hasAttribute("data-auction-status-label")) {
                    item.textContent = schedule.status === "Upcoming"
                        ? "Starts in"
                        : schedule.status === "Ended" ? "Ended" : "Time remaining";
                }
                if (item.hasAttribute("data-countdown")) {
                    item.dataset.countdownMode = schedule.status === "Upcoming" ? "start" : "end";
                    item.dataset.countdown = schedule.status === "Upcoming" ? schedule.start_time : schedule.end_time;
                }
                if (item.hasAttribute("data-auction-closing-time")) {
                    item.textContent = `${item.dataset.auctionClosingPrefix || ""}${schedule.closing_display}`;
                }
                if (item.hasAttribute("data-open-auction-time")) {
                    item.dataset.endTime = schedule.end_time;
                    item.dataset.endDisplay = schedule.closing_display;
                    item.dataset.endValue = schedule.end_value;
                    item.dataset.status = schedule.status;
                }
            });
            if (statusChanged) window.location.reload();
            else updateCountdowns();
        } catch (_error) {
            // Keep the current countdown running when the schedule service is briefly unavailable.
        }
    };
    if (scheduleItems.length) {
        refreshSchedules();
        window.setInterval(refreshSchedules, 5000);
    }

    const auctionTimeModal = document.querySelector("[data-auction-time-modal]");
    const auctionTimeForm = document.querySelector("[data-auction-time-form]");
    if (auctionTimeModal && auctionTimeForm) {
        const auctionName = auctionTimeModal.querySelector("#auction-time-title");
        const auctionStart = auctionTimeModal.querySelector("[data-modal-start]");
        const auctionClosing = auctionTimeModal.querySelector("[data-modal-closing]");
        const auctionStatus = auctionTimeModal.querySelector("[data-modal-auction-status]");
        const auctionCountdown = auctionTimeModal.querySelector("[data-countdown]");
        const closingInput = auctionTimeForm.querySelector('[name="end_time"]');
        const message = auctionTimeModal.querySelector("[data-auction-time-message]");
        const saveButton = auctionTimeForm.querySelector('button[type="submit"]');
        let lastTrigger = null;

        const closeModal = () => {
            auctionTimeModal.hidden = true;
            document.body.classList.remove("modal-open");
            lastTrigger?.setAttribute("aria-expanded", "false");
            lastTrigger?.focus();
        };

        document.querySelectorAll("[data-open-auction-time]").forEach((button) => {
            button.addEventListener("click", () => {
                lastTrigger = button;
                button.setAttribute("aria-expanded", "true");
                auctionName.textContent = button.dataset.productName;
                auctionStart.textContent = button.dataset.startDisplay;
                auctionClosing.textContent = button.dataset.endDisplay;
                auctionStatus.textContent = button.dataset.status;
                auctionStatus.className = `auction-time-status status-${button.dataset.status.toLowerCase()}`;
                auctionStatus.dataset.auctionId = button.dataset.auctionId;
                auctionStatus.dataset.scheduleUrl = button.dataset.scheduleUrl;
                auctionClosing.dataset.auctionId = button.dataset.auctionId;
                auctionClosing.dataset.scheduleUrl = button.dataset.scheduleUrl;
                auctionCountdown.dataset.auctionId = button.dataset.auctionId;
                auctionCountdown.dataset.scheduleUrl = button.dataset.scheduleUrl;
                auctionCountdown.dataset.countdown = button.dataset.endTime;
                auctionTimeForm.action = button.dataset.action;
                closingInput.value = button.dataset.endValue;
                message.hidden = true;
                message.textContent = "";
                const ended = button.dataset.status === "Ended";
                closingInput.disabled = ended;
                saveButton.disabled = ended;
                if (ended) {
                    message.textContent = "This auction has ended. Its schedule cannot be changed or reopened.";
                    message.className = "auction-time-message is-error";
                    message.hidden = false;
                }
                auctionTimeModal.hidden = false;
                document.body.classList.add("modal-open");
                updateCountdowns();
                auctionTimeModal.querySelector(".auction-time-close").focus();
            });
        });

        auctionTimeModal.querySelectorAll("[data-close-auction-time]").forEach((button) => {
            button.addEventListener("click", closeModal);
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !auctionTimeModal.hidden) closeModal();
        });

        auctionTimeForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            message.hidden = true;
            saveButton.disabled = true;
            saveButton.textContent = "Saving…";
            try {
                const response = await fetch(auctionTimeForm.action, {
                    method: "POST",
                    body: new FormData(auctionTimeForm),
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                    cache: "no-store",
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || "We could not update this auction's closing time.");

                auctionClosing.textContent = result.closing_display;
                auctionStatus.textContent = result.status;
                auctionStatus.className = `auction-time-status status-${result.status.toLowerCase()}`;
                auctionCountdown.dataset.countdown = result.end_time;
                if (lastTrigger) {
                    lastTrigger.dataset.endTime = result.end_time;
                    lastTrigger.dataset.endDisplay = result.closing_display;
                    lastTrigger.dataset.endValue = result.end_value;
                    lastTrigger.dataset.status = result.status;
                }
                message.textContent = "Auction closing time updated.";
                message.className = "auction-time-message is-success";
                message.hidden = false;
                updateCountdowns();
                refreshSchedules();
            } catch (error) {
                message.textContent = error.message || "We could not update this auction's closing time.";
                message.className = "auction-time-message is-error";
                message.hidden = false;
            } finally {
                const ended = lastTrigger?.dataset.status === "Ended";
                saveButton.disabled = ended;
                closingInput.disabled = ended;
                saveButton.textContent = "Save Changes";
                saveButton.classList.remove("is-loading");
                saveButton.removeAttribute("aria-busy");
            }
        });
    }
})();
