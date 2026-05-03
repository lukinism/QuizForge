document.querySelectorAll(".question-editor").forEach((form) => {
    const select = form.querySelector(".question-type-select");
    const mediaTypes = ["image", "audio", "video", "file"];
    const manualReviewTypes = ["free_answer", "practical"];
    const mediaAccepts = {
        image: "image/*",
        audio: "audio/*",
        video: "video/*",
        file: "image/*,audio/*,video/*,.pdf,.docx,.xlsx,.pptx,.txt,.csv",
    };
    const singleCorrectTypes = ["single_choice", ...mediaTypes];
    const textCorrectTypes = ["text_answer", "fill_blank", "code"];

    const setFieldVisible = (selector, visible) => {
        form.querySelectorAll(selector).forEach((element) => {
            element.classList.toggle("d-none", !visible);
            element.querySelectorAll("input, textarea, select").forEach((input) => {
                input.disabled = !visible;
            });
        });
    };

    const optionLabelFor = (type) => {
        if (type === "matching") {
            return "Пары соответствия";
        }
        if (type === "ordering") {
            return "Элементы в правильном порядке";
        }
        if (textCorrectTypes.includes(type)) {
            return "Допустимые правильные ответы";
        }
        return "Варианты ответа";
    };

    const syncInputTypes = () => {
        const type = select ? select.value : "single_choice";
        setFieldVisible(".question-field-media", mediaTypes.includes(type));
        setFieldVisible(".question-field-code", type === "code");
        setFieldVisible(".question-field-options", !manualReviewTypes.includes(type));
        form.querySelectorAll('input[name="media_file"]').forEach((input) => {
            input.accept = mediaAccepts[type] || mediaAccepts.file;
        });
        const optionsLabel = form.querySelector(".question-options-label");
        if (optionsLabel) {
            optionsLabel.textContent = optionLabelFor(type);
        }

        const inputs = form.querySelectorAll(".correct-flag");
        inputs.forEach((input) => {
            input.type = singleCorrectTypes.includes(type) ? "radio" : "checkbox";
            if (textCorrectTypes.includes(type)) {
                input.checked = true;
            }
        });

        form.querySelectorAll(".match-input").forEach((input) => {
            input.classList.toggle("d-none", type !== "matching");
            input.disabled = type !== "matching";
            input.required = type === "matching";
        });
        form.querySelectorAll(".order-input").forEach((input) => {
            input.classList.toggle("d-none", type !== "ordering");
            input.disabled = type !== "ordering";
            input.required = type === "ordering";
        });
        form.querySelectorAll(".correct-input-wrap").forEach((wrapper) => {
            wrapper.classList.toggle("d-none", ["matching", "ordering"].includes(type));
            wrapper.querySelectorAll("input").forEach((input) => {
                input.disabled = ["matching", "ordering"].includes(type);
            });
        });
    };

    form.querySelectorAll(".js-add-option").forEach((button) => {
        button.addEventListener("click", () => {
            const optionsList = form.querySelector(".options-list");
            const index = optionsList.querySelectorAll(".option-row").length;
            const wrapper = document.createElement("div");
            wrapper.className = "input-group mb-2 option-row";
            wrapper.innerHTML = `
                <span class="input-group-text">${index + 1}</span>
                <input class="form-control" type="text" name="option_text" required>
                <input class="form-control match-input" type="text" name="match_text" placeholder="Соответствие">
                <input class="form-control order-input" type="number" min="1" name="order_index" value="${index + 1}" placeholder="Порядок">
                <span class="input-group-text correct-input-wrap">
                    <input class="form-check-input mt-0 correct-flag" type="${select && singleCorrectTypes.includes(select.value) ? "radio" : "checkbox"}" name="correct_option" value="${index}">
                </span>
            `;
            optionsList.appendChild(wrapper);
            syncInputTypes();
        });
    });

    if (select) {
        select.addEventListener("change", syncInputTypes);
    }
    syncInputTypes();
});

document.querySelectorAll("[data-test-preview-modal]").forEach((modal) => {
    modal.addEventListener("shown.bs.modal", () => {
        if (window.renderMath) {
            window.renderMath(modal);
        }
    });
});

document.querySelectorAll("[data-copy-link]").forEach((button) => {
    button.addEventListener("click", async () => {
        const input = button.closest(".copy-link-box")?.querySelector("input");
        if (!input) {
            return;
        }
        input.select();
        try {
            await navigator.clipboard.writeText(input.value);
            button.innerHTML = '<i data-lucide="check"></i>';
            if (window.lucide) {
                window.lucide.createIcons({ attrs: { "stroke-width": 1.9 } });
            }
            window.setTimeout(() => {
                button.innerHTML = '<i data-lucide="copy"></i>';
                if (window.lucide) {
                    window.lucide.createIcons({ attrs: { "stroke-width": 1.9 } });
                }
            }, 1200);
        } catch (_) {
            document.execCommand("copy");
        }
    });
});
