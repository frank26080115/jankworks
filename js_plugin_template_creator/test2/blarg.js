function runDemoTextReplacement() {
    const target = document.getElementById("js-demo-text");
    if (!target) {
        return;
    }

    target.textContent = whale_talk;
}
