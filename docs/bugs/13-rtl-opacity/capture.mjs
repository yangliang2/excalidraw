import { chromium } from "/Users/80268204/Documents/ChatGPT/REA/node_modules/playwright-core/index.mjs";
const b=await chromium.launch({executablePath:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"});
try {
for(const lang of ["en","ar"]){
const c=await b.newContext({locale:lang, viewport:{width:1200,height:800}});
await c.addInitScript(lang=>localStorage.setItem("i18nextLng",lang),lang);
const p=await c.newPage();await p.goto("https://yangliang2.github.io/excalidraw/pr-12/",{waitUntil:"domcontentloaded",timeout:90000});
await p.locator("canvas").first().waitFor({timeout:90000});await p.keyboard.press("r");await p.mouse.move(470,250);await p.mouse.down();await p.mouse.move(700,400);await p.mouse.up();
const input=p.locator('input[data-testid="opacity"]');await input.waitFor();await input.focus();await p.keyboard.press("Home");await p.keyboard.press("ArrowUp");await p.keyboard.press("ArrowUp");
console.log(lang,await input.evaluate(el=>({lang:document.documentElement.lang,dir:getComputedStyle(el).direction,value:el.value,label:el.closest("label").textContent,gradient:getComputedStyle(el).backgroundImage})));
await input.locator('xpath=ancestor::label').screenshot({path:lang+".png"});await c.close();
}
}finally{await b.close();}
