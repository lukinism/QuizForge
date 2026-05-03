(function () {
    window.renderMath = function (root) {
        if (!window.MathJax || !window.MathJax.typesetPromise) {
            return Promise.resolve();
        }
        if (root && window.MathJax.typesetClear) {
            window.MathJax.typesetClear([root]);
        }
        return window.MathJax.typesetPromise(root ? [root] : undefined);
    };

    document.addEventListener("DOMContentLoaded", function () {
        window.renderMath();
    });
})();
