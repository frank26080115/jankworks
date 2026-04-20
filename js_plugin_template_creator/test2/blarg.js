function runDemoTextReplacement() {
    const target = document.getElementById("js-demo-text");
    if (!target) {
        return;
    }

    target.textContent = "The demo JavaScript replaced the original text successfully.";
}
