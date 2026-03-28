const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        recordVideo: { dir: "/home/jules/verification/videos" }
    });
    const page = await context.newPage();
    try {
        await page.goto("http://localhost:5173");
        await page.waitForTimeout(2000);

        // Click Settings navigation item (it's the 3rd button in the nav bar, the first is global keyboard, then home, then settings)
        await page.locator('nav button').nth(2).click();
        await page.waitForTimeout(2000);

        // Click Lyrion URL input
        await page.getByPlaceholder("http://localhost:9000").click();
        await page.waitForTimeout(1000);

        // Press '9' on the virtual keyboard to ensure it types
        await page.locator('.hg-button').filter({ hasText: '9' }).first().click();
        await page.waitForTimeout(1000);

        // Verify it changed
        await page.screenshot({ path: "/home/jules/verification/screenshots/verification.png" });
        await page.waitForTimeout(2000);
    } finally {
        await context.close();
        await browser.close();
    }
})();