const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch();
  const page = await browser.newPage();

  // Login via API to get token and set local storage
  await page.goto('http://localhost:5173/login');
  
  // Intercept network requests
  page.on('response', async (response) => {
    if (response.url().includes('/api/groups/') && response.request().method() === 'GET') {
      console.log('--- NETWORK RESPONSE FOR /groups/ ---');
      console.log('Status:', response.status());
      try {
        const text = await response.text();
        console.log('Body:', text);
      } catch (e) {
        console.log('Could not read body:', e.message);
      }
      console.log('--------------------------------------');
    }
  });

  // Execute login logic in browser context
  await page.evaluate(() => {
    localStorage.setItem('access_token', 'test_token'); // Mock token, but wait, the backend needs a real token!
  });
  
  await browser.close();
})();
