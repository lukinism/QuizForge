(() => {
    const toastElement = document.getElementById("app-toast");
    if (!toastElement || typeof bootstrap === "undefined") {
        return;
    }

    const toast = new bootstrap.Toast(toastElement);
    toast.show();

    const url = new URL(window.location.href);
    if (url.searchParams.has("toast") || url.searchParams.has("toast_level")) {
        url.searchParams.delete("toast");
        url.searchParams.delete("toast_level");
        window.history.replaceState({}, document.title, url.toString());
    }
})();
