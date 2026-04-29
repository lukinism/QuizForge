const timer = document.getElementById("attempt-timer");

if (timer) {
    let seconds = Number(timer.dataset.seconds || "0");
    const timerValue = timer.querySelector(".timer-value");

    const format = (value) => {
        const hrs = Math.floor(value / 3600).toString().padStart(2, "0");
        const mins = Math.floor((value % 3600) / 60).toString().padStart(2, "0");
        const secs = Math.floor(value % 60).toString().padStart(2, "0");
        return `${hrs}:${mins}:${secs}`;
    };

    const update = () => {
        timerValue.textContent = format(seconds);
        if (seconds <= 0) {
            const form = document.getElementById("attempt-form");
            if (form) {
                form.submit();
            }
            return;
        }
        seconds -= 1;
    };

    update();
    window.setInterval(update, 1000);
}
