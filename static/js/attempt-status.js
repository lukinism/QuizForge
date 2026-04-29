const attemptForm = document.getElementById("attempt-form");

if (attemptForm && attemptForm.dataset.statusUrl) {
    const checkAttemptStatus = async () => {
        try {
            const response = await fetch(attemptForm.dataset.statusUrl, {
                headers: {Accept: "application/json"},
            });
            if (!response.ok) {
                return;
            }
            const payload = await response.json();
            if (payload.status && !["started", "revision_requested"].includes(payload.status)) {
                window.location.href = payload.detail_url || window.location.href;
            }
        } catch (_) {
            // The next polling tick will try again.
        }
    };

    window.setInterval(checkAttemptStatus, 5000);
}
