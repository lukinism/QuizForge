(() => {
    const refreshIcons = () => {
        if (!window.lucide) {
            return;
        }

        window.lucide.createIcons({
            attrs: {
                "stroke-width": 1.9,
            },
        });
    };

    refreshIcons();

    document.querySelectorAll("[data-member-picker]").forEach((picker) => {
        const search = picker.querySelector("[data-member-search]");
        const dropdown = picker.querySelector("[data-member-dropdown]");
        const toggle = picker.querySelector("[data-member-toggle]");
        const selectedList = picker.querySelector("[data-member-selected]");
        const count = picker.querySelector("[data-member-count]");
        const options = Array.from(picker.querySelectorAll("[data-member-option]"));
        const checkboxes = Array.from(picker.querySelectorAll("[data-member-checkbox]"));

        if (!dropdown || !selectedList || !count) {
            return;
        }

        const initials = (value) => (value || "U").trim().slice(0, 1).toUpperCase();

        const renderSelected = () => {
            const selected = checkboxes.filter((checkbox) => checkbox.checked);
            count.textContent = String(selected.length);
            selectedList.innerHTML = "";

            if (!selected.length) {
                const empty = document.createElement("div");
                empty.className = "member-empty";
                empty.textContent = "Участники пока не выбраны.";
                selectedList.append(empty);
                return;
            }

            selected.forEach((checkbox) => {
                const row = document.createElement("div");
                row.className = "selected-member-row";

                const avatar = document.createElement("span");
                avatar.className = "member-avatar";
                avatar.textContent = initials(checkbox.dataset.userName);

                const text = document.createElement("span");
                text.className = "selected-member-text";

                const name = document.createElement("strong");
                name.textContent = checkbox.dataset.userName || "";

                const dot = document.createElement("span");
                dot.textContent = "·";

                const email = document.createElement("small");
                email.textContent = checkbox.dataset.userEmail || "";

                text.append(name, dot, email);

                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "selected-member-remove";
                remove.setAttribute("aria-label", "Убрать участника");
                remove.innerHTML = '<i data-lucide="x"></i>';
                remove.addEventListener("click", () => {
                    checkbox.checked = false;
                    renderSelected();
                });

                row.append(avatar, text, remove);
                selectedList.append(row);
            });

            refreshIcons();
        };

        const filterOptions = () => {
            const query = (search?.value || "").trim().toLowerCase();
            options.forEach((option) => {
                const haystack = `${option.dataset.name || ""} ${option.dataset.email || ""}`;
                option.hidden = query !== "" && !haystack.includes(query);
            });
        };

        const openDropdown = () => dropdown.classList.add("is-open");
        const closeDropdown = () => dropdown.classList.remove("is-open");

        search?.addEventListener("focus", openDropdown);
        search?.addEventListener("input", () => {
            filterOptions();
            openDropdown();
        });
        toggle?.addEventListener("click", () => {
            dropdown.classList.toggle("is-open");
            search?.focus();
        });

        checkboxes.forEach((checkbox) => {
            checkbox.addEventListener("change", renderSelected);
        });

        document.addEventListener("click", (event) => {
            if (!picker.contains(event.target)) {
                closeDropdown();
            }
        });

        renderSelected();
    });

    document.querySelectorAll("[data-groups-page]").forEach((page) => {
        const search = page.querySelector("[data-groups-search]");
        const filter = page.querySelector("[data-groups-filter]");
        const visibleCount = page.querySelector("[data-groups-visible]");
        const rows = Array.from(page.querySelectorAll("[data-group-row]"));

        const applyGroupsFilter = () => {
            const query = (search?.value || "").trim().toLowerCase();
            const mode = filter?.value || "all";
            let visible = 0;

            rows.forEach((row) => {
                const matchesQuery = `${row.dataset.title || ""} ${row.dataset.description || ""}`.includes(query);
                const isActive = row.dataset.active === "true";
                const matchesMode = mode === "all" || (mode === "active" && isActive) || (mode === "empty" && !isActive);
                const shouldShow = matchesQuery && matchesMode;
                row.hidden = !shouldShow;
                if (shouldShow) {
                    visible += 1;
                }
            });

            if (visibleCount) {
                visibleCount.textContent = String(visible);
            }
        };

        search?.addEventListener("input", applyGroupsFilter);
        filter?.addEventListener("change", applyGroupsFilter);
        applyGroupsFilter();
    });

    document.querySelectorAll("[data-results-page]").forEach((page) => {
        const search = page.querySelector("[data-results-search]");
        const status = page.querySelector("[data-results-status]");
        const test = page.querySelector("[data-results-test]");
        const reset = page.querySelector("[data-results-reset]");
        const visibleCount = page.querySelector("[data-results-visible]");
        const rows = Array.from(page.querySelectorAll("[data-result-row]"));

        const applyResultsFilter = () => {
            const query = (search?.value || "").trim().toLowerCase();
            const statusValue = status?.value || "all";
            const testValue = test?.value || "all";
            let visible = 0;

            rows.forEach((row) => {
                const haystack = `${row.dataset.user || ""} ${row.dataset.testTitle || ""}`;
                const matchesQuery = haystack.includes(query);
                const matchesStatus = statusValue === "all" || row.dataset.status === statusValue;
                const matchesTest = testValue === "all" || row.dataset.testId === testValue;
                const shouldShow = matchesQuery && matchesStatus && matchesTest;
                row.hidden = !shouldShow;
                if (shouldShow) {
                    visible += 1;
                }
            });

            if (visibleCount) {
                visibleCount.textContent = String(visible);
            }
        };

        search?.addEventListener("input", applyResultsFilter);
        status?.addEventListener("change", applyResultsFilter);
        test?.addEventListener("change", applyResultsFilter);
        reset?.addEventListener("click", () => {
            if (search) search.value = "";
            if (status) status.value = "all";
            if (test) test.value = "all";
            applyResultsFilter();
        });

        applyResultsFilter();
    });

    document.querySelectorAll("[data-reports-page]").forEach((page) => {
        const search = page.querySelector("[data-reports-search]");
        const type = page.querySelector("[data-reports-type]");
        const sort = page.querySelector("[data-reports-sort]");
        const body = page.querySelector("[data-reports-body]");
        const visibleCount = page.querySelector("[data-reports-visible]");
        const rows = Array.from(page.querySelectorAll("[data-report-row]"));

        const applyReportsFilter = () => {
            const query = (search?.value || "").trim().toLowerCase();
            const typeValue = type?.value || "all";
            const sortValue = sort?.value || "new";
            let visible = 0;

            const sortedRows = [...rows].sort((first, second) => {
                const a = Number(first.dataset.index || 0);
                const b = Number(second.dataset.index || 0);
                return sortValue === "old" ? a - b : b - a;
            });

            sortedRows.forEach((row) => {
                body?.append(row);
                const matchesQuery = (row.dataset.search || "").includes(query);
                const matchesType = typeValue === "all" || row.dataset.type === typeValue;
                const shouldShow = matchesQuery && matchesType;
                row.hidden = !shouldShow;
                if (shouldShow) {
                    visible += 1;
                }
            });

            if (visibleCount) {
                visibleCount.textContent = String(visible);
            }
        };

        search?.addEventListener("input", applyReportsFilter);
        type?.addEventListener("change", applyReportsFilter);
        sort?.addEventListener("change", applyReportsFilter);
        applyReportsFilter();
    });

    document.querySelectorAll("[data-auth-password-toggle]").forEach((toggle) => {
        const field = toggle.closest(".auth-input")?.querySelector("[data-auth-password]");
        if (!field) {
            return;
        }

        toggle.addEventListener("click", () => {
            const shouldShow = field.type === "password";
            field.type = shouldShow ? "text" : "password";
            toggle.setAttribute("aria-label", shouldShow ? "Скрыть пароль" : "Показать пароль");
            toggle.innerHTML = shouldShow ? '<i data-lucide="eye-off"></i>' : '<i data-lucide="eye"></i>';
            refreshIcons();
        });
    });

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
