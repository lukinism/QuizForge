const testForm = document.getElementById("attempt-form");

if (testForm) {
    const instruction = document.getElementById("test-instruction");
    const startButton = document.querySelector("[data-start-test]");
    const flowMode = testForm.dataset.flowMode || "all_questions";
    const hasInstruction = testForm.dataset.hasInstruction === "true";
    const allowSkip = testForm.dataset.allowSkip === "true";
    const questions = Array.from(testForm.querySelectorAll(".question-step"));
    const prevButton = testForm.querySelector("[data-prev-question]");
    const nextButton = testForm.querySelector("[data-next-question]");
    const skipButton = testForm.querySelector("[data-skip-question]");
    const submitButton = testForm.querySelector("button[type='submit']");
    const progress = testForm.querySelector("[data-question-progress]");
    let currentIndex = 0;

    const setFormVisible = (visible) => {
        testForm.classList.toggle("d-none", !visible);
    };

    const questionHasAnswer = (question) => {
        const checkedInputs = question.querySelectorAll("input[type='radio']:checked, input[type='checkbox']:checked");
        if (checkedInputs.length > 0) {
            return true;
        }
        const textFields = question.querySelectorAll("input[type='text'], textarea");
        if (Array.from(textFields).some((field) => field.value.trim().length > 0)) {
            return true;
        }
        const selects = question.querySelectorAll("select");
        if (!selects.length) {
            return false;
        }
        return Array.from(selects).every((select) => select.value && !select.value.endsWith("::"));
    };

    const showAnswerRequired = () => {
        const question = questions[currentIndex];
        if (!question) {
            return false;
        }
        question.classList.add("border", "border-danger");
        const existing = question.querySelector("[data-answer-required]");
        if (!existing) {
            const message = document.createElement("div");
            message.className = "alert alert-warning mt-3 mb-0";
            message.dataset.answerRequired = "true";
            message.textContent = "Ответьте на вопрос или включите пропуск вопросов в настройках теста.";
            question.querySelector(".card-body").appendChild(message);
        }
        return false;
    };

    const clearAnswerRequired = (question) => {
        question.classList.remove("border", "border-danger");
        const message = question.querySelector("[data-answer-required]");
        if (message) {
            message.remove();
        }
    };

    const syncQuestion = () => {
        const oneByOne = flowMode === "one_by_one";
        questions.forEach((question, index) => {
            question.classList.toggle("d-none", oneByOne && index !== currentIndex);
            if (questionHasAnswer(question)) {
                clearAnswerRequired(question);
            }
        });

        if (prevButton) {
            prevButton.classList.toggle("d-none", !oneByOne);
            prevButton.disabled = currentIndex === 0;
        }
        if (nextButton) {
            nextButton.classList.toggle("d-none", !oneByOne || currentIndex >= questions.length - 1);
        }
        if (skipButton) {
            skipButton.classList.toggle("d-none", !oneByOne || !allowSkip || currentIndex >= questions.length - 1);
        }
        if (submitButton) {
            submitButton.classList.toggle("d-none", oneByOne && currentIndex < questions.length - 1);
        }
        if (progress) {
            progress.textContent = oneByOne && questions.length
                ? `Вопрос ${currentIndex + 1} из ${questions.length}`
                : "";
        }
    };

    if (hasInstruction) {
        setFormVisible(false);
    }

    if (startButton) {
        startButton.addEventListener("click", () => {
            if (instruction) {
                instruction.classList.add("d-none");
            }
            setFormVisible(true);
            syncQuestion();
        });
    }

    if (prevButton) {
        prevButton.addEventListener("click", () => {
            currentIndex = Math.max(currentIndex - 1, 0);
            syncQuestion();
        });
    }

    if (nextButton) {
        nextButton.addEventListener("click", () => {
            if (!allowSkip && !questionHasAnswer(questions[currentIndex])) {
                showAnswerRequired();
                return;
            }
            currentIndex = Math.min(currentIndex + 1, questions.length - 1);
            syncQuestion();
        });
    }

    if (skipButton) {
        skipButton.addEventListener("click", () => {
            currentIndex = Math.min(currentIndex + 1, questions.length - 1);
            syncQuestion();
        });
    }

    testForm.addEventListener("submit", (event) => {
        if (allowSkip) {
            return;
        }
        const firstEmptyIndex = questions.findIndex((question) => !questionHasAnswer(question));
        if (firstEmptyIndex === -1) {
            return;
        }
        event.preventDefault();
        currentIndex = firstEmptyIndex;
        syncQuestion();
        showAnswerRequired();
    });

    syncQuestion();
}
