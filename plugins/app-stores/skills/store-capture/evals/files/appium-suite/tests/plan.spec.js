// End-to-end checks run against a local Appium server (appium --address 127.0.0.1 --port 4723).
const { remote } = require('webdriverio');

const caps = {
  ios: { platformName: 'iOS', 'appium:automationName': 'XCUITest', 'appium:bundleId': 'com.example.samplerecipes' },
  android: { platformName: 'Android', 'appium:automationName': 'UiAutomator2',
             'appium:appPackage': 'com.example.samplerecipes', 'appium:appActivity': '.MainActivity' },
};

describe('meal plan', () => {
  it('opens a recipe from the plan', async () => {
    const driver = await remote({ hostname: '127.0.0.1', port: 4723, capabilities: caps[process.env.PLATFORM || 'ios'] });
    await (await driver.$('~tab-plan')).click();
    await (await driver.$('~plan-day-monday')).click();
    await (await driver.$('~recipe-title')).waitForDisplayed({ timeout: 10000 });
    await (await driver.$('~tab-shopping')).click();
    await (await driver.$('~shopping-list')).waitForDisplayed({ timeout: 10000 });
    await driver.deleteSession();
  });
});
