// Resets the store-screenshot account on the live API before the Appium screenshot run.
// Needs TEST_USER and TEST_PWD (the account's sign-in), then signs in on the device with them.
const user = process.env.TEST_USER, pwd = process.env.TEST_PWD;
const demoWeek = require('../fixtures/demo-week.json');
async function main() {
  const token = await signIn('https://api.samplerecipes.example/v2/auth', user, pwd);
  await fetch('https://api.samplerecipes.example/v2/me/plan', { method: 'DELETE', headers: { authorization: token } });
  await fetch('https://api.samplerecipes.example/v2/me/plan', { method: 'PUT', headers: { authorization: token },
    body: JSON.stringify(demoWeek) });
}
main();
